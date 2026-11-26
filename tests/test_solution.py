"""최적해가 제약을 실제로 지키는지 독립적으로 다시 확인한다.  python -m pytest -q tests

시나리오마다 한 번만 풀고 결과를 재사용한다 (module 단위 캐시).
"""
import math

import pytest

from lng import optimizer as opt
from lng.planner import Scenario, build_inputs
from lng.schemas import CARGO_KT

SCENARIOS = {
    "baseline": Scenario(),
    "hormuz_6m": Scenario(name="hormuz_6m", hormuz_blocked_months=6, spot_price_multiplier=1.5, spot_volume_multiplier=0.6),
    "tight": Scenario(name="tight", hormuz_blocked_months=6, spot_price_multiplier=1.8, spot_volume_multiplier=0.25),
}


@pytest.fixture(scope="module")
def solved():
    out = {}
    for name, sc in SCENARIOS.items():
        inp, _ = build_inputs(sc)
        out[name] = (inp, opt.solve(inp))
    return out


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_constraints(solved, name):
    inp, res = solved[name]
    assert res["status"] == "Optimal"
    a, inv = res["allocation"], res["inventory"].set_index(["terminal", "month"])
    pipe = res["pipeline"]
    term = inp.terminals.set_index("terminal")
    avail = inp.avail.set_index(["source", "month"])["avail_kt"]
    src = inp.sources.set_index("source")
    tol = 1.0  # 출력 반올림(0.1kt) 허용

    # 공급원 월 상한(카고 올림), 연간 상한, take-or-pay
    for s in src.index:
        tot = 0.0
        for m in inp.months:
            c = a[(a.source == s) & (a.month == m)]["kt"].sum() / CARGO_KT
            assert c <= math.ceil(avail.get((s, m), 0) / CARGO_KT - 1e-9) + 0.01
            assert abs(c - round(c)) < 0.01  # 공급원-월 카고 수는 정수
            tot += c * CARGO_KT
        # 연도별 상한과 take-or-pay. 신규 계약 후보는 계약한 비율만큼만
        frac = (res.get("contracts") or {}).get(s, 1.0)
        for y in sorted({m[:4] for m in inp.months}):
            ms = [m for m in inp.months if m[:4] == y]
            year_av = sum(avail.get((s, m), 0) for m in ms) * frac
            lifted = a[(a.source == s) & (a.month.isin(ms))]["kt"].sum()
            assert lifted <= year_av + CARGO_KT / 2 + tol, (s, y)
            top = src.loc[s, "top_ratio"] * year_av - CARGO_KT
            if top > 0:
                assert lifted >= top - tol, (s, y)

    # 재고 수지, 저장 용량, 안전재고, 하역 상한
    for t in term.index:
        cap = term.loc[t, "storage_kt"]
        prev = cap * term.loc[t, "init_inv_ratio"]
        for m in inp.months:
            r = inv.loc[(t, m)]
            arr = a[(a.terminal == t) & (a.month == m)]["kt"].sum()
            pin = pipe[(pipe["to"] == t) & (pipe.month == m)]["kt"].sum() if len(pipe) else 0
            pout = pipe[(pipe["from"] == t) & (pipe.month == m)]["kt"].sum() if len(pipe) else 0
            expected = prev + arr + pin - pout - (r.demand_kt - r.shortage_kt)
            assert abs(expected - r.inventory_kt) < 1.0, (t, m)
            assert opt.SAFETY_RATIO * cap - 0.1 <= r.inventory_kt <= cap + 0.1
            assert a[(a.terminal == t) & (a.month == m)]["cargoes"].sum() <= term.loc[t, "max_cargo_per_month"] + 0.01
            prev = r.inventory_kt
        assert prev >= opt.END_INV_RATIO * cap - 0.1


def test_hormuz_blocks_qatar(solved):
    inp, res = solved["hormuz_6m"]
    a = res["allocation"]
    assert a[(a.source == "QATAR_LT") & (a.month.isin(inp.months[:6]))].empty


def test_hormuz_costs_more_than_baseline(solved):
    assert solved["hormuz_6m"][1]["objective_musd"] > solved["baseline"][1]["objective_musd"]


def test_not_time_limited(solved):
    """실패하면 솔버가 시간 제한까지 돈 것 (Windows CBC 문제일 가능성)."""
    for name, (_, res) in solved.items():
        assert not res["time_limited"], f"{name}: {res['solve_seconds']}s"


def test_parse_job_output():
    """Studio job 응답에서 additional_values와 JSON text를 합쳐 읽는지 확인 (가짜 응답)."""
    import json

    from lng.studio_client import normalize_record, parse_job_output

    job = {"status": "completed", "output": [
        {"model": "extract", "content": [{"type": "output_text",
                                          "text": "추출 완료",
                                          "additional_values": json.dumps({"doc_type": "semi_annual_report",
                                                                           "project": "P", "authorized_mtpa": "15 MTPA"})}]},
        {"model": "instruct", "content": [{"type": "output_text", "text": json.dumps({"progress_note": "ok"})}]},
    ]}
    fields, texts = parse_job_output(job)
    rec = normalize_record(fields)
    assert rec["project"] == "P" and rec["authorized_mtpa"] == 15.0 and rec["progress_note"] == "ok"
    assert texts[0] == "추출 완료"


