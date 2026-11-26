"""시나리오 하나를 받아 공급 예측 -> 수요 예측 -> 최적화까지 한 번에 돌린다."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import demand as demand_mod
from . import supply as supply_mod
from . import workflows
from .optimizer import OptInputs, solve
from .schemas import MTPA_TO_KT_PER_MONTH
from .studio_client import load_extractions

DATA = Path(__file__).resolve().parents[1] / "data" / "sample"
US_UNCONTRACTED_PREMIUM = 60.0  # 미계약 물량 신규 협상 시 단가 프리미엄 ($/t, 가정)


@dataclass
class Scenario:
    name: str = "baseline"
    start_month: str = "2027-01"
    horizon: int = 60                     # 2027~2031 5년. 신규 계약 후보는 대부분 2029년 이후 가동
    hormuz_blocked_months: int = 0        # 시작월부터 몇 달간 호르무즈 경유 물량 0
    spot_price_multiplier: float = 1.0
    spot_volume_multiplier: float = 1.0   # 현물 확보 경쟁으로 물량이 줄어드는 효과
    us_extra_delay_months: int = 0
    demand_multiplier: float = 1.0
    use_studio: bool = True               # Studio A 결과와 수급계획 기준 자료가 있으면 사용
    allow_new_contracts: bool = True      # False면 A가 찾은 미국 신규 계약 후보를 쓰지 않는다 (다원화 효과 비교용)
    min_stable_share: float = 0.8         # 장기(안정) 계약 최소 비중. 나머지 20%만 현물(단기)로 수익성을 노린다
    notes: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _static():
    terminals = pd.read_csv(DATA / "terminals.csv")
    sources = pd.read_csv(DATA / "sources.csv")
    history = pd.read_csv(DATA / "demand_history.csv")
    return terminals, sources, history


def build_inputs(sc: Scenario):
    terminals, sources, history = _static()
    plan = workflows.load_plan() if sc.use_studio else None
    terminals, terminal_changes = demand_mod.apply_terminal_plan(terminals, plan)
    months_ts = list(pd.date_range(sc.start_month + "-01", periods=sc.horizon, freq="MS"))
    months = [m.strftime("%Y-%m") for m in months_ts]

    # 공급
    params = workflows.load_params() if sc.use_studio else []
    if params:  # 워크플로우 A 결과 (검토 필요는 승인된 것만)
        us_avail, profiles, prob_detail = supply_mod.us_supply_from_params(params, months_ts, sc.us_extra_delay_months)
        supply_source = f"Studio A 파라미터 {len(params)}건"
    else:  # 예전 경로: 보고서별 추출 레코드
        records = load_extractions()
        us_avail, profiles, prob_detail = supply_mod.us_supply_forecast(records, months_ts, sc.us_extra_delay_months)
        supply_source = f"보고서 추출 레코드 {len(records)}건"
    us_avail = us_avail[us_avail.source != "US_UNCONTRACTED"]
    # 신규 계약 후보: A가 미계약 물량을 찾은 미국 프로젝트 하나하나
    cand_avail, candidates = supply_mod.us_candidates(profiles, months_ts)
    if not sc.allow_new_contracts:
        cand_avail, candidates = cand_avail.iloc[0:0], []
    src = sources.copy()
    src["candidate"] = False
    us_row = src[src.source == "US_LT"].iloc[0]
    for c in candidates:
        row = us_row.copy()
        row["source"], row["kind"], row["annual_mtpa"] = c["source"], "candidate", c["max_contract_mtpa"]
        row["price_usd_t"] = us_row["price_usd_t"] + US_UNCONTRACTED_PREMIUM
        row["top_ratio"], row["via_hormuz"], row["candidate"] = 0.9, False, True
        src = pd.concat([src, row.to_frame().T], ignore_index=True)
    src.loc[src.source == "SPOT", "price_usd_t"] *= sc.spot_price_multiplier
    src["short_term"] = src["source"] == "SPOT"
    src = src.astype({"price_usd_t": float, "voyage_days": float, "top_ratio": float, "candidate": bool, "short_term": bool})

    rows = []
    for _, s in sources.iterrows():
        if s["source"] == "US_LT":
            continue
        for i, m in enumerate(months):
            kt = s["annual_mtpa"] * MTPA_TO_KT_PER_MONTH
            if s["via_hormuz"] and i < sc.hormuz_blocked_months:
                kt = 0.0
            if s["source"] == "SPOT":
                kt *= sc.spot_volume_multiplier
            rows.append({"source": s["source"], "month": m, "avail_kt": kt})
    avail = pd.concat([pd.DataFrame(rows), us_avail, cand_avail], ignore_index=True)

    # 수요
    national = demand_mod.forecast_national(history, months_ts)
    national, plan_factors = demand_mod.apply_plan(national, plan)
    dem = demand_mod.split_by_terminal(national, terminals, sc.demand_multiplier)

    inp = OptInputs(months=months, terminals=terminals,
                    sources=src[["source", "price_usd_t", "voyage_days", "top_ratio", "candidate", "short_term"]],
                    avail=avail, demand=dem, min_stable_share=sc.min_stable_share)
    context = {"profiles": profiles, "prob_detail": prob_detail, "candidates": candidates, "source_table": src, "national_demand": national, "terminals": terminals,
               "inputs_used": {"supply": supply_source,
                               "demand_plan": (plan.get("plan_name") + " (전산 기준 자료)") if plan else "없음 (실적 추세만)",
                               "plan_factors": plan_factors, "terminal_changes": terminal_changes}}
    return inp, context


def run(sc: Scenario) -> dict:
    inp, ctx = build_inputs(sc)
    res = solve(inp, time_limit=60)
    res["scenario"] = asdict(sc)
    avail = inp.avail.copy()
    for s, frac in (res.get("contracts") or {}).items():  # 후보는 실제로 계약한 만큼만 공급 가능량으로 본다
        avail.loc[avail.source == s, "avail_kt"] *= frac
    res["avail"] = avail
    res["demand"] = inp.demand
    res.update(ctx)
    return res


def scenario_label(d: dict | None) -> str:
    """시나리오 조건을 사람이 읽는 말로. LLM이 지은 이름 대신 화면에 쓴다."""
    d = d or {}
    parts = []
    if d.get("hormuz_blocked_months"):
        parts.append(f"호르무즈 {d['hormuz_blocked_months']}개월 차단")
    dm = float(d.get("demand_multiplier") or 1.0)
    if abs(dm - 1) > 1e-9:
        parts.append(f"수요 {abs(dm - 1):.0%} {'증가' if dm > 1 else '감소'}")
    sv = float(d.get("spot_volume_multiplier") or 1.0)
    if abs(sv - 1) > 1e-9:
        parts.append(f"현물 확보 {sv:.0%}")
    sp = float(d.get("spot_price_multiplier") or 1.0)
    if abs(sp - 1) > 1e-9:
        parts.append(f"현물 가격 {abs(sp - 1):.0%} {'상승' if sp > 1 else '하락'}")
    if d.get("us_extra_delay_months"):
        parts.append(f"미국 프로젝트 {d['us_extra_delay_months']}개월 추가 지연")
    ms = d.get("min_stable_share")
    if ms is not None and abs(float(ms) - 0.8) > 1e-9:
        parts.append(f"장기계약 비중 {float(ms):.0%} 이상" if float(ms) > 0 else "장기 비중 원칙 없이")
    if d.get("allow_new_contracts") is False:
        parts.append("신규 계약 없이")
    return ", ".join(parts) or "평상시"


def real_cost(res: dict) -> float:
    """실제 비용 (구매, 운송, 재고, 배관). 부족과 안정성 원칙 벌점은 뺀다."""
    return round(res["objective_musd"] - res.get("penalty_musd", 0.0), 1)


def summarize(res: dict) -> dict:
    """채팅과 보고서에서 쓸 숫자 요약 (LLM은 이 숫자만 인용한다)."""
    if "allocation" not in res:
        return {"status": res.get("status")}
    a = res["allocation"]
    by_src = a.groupby("source")["kt"].sum().round(0).to_dict()
    inv = res["inventory"]
    short_by_month = inv.groupby("month")["shortage_kt"].sum()
    return {
        "scenario": res["scenario"]["name"],
        "scenario_label": scenario_label(res["scenario"]),
        "status": res["status"],
        "time_limited": res.get("time_limited", False),
        "total_cost_musd": real_cost(res),
        "purchase_cost_musd": res["purchase_musd"],
        "total_shortage_kt": res["shortage_kt"],
        "shortage_months": {m: round(v, 1) for m, v in short_by_month.items() if v > 0.5},
        "volume_by_source_kt": by_src,
        "spot_cargoes": int(round(a.loc[a.source == "SPOT", "cargoes"].sum())),
        "new_us_cargoes": int(round(a.loc[a.source.str.startswith(supply_mod.NEW_US_PREFIX), "cargoes"].sum())),
        "procurement": procurement(res),
        "inputs_used": res.get("inputs_used"),
    }


SOURCE_NAMES = {"QATAR_LT": "카타르 장기", "OMAN_LT": "오만 장기", "AUSTRALIA_LT": "호주 장기", "MALAYSIA_LT": "말레이시아 장기",
                "OTHER_LT": "기타 장기", "US_LT": "미국 장기", "SPOT": "현물"}
REGIONS = {"QATAR_LT": "중동", "OMAN_LT": "중동", "AUSTRALIA_LT": "호주", "MALAYSIA_LT": "동남아", "OTHER_LT": "기타",
           "US_LT": "미국", "SPOT": "현물"}


def source_name(s: str) -> str:
    if s.startswith(supply_mod.NEW_US_PREFIX):
        return "미국 신규 " + s[len(supply_mod.NEW_US_PREFIX):].replace("_LNG", " LNG").replace("_LLC", "").replace("_", " ")
    return SOURCE_NAMES.get(s, s)


def region(s: str) -> str:
    return "미국" if s.startswith(supply_mod.NEW_US_PREFIX) else REGIONS.get(s, "기타")


def procurement(res: dict) -> dict:
    """어디서 얼마나 사고 비용이 얼마인지: 연도별 조달 구성, 중동 의존도, 신규 계약 후보별 권장 물량과 절감액."""
    a = res["allocation"].copy()
    if a.empty:
        return {}
    a["year"] = a["month"].str[:4]
    a["region"] = a["source"].map(region)
    src = res.get("source_table")
    hormuz = set(src.loc[src["via_hormuz"].astype(bool), "source"]) if src is not None and "via_hormuz" in src else {"QATAR_LT"}
    inv = res["inventory"].assign(year=lambda d: d["month"].str[:4])
    years = []
    for y, g in a.groupby("year"):
        kt = g["kt"].sum()
        by_reg = (g.groupby("region")["kt"].sum() / kt).round(3).to_dict() if kt else {}
        years.append({
            "year": y, "total_kt": round(kt), "cost_musd": round(g["cost_musd"].sum(), 1),
            "avg_usd_t": round(g["cost_musd"].sum() * 1000 / kt, 1) if kt else 0,
            "spot_kt": round(g.loc[g.source == "SPOT", "kt"].sum()),
            "new_us_kt": round(g.loc[g.source.str.startswith(supply_mod.NEW_US_PREFIX), "kt"].sum()),
            "middle_east_share": round(by_reg.get("중동", 0.0), 3),
            "hormuz_share": round(g.loc[g.source.isin(hormuz), "kt"].sum() / kt, 3) if kt else 0,
            "hhi": round(sum(v * v for v in by_reg.values()) * 10000),
            "stable_share": round(1 - g.loc[g.source == "SPOT", "kt"].sum() / kt, 3) if kt else 0,
            # 원칙(장기 비중)을 지키려면 그 해에 더 필요한 장기계약 물량 = 비중 x 총조달 - 장기 물량
            "stability_gap_kt": round(max(0.0, (res.get("min_stable_share") or 0) * kt
                                          - g.loc[g.source != "SPOT", "kt"].sum())) if kt else 0,
            "share_by_region": by_reg,
            "shortage_kt": round(inv.loc[inv.year == y, "shortage_kt"].sum()),
        })
    spot_unit = None
    if src is not None and (src.source == "SPOT").any():
        r = src[src.source == "SPOT"].iloc[0]
        spot_unit = float(r["price_usd_t"]) + 1.2 * float(r["voyage_days"])
    contracts = []
    for c in res.get("candidates") or []:
        frac = (res.get("contracts") or {}).get(c["source"], 0.0)
        g = a[a.source == c["source"]]
        kt = float(g["kt"].sum())
        cost = float(g["cost_musd"].sum())
        unit = cost * 1000 / kt if kt else None
        contracts.append({
            "project": c["project"], "name": source_name(c["source"]), "docket": c["docket"], "stage": c["stage"],
            "online_month": c["online_month"], "max_contract_mtpa": c["max_contract_mtpa"],
            "contract_mtpa": round(frac * c["max_contract_mtpa"], 2), "recommended": frac > 0.01 and kt > 0,
            "first_delivery": g["month"].min() if kt else None,
            "kt_by_year": {y: round(v) for y, v in g.groupby(g["month"].str[:4])["kt"].sum().items()},
            "total_kt": round(kt), "cost_musd": round(cost, 1), "avg_usd_t": round(unit, 1) if unit else None,
            "saving_vs_spot_musd": round((spot_unit - unit) * kt / 1000, 1) if unit and spot_unit else None,
            "p_by_year": c["p_by_year"],
        })
    by_src = a.groupby("source").agg(kt=("kt", "sum"), cost=("cost_musd", "sum")).reset_index()
    sources = [{"source": r.source, "name": source_name(r.source), "region": region(r.source), "kt": round(r.kt),
                "cost_musd": round(r.cost, 1), "avg_usd_t": round(r.cost * 1000 / r.kt, 1) if r.kt else None}
               for r in by_src.sort_values("kt", ascending=False).itertuples()]
    ms = res.get("min_stable_share") or 0
    gaps = {y["year"]: y["stability_gap_kt"] for y in years if y["stability_gap_kt"] > 0}
    rule = {"min_stable_share": ms, "text": f"연간 조달의 {ms:.0%} 이상은 장기계약(안정), 현물(단기)은 {1 - ms:.0%} 이하",
            "met": not gaps, "gap_years": gaps,
            "note": ("장기계약이 모자라 원칙을 못 지키는 해가 있다. gap_years의 물량만큼 그 해에 장기계약을 더 확보해야 한다. "
                     "그 공백을 메울 장기 공급처 후보(미국 신규 외)는 아직 데이터에 없어 추가 공급처 자료가 필요하다."
                     if gaps else "모든 해에 원칙을 지킨다."),
            "max_gap_mtpa": round(max(gaps.values()) / 1000, 2) if gaps else 0} if ms else None
    return {"period": f"{years[0]['year']}~{years[-1]['year']}" if years else "", "stability_rule": rule, "years": years,
            "new_contracts": contracts, "sources": sources}
