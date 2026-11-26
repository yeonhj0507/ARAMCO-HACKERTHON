"""워크플로우 A, B, C를 잇는 흐름 테스트 (Studio 대신 정답지와 코드 검산을 쓰는 가짜 모드)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from lng import demand, execdoc, planner, supply

ROOT = Path(__file__).resolve().parents[1]


def _a_answers():
    f = next(iter(sorted((ROOT / "submission").glob("*_answer.json"))), None)
    if not f:
        pytest.skip("submission 정답지가 없습니다")
    return json.loads(f.read_text(encoding="utf-8"))["cases"]


def test_profiles_from_params():
    params = [dict(c["answer"], case_key=c["case_id"]) for c in _a_answers()]
    prof = supply.profiles_from_params(params, as_of=pd.Timestamp("2026-11-01"))
    by = prof.set_index("project")
    assert by.loc["A", "operating"] and by.loc["A", "latest_expected"] == "2026-03"
    assert by.loc["B", "latest_expected"] == "2030-12" and by.loc["B", "tau_months"] == 12.5
    assert by.loc["B", "uncontracted_mtpa"] == 1.0
    assert by.loc["D", "latest_expected"] is None  # pre_fid, 날짜 없음 -> 계획 기간 안 공급 없음
    months = list(pd.date_range("2027-01-01", periods=12, freq="MS"))
    avail, _, _ = supply.us_supply_from_params(params, months)
    unc = avail[avail.source == "US_UNCONTRACTED"]["avail_kt"]
    assert (unc >= 0).all()


def test_plan_targets_and_terminals():
    plan = json.loads((ROOT / "data" / "plans" / "b_answer.json").read_text(encoding="utf-8"))["cases"][0]["answer"]
    tg = demand.plan_annual_targets(plan, [2026, 2027, 2032, 2040])
    assert tg[2026]["city_gas"] == 23560 and tg[2032]["power"] == 20820
    assert 23560 < tg[2027]["city_gas"] < 27310  # 2026~2032 사이 직선 보간
    assert tg[2040]["power"] == 12840            # 범위 밖은 끝값
    terms = pd.DataFrame({"terminal": ["PYEONGTAEK", "JEJU"], "storage_kt": [1400.0, 90.0]})
    t2, changed = demand.apply_terminal_plan(terms, plan)
    assert t2.set_index("terminal").loc["PYEONGTAEK", "storage_kt"] == 1500 and len(changed) == 2


def test_apply_plan_scales_annual_total():
    plan = {"base_demand_rows": ["2027,24000,22000,46000"]}
    months = [f"2027-{m:02d}" for m in range(1, 13)]
    nat = pd.DataFrame([{"use": u, "month": m, "demand_kt": 1500.0} for u in ("city_gas", "power") for m in months])
    out, f = demand.apply_plan(nat, plan)
    assert abs(out[out.use == "city_gas"]["demand_kt"].sum() - 24000) < 1e-6
    assert f["power_2027"] == round(22000 / 18000, 3)


def test_check_tables_matches_answer_key():
    ans = json.loads((ROOT / "data" / "allocations" / "c_answer.json").read_text(encoding="utf-8"))
    for c in ans["cases"]:
        side = (ROOT / "data" / "allocations" / c["file"]).with_suffix(".json")
        t = json.loads(side.read_text(encoding="utf-8"))
        got = execdoc.check_tables(t["tables"], c["answer"]["plan_id"])
        assert not execdoc.compare_checks(got, c["answer"]), c["case_id"]


def test_cycle_offline(monkeypatch, tmp_path):
    from lng import cycle, workflows
    monkeypatch.setenv("LNG_STUDIO_FAKE", "1")
    monkeypatch.setattr(workflows, "EXEC_DIR", tmp_path / "exec")
    monkeypatch.setattr(cycle, "ORDERS_DIR", tmp_path / "orders")
    out = cycle.run_cycle(planner.Scenario(name="hormuz3", hormuz_blocked_months=3), log=lambda *_: None)
    assert out["status"] == "PENDING_APPROVAL"
    assert out["order"]["studio_check"]["decision"] == "승인 요청"
    assert (tmp_path / "orders" / f"{out['order']['order_id']}.json").exists()


def test_check_plan_replans_edited_doc(monkeypatch, tmp_path):
    import shutil
    from lng import cycle, workflows
    monkeypatch.setenv("LNG_STUDIO_FAKE", "1")
    monkeypatch.setattr(workflows, "EXEC_DIR", tmp_path / "exec")
    monkeypatch.setattr(cycle, "ORDERS_DIR", tmp_path / "orders")
    src = ROOT / "data" / "allocations" / "C_set04.pdf"   # 인천 재고가 저장용량을 넘게 고친 실행안
    pdf = tmp_path / "edited.pdf"
    shutil.copyfile(src, pdf)
    shutil.copyfile(src.with_suffix(".json"), pdf.with_suffix(".json"))
    out = cycle.check_plan(pdf, log=lambda *_: None)
    assert out["studio"]["decision"] == "재계획 필요" and out["studio"]["capacity_rows"]
    assert out["replan"]["status"] == "PENDING_APPROVAL"