def test_normalize_studio_values():
    """실제 Studio Extract 응답 형식({"_value", "confidence", "page"})을 값으로 풀고 가동일을 보충하는지 확인."""
    from lng.studio_client import normalize_record

    raw = {
        "project": {"_value": "Commonwealth LNG", "confidence": "low", "page": 1, "confidence_score": 0.7},
        "report_date": {"_value": "2026-10-01", "confidence": "high", "page": 1},
        "expected_operational_date": {"_value": "", "confidence": "low", "page": -1},
        "progress_note": {"_value": "건설은 일정대로 진행 중이고 상업운전은 2030년을 목표로 하고 있다.", "page": 1},
        "long_term_contracts": [{"buyer": {"_value": "Glencore LTD", "page": 1}, "mtpa": {"_value": 1, "page": 1},
                                 "start_year": {"_value": 0, "page": 1}, "term_years": {"_value": 20, "page": 1}}],
        "step_run_id": "x",
    }
    rec = normalize_record(raw)
    assert rec["project"] == "Commonwealth LNG" and rec["doc_type"] == "semi_annual_report"
    assert rec["expected_operational_date"] == "2030-12-01" and rec["expected_operational_date_inferred"]
    assert rec["long_term_contracts"][0]["start_year"] is None and rec["long_term_contracts"][0]["mtpa"] == 1.0
    assert "step_run_id" not in rec and rec["_confidence"]["project"]["confidence"] == "low"


def test_cumulative_contracts_and_uncontracted():
    """보고서마다 새 계약만 적혀도 누적으로 합치고, 미계약은 '허가 - 확보'로 계산하는지."""
    from lng.supply import project_profiles

    base = {"doc_type": "semi_annual_report", "project": "P", "docket": "19-134-LNG"}
    recs = [
        dict(base, report_date="2024-04-01"),
        dict(base, report_date="2025-10-01", long_term_contracts=[{"buyer": "JERA Co., Inc.", "mtpa": 1.0},
                                                                   {"buyer": "Glencore LTD", "mtpa": 2.0}]),
        dict(base, report_date="2026-04-01", authorized_mtpa=9.5, long_term_contracts=[{"buyer": "Glencore LTD", "mtpa": 1.0},
                                                                                       {"buyer": "Aramco Trading", "mtpa": 1.0}]),
        dict(base, report_date="2026-10-01", authorized_mtpa=9.5, uncontracted_mtpa=0,
             progress_note="약 9.5 MTPA 허가용량 중 8.5 MTPA를 확보했으며 상업운전은 2030년 목표",
             expected_operational_date="2030-12-01", expected_operational_date_inferred=True),
    ]
    p = project_profiles(recs).iloc[0]
    assert p["reports"] == 4 and p["dated_reports"] == 1
    assert p["contracts"] == 3 and p["contracted_mtpa"] == 4.0
    assert p["uncontracted_mtpa"] == 1.0 and p["tau_months"] >= 6


def test_derive_status_from_notes():
    """진행 요약 문장에서 단계와 실제 첫 LNG 날짜, 목표 연도를 뽑는지 (Golden Pass, Commonwealth 실제 문장)."""
    from lng.studio_client import derive_status

    gp = derive_status("트레인 1의 시운전과 가동 개시가 진행되어 2026년 3월 30일 첫 LNG 생산을 달성했고, 트레인 2와 3의 건설은 계속 진행 중이다.")
    assert gp["stage"] == "operating" and gp["first_lng_date"] == "2026-03-30" and "target_year" not in gp
    assert derive_status("GPLNG는 Train 1 장비 시운전을 시작했고 현장 공사를 진전시켰다.")["stage"] == "commissioning"
    assert derive_status("커먼웰스는 장기 LNG 판매를 위한 상업 협의를 진행 중이며 건설을 향해 FERC와 협력")["stage"] == "pre_fid"
    cw = derive_status("FID와 건설금융 종결이 발표되었고 건설은 일정대로 진행 중이고 상업운전은 2030년을 목표로 하고 있다.")
    assert cw["stage"] == "construction" and cw["target_year"] == 2030


def test_base_operating_and_korean_buyers():
    """기존 설비 가동 표현과 한국 구매자 이름 판별 (실제 보고서 문장)."""
    from lng.studio_client import derive_status
    from lng.supply import _docket_key, is_korean_buyer

    assert derive_status("시설 건설은 완료되었고 현재 LNG를 생산하며 계속 수출 중이다.").get("base_operating")
    assert derive_status("액화 프로젝트 1~3호기는 2020년 8월 10일 기준 모두 상업 운전에 들어갔고, 확장 프로젝트는 EPC 재입찰").get("base_operating")
    assert not derive_status("Stage 5 Project 확장은 FERC에서 계류 중이며 건설 활동이 없었다.").get("base_operating")
    assert is_korean_buyer({"buyer": "SK Gas Trading LLC"}) and is_korean_buyer({"buyer": "Posco International Corporation"})
    assert not is_korean_buyer({"buyer": "ENN Natural Gas"})
    assert _docket_key("12-88-LNG, 12-156-LNG") == _docket_key("12-88-LNG") == "12-88-LNG"
