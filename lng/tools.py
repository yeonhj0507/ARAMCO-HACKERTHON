"""채팅 오케스트레이터가 부르는 도구 모음.

원칙
  - 숫자는 전부 여기 함수 결과에서만 나온다. LLM은 계산하지 않고 인용만 한다.
  - 명령(구매 요청, 배분 지시)은 초안까지만 만든다. 승인은 사람이 main.py approve로 한다.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from . import planner, report
from .studio_client import search_documents as _search

ORDERS_DIR = Path(__file__).resolve().parents[1] / "orders"
_RESULTS: dict[str, dict] = {}


def _get(name: str) -> dict:
    if name not in _RESULTS:
        if name != "baseline":
            raise KeyError(f"시나리오 '{name}'이 없습니다. run_scenario로 먼저 실행하세요.")
        _RESULTS["baseline"] = planner.run(planner.Scenario())
    return _RESULTS[name]


# 조사 -------------------------------------------------------------------------
def search_documents(query: str, top_k: int = 5) -> dict:
    return {"hits": _search(query, top_k=top_k)}


def forecast_demand() -> dict:
    nd = _get("baseline")["national_demand"]
    tbl = nd.pivot(index="month", columns="use", values="demand_kt").round(0).reset_index()
    return {"national_demand_kt": tbl.to_dict(orient="records")}


# 분석 -------------------------------------------------------------------------
def run_scenario(name: str, hormuz_blocked_months: int = 0, spot_price_multiplier: float = 1.0,
                 spot_volume_multiplier: float = 1.0, us_extra_delay_months: int = 0,
                 demand_multiplier: float = 1.0, allow_new_contracts: bool = True,
                 min_stable_share: float = 0.8) -> dict:
    sc = planner.Scenario(name=name, hormuz_blocked_months=hormuz_blocked_months,
                          spot_price_multiplier=spot_price_multiplier, spot_volume_multiplier=spot_volume_multiplier,
                          us_extra_delay_months=us_extra_delay_months, demand_multiplier=demand_multiplier,
                          allow_new_contracts=allow_new_contracts, min_stable_share=min_stable_share)
    res = planner.run(sc)
    _RESULTS[name] = res
    summ = planner.summarize(res)
    base = planner.summarize(_get("baseline"))
    if "total_cost_musd" in summ and "total_cost_musd" in base:
        summ["vs_baseline"] = {
            "cost_change_musd": round(summ["total_cost_musd"] - base["total_cost_musd"], 1),
            "spot_cargo_change": summ["spot_cargoes"] - base["spot_cargoes"],
            "shortage_change_kt": round(float(summ["total_shortage_kt"] - base["total_shortage_kt"]), 1),
        }
    summ["diversification_effect"] = diversification_effect(sc, res)
    return summ


def diversification_effect(sc, res: dict) -> dict | None:
    """같은 조건에서 신규 계약 없이(기존 장기계약 + 현물만) 돌린 결과와 비교한 다원화 효과."""
    from dataclasses import replace
    if "allocation" not in res or not (res.get("candidates")):
        return None
    alt = planner.run(replace(sc, name=f"{sc.name}_no_new", allow_new_contracts=False))
    if "allocation" not in alt:
        return None
    p1, p0 = planner.procurement(res), planner.procurement(alt)
    last1, last0 = p1["years"][-1], p0["years"][-1]
    return {
        "compare": "같은 조건에서 신규 계약 없이 기존 장기계약과 현물로만 조달한 경우와 비교",
        "cost_saving_musd": round(planner.real_cost(alt) - planner.real_cost(res), 1),
        "spot_kt_reduced": round(sum(y["spot_kt"] for y in p0["years"]) - sum(y["spot_kt"] for y in p1["years"])),
        "shortage_kt_reduced": round(alt["shortage_kt"] - res["shortage_kt"], 1),
        "last_year": last1["year"],
        "hhi_last_year": {"without": last0["hhi"], "with": last1["hhi"]},
        "spot_share_last_year": {"without": round(last0["spot_kt"] / last0["total_kt"], 3) if last0["total_kt"] else 0,
                                 "with": round(last1["spot_kt"] / last1["total_kt"], 3) if last1["total_kt"] else 0},
        "avg_usd_t_last_year": {"without": last0["avg_usd_t"], "with": last1["avg_usd_t"]},
    }


def get_allocation(scenario: str = "baseline", month: str | None = None, terminal: str | None = None) -> dict:
    a = _get(scenario)["allocation"]
    if month:
        a = a[a.month == month]
    if terminal:
        a = a[a.terminal == terminal.upper()]
    return {"rows": a.head(60).to_dict(orient="records"), "total_rows": int(len(a))}


# 명령 (초안만) -----------------------------------------------------------------
def create_order_draft(scenario: str, month: str) -> dict:
    """예전 방식 (단월 초안, Studio C 검사 없음). 에이전트 도구에서 뺐고 승인도 막힌다. 계획은 make_plan을 쓴다."""
    res = _get(scenario)
    a = res["allocation"]
    a = a[a.month == month]
    if a.empty:
        return {"error": f"{scenario} 시나리오의 {month} 배분이 없습니다."}
    order_id = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    purchases = a[a.source.isin(["SPOT", "US_UNCONTRACTED"])]
    order = {
        "order_id": order_id,
        "status": "PENDING_APPROVAL",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "scenario": scenario,
        "month": month,
        "allocation_instructions": a[["source", "terminal", "cargoes", "kt"]].to_dict(orient="records"),
        "purchase_requests": purchases[["source", "terminal", "cargoes", "kt", "cost_musd"]].to_dict(orient="records"),
    }
    ORDERS_DIR.mkdir(exist_ok=True)
    (ORDERS_DIR / f"{order_id}.json").write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")
    rpt = report.write_report(res, _get("baseline"), month, order_id, ORDERS_DIR)
    return {"order_id": order_id, "status": "PENDING_APPROVAL", "report_path": str(rpt),
            "purchase_cargoes": round(float(purchases["cargoes"].sum()), 1), "instruction_rows": len(order["allocation_instructions"]),
            "note": "승인은 담당자가 `python main.py approve <order_id>`로 직접 합니다."}


def approve_order(order_id: str, approver: str) -> dict:
    """사람용. LLM 도구 목록에는 넣지 않는다. Studio C가 '승인 요청'으로 본 초안만 승인한다."""
    p = ORDERS_DIR / f"{order_id}.json"
    order = json.loads(p.read_text(encoding="utf-8"))
    decision = (order.get("studio_check") or {}).get("decision")
    if decision != "승인 요청":
        raise ValueError("검증 시스템을 통과한 초안만 승인할 수 있습니다"
                         + (" (검증 없이 만든 예전 방식 초안)" if not order.get("studio_check") else f" (판정: {decision})"))
    order.update(status="APPROVED", approver=approver, approved_at=datetime.now().isoformat(timespec="seconds"))
    p.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")
    return order


# 문서, 검토, 계획 주기 (채팅 중심 앱에서 에이전트가 직접 부른다) ---------------------
ROOT = Path(__file__).resolve().parents[1]
DOC_DIRS = {"A": [ROOT / "submission", ROOT / "data" / "a_cases"],
            "C": [ROOT / "data" / "allocations", ROOT / "data" / "exec"]}
UPLOAD_DIR = ROOT / "data" / "uploads"
KIND_NAMES = {"A": "미국 DOE 반기 보고서 (프로젝트 가동 시점, 한국 계약, 미계약 물량)",
              "C": "배분 실행안 (승인 전 검사)"}


def _quiet(*_a, **_k):
    pass


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def _norm(x: str) -> str:
    import re
    return re.sub(r"[^0-9a-z가-힣]", "", x.lower())


def _all_docs() -> list[tuple[str | None, Path]]:
    out = [(k, p) for k, ds in DOC_DIRS.items() for d in ds if d.exists() for p in sorted(d.glob("*.pdf"))]
    if UPLOAD_DIR.exists():
        out += [(None, p) for p in sorted(UPLOAD_DIR.rglob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)]
    return out


def list_documents(query: str = "") -> dict:
    q = _norm(query)
    docs: dict[str, list[str]] = {}
    for k, p in _all_docs():
        if q and q not in _norm(p.stem):
            continue
        docs.setdefault(k or "uploaded", []).append(_rel(p))
    return {"kinds": KIND_NAMES, "documents": {k: v[:40] for k, v in docs.items()},
            "total": sum(len(v) for v in docs.values())}


def _resolve(path: str) -> Path:
    p = (ROOT / path).resolve()
    if p.exists() and p.suffix.lower() == ".pdf":
        return p
    q = _norm(Path(path).stem)
    hits = [p for _, p in _all_docs() if q and q in _norm(p.stem)]
    if not hits:
        raise FileNotFoundError(f"'{path}' 문서를 찾지 못했습니다. list_documents로 경로를 확인하세요.")
    return hits[0]


def _guess_kind(p: Path) -> str | None:
    for k, ds in DOC_DIRS.items():
        if any(d.resolve() in p.resolve().parents for d in ds):
            return k
    try:
        from pypdf import PdfReader
        text = " ".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages[:2])
    except Exception:  # noqa: BLE001
        return None
    if "실행안" in text:
        return "C"
    if any(w in text for w in ("Semi-Annual", "Semi-annual", "Docket", "FE Docket", "Department of Energy")):
        return "A"
    return None


def order_label(o: dict) -> str:
    """주문 초안의 시나리오를 사람이 읽는 말로. 예전 초안은 실행안 옆 .json의 조건이나 이름으로 추정한다."""
    if o.get("scenario_label"):
        return o["scenario_label"]
    if o.get("scenario_params"):
        return planner.scenario_label(o["scenario_params"])
    from . import workflows
    side = workflows.EXEC_DIR / f"{o.get('plan_id')}.json"
    if o.get("plan_id") and side.exists():
        meta = json.loads(side.read_text(encoding="utf-8"))
        if meta.get("scenario"):
            return planner.scenario_label(meta["scenario"])
    import re
    name = str(o.get("scenario") or "")
    d = {}
    if m := re.search(r"hormuz\D*(\d+)", name, re.I):
        d["hormuz_blocked_months"] = int(m.group(1))
    if m := re.search(r"demand\D*(\d+)p(\d+)", name, re.I):
        d["demand_multiplier"] = float(f"{m.group(1)}.{m.group(2)}")
    return planner.scenario_label(d) if d or name.lower() in ("", "baseline", "base") else name


def slim_cycle(out: dict | None) -> dict | None:
    """계획 주기 결과에서 화면과 에이전트에 필요한 것만."""
    if not out:
        return None
    o = out["order"]
    hist = [{**h, "pdf": _rel(Path(h["pdf"]))} for h in out["history"]]
    return {"status": out["status"], "history": hist,
            "order": {**{k: o.get(k) for k in ("order_id", "status", "plan_id", "scenario", "months", "studio_check",
                                               "inputs_used", "code_check", "disagree", "replan_of", "procurement")},
                      "scenario_label": order_label(o)},
            "purchase_requests": o.get("purchase_requests", [])}


def read_document(path: str, kind: str | None = None) -> dict:
    import re
    from . import cycle, workflows

    p = _resolve(path)
    kind = (kind or _guess_kind(p) or "").upper()[:1]
    if kind == "B":
        return {"error": "수급계획(수요)은 이미 전산화된 기준 자료(제16차 장기 천연가스 수급계획)를 쓰므로 문서로 읽지 않습니다."}
    if kind not in ("A", "C"):
        return {"error": f"{p.name}가 어떤 문서인지 모르겠습니다. 종류(A 미국 DOE 반기 보고서, C 배분 실행안)를 알려주세요."}
    key = re.sub(r"^\d{14}_", "", p.stem)
    base = {"kind": kind, "kind_name": KIND_NAMES[kind], "file": p.name, "path": _rel(p), "case_key": key}
    if kind == "A":
        out = workflows.ingest_a(p, key)
        return {**base, "fields": {k: out.get(k) for k in workflows.KEYS["A"]},
                "review_status": (out.get("review") or {}).get("status")}
    out = cycle.check_plan(p, log=_quiet)
    return {**base, "fields": out["studio"], "code_decision": (out.get("code_check") or {}).get("decision"),
            "disagree": out.get("disagree"), "replan": slim_cycle(out.get("replan"))}


def list_reviews() -> dict:
    from . import workflows
    keys = ["docket", "stage", "operating", "online_month", "kr_buyers", "kr_mtpa", "uncontracted_mtpa", "reason"]
    items = [{"case_key": r["case_key"], **{k: r.get(k) for k in keys}} for r in workflows.pending_reviews()]
    return {"count": len(items), "items": items}


def get_supply_outlook(project: str = "") -> dict:
    """Studio A 결과(사람 확인 끝난 것)로 본 프로젝트별 가동 시점과 2027년 말 가동 확률."""
    import pandas as pd
    from . import supply, workflows

    ps = workflows.load_params()
    if not ps:
        return {"source": "보고서 판독 결과 없음", "projects": []}
    prof = supply.profiles_from_params(ps)
    dec = pd.Timestamp("2027-12-01")
    q = _norm(project)
    rows = []
    for _, p in prof.iterrows():
        if q and q not in _norm(str(p["project"])):
            continue
        rows.append({"project": p["project"], "docket": p["docket"], "stage": p["stage"], "operating": bool(p["operating"]),
                     "online_month": p["latest_expected"], "kr_mtpa": p["kr_mtpa"],
                     "uncontracted_mtpa": p["uncontracted_mtpa"],
                     "p_2027_12": round(float(supply.prob_operational(p, dec)), 2)})
    rows.sort(key=lambda r: -r["p_2027_12"])
    by_stage: dict[str, int] = {}
    for r in rows:
        by_stage[str(r["stage"])] = by_stage.get(str(r["stage"]), 0) + 1
    summary = {
        "projects": len(rows), "by_stage": by_stage,
        "likely_online_by_2027_12": sum(r["p_2027_12"] >= 0.5 for r in rows),
        "with_korean_contract": sum((r["kr_mtpa"] or 0) > 0 for r in rows),
        "korean_contract_mtpa_total": round(sum(float(r["kr_mtpa"] or 0) for r in rows), 2),
        "uncontracted_mtpa_total": round(sum(float(r["uncontracted_mtpa"] or 0) for r in rows), 2),
    }
    return {"source": f"보고서 판독 {len(ps)}건 (사람 확인 대기는 제외)", "summary": summary, "projects": rows}


def get_overview() -> dict:
    """한국 수급 현황 한눈에: 수요 기준(제16차 수급계획 전산 자료)과 기지, 미국 공급(A) 요약, 확인과 승인 대기. 최적화는 돌리지 않는다."""
    from . import demand, workflows

    plan = workflows.load_plan()
    demand_part = None
    if plan:
        tg = demand.plan_annual_targets(plan, [2026, 2027, 2028])
        terms = [r.split(",") for r in plan.get("terminal_rows") or []]
        demand_part = {
            "plan": plan.get("plan_name"), "period": f"{plan.get('plan_start_year')}~{plan.get('plan_end_year')}",
            "annual_demand_kt": {y: {"city_gas": round(v["city_gas"]), "power": round(v["power"]),
                                     "total": round(v["city_gas"] + v["power"])} for y, v in tg.items()},
            "terminals": len(terms),
            "terminal_capacity_kt_total": round(sum(float(t[2]) for t in terms if len(t) > 2 and t[2].strip())),
        }
    sup = get_supply_outlook()
    reviews = list_reviews()["count"]
    orders = list_orders()["orders"]
    return {
        "demand_plan": demand_part or "수요 기준 자료 없음",
        "us_supply_A": {"source": sup["source"], **(sup.get("summary") or {}),
                        "top_projects": [{k: p[k] for k in ("project", "stage", "online_month", "kr_mtpa", "p_2027_12")}
                                         for p in sup["projects"][:5]]},
        "waiting_for_people": {"reviews": reviews, "orders_pending_approval": sum(o["status"] == "PENDING_APPROVAL" for o in orders),
                               "orders_needing_review": sum(o["status"] in ("NEEDS_REVIEW", "ESCALATED") for o in orders)},
        "latest_order": orders[0] if orders else None,
    }


def make_plan(hormuz_blocked_months: int = 0, spot_volume_multiplier: float = 1.0, us_extra_delay_months: int = 0,
              demand_multiplier: float = 1.0, spot_price_multiplier: float = 1.0, name: str = "") -> dict:
    from . import cycle
    sc = planner.Scenario(name=name or (f"hormuz{hormuz_blocked_months}" if hormuz_blocked_months else "baseline"),
                          hormuz_blocked_months=hormuz_blocked_months, spot_volume_multiplier=spot_volume_multiplier,
                          spot_price_multiplier=spot_price_multiplier, us_extra_delay_months=us_extra_delay_months,
                          demand_multiplier=demand_multiplier)
    return slim_cycle(cycle.run_cycle(sc, log=_quiet))


def list_orders(status: str = "") -> dict:
    out = []
    for f in ORDERS_DIR.glob("*.json") if ORDERS_DIR.exists() else []:
        o = json.loads(f.read_text(encoding="utf-8"))
        if "order_id" not in o:
            continue
        out.append({"order_id": o["order_id"], "status": o["status"], "created_at": o.get("created_at"),
                    "scenario": o.get("scenario"), "scenario_label": order_label(o), "plan_id": o.get("plan_id"),
                    "months": o.get("months") or [o.get("month")],
                    "decision": (o.get("studio_check") or {}).get("decision"),
                    "reason": (o.get("studio_check") or {}).get("reason"),
                    "purchase_cargoes": round(sum(r.get("cargoes", 0) for r in o.get("purchase_requests", [])), 1),
                    "replan_of": o.get("replan_of"), "studio_checked": bool(o.get("studio_check"))})
    out.sort(key=lambda o: o["created_at"] or "", reverse=True)
    if status:
        out = [o for o in out if o["status"] == status]
    return {"count": len(out), "orders": out}


def get_plan_detail(order_id: str = "", month: str = "") -> dict:
    """계획 초안의 월별, 기지별 배분: 어느 기지에 어느 공급원에서 몇 척, 월말 재고와 안전재고, 부족, 추가 구매(현물, 미국 무계약)."""
    from . import workflows

    orders = [o for o in list_orders()["orders"] if o["studio_checked"]]
    if not order_id:
        if not orders:
            return {"error": "검증 시스템을 거친 계획 초안이 없습니다. make_plan으로 먼저 계획을 세우세요."}
        order_id = orders[0]["order_id"]
    p = ORDERS_DIR / f"{order_id}.json"
    if not p.exists():
        return {"error": f"계획 초안 {order_id}가 없습니다."}
    o = json.loads(p.read_text(encoding="utf-8"))
    side = workflows.EXEC_DIR / f"{o.get('plan_id')}.json"
    tables = json.loads(side.read_text(encoding="utf-8")).get("tables", {}) if side.exists() else {}
    stock = tables.get("stock") or []
    summ = {s["month"]: s for s in tables.get("summary") or []}
    alloc = o.get("allocation_instructions") or []
    buys = o.get("purchase_requests") or []
    months = o.get("months") or sorted({a["month"] for a in alloc})
    if month:
        months = [m for m in months if m == month] or months
    out_months = []
    for m in months:
        terms = {}
        for st in (x for x in stock if x["month"] == m):
            terms[st["terminal"]] = {**{k: st[k] for k in ("terminal", "demand_kt", "inventory_kt", "capacity_kt", "safety_kt", "shortage_kt")},
                                     "inflow": []}
        for a in (x for x in alloc if x["month"] == m and x["kt"] > 0):
            t = terms.setdefault(a["terminal"], {"terminal": a["terminal"], "inflow": []})
            t["inflow"].append({"source": a["source"], "cargoes": round(a["cargoes"], 1), "kt": round(a["kt"])})
        for t in terms.values():
            t["inflow"].sort(key=lambda x: -x["kt"])
            t["inflow_kt"] = sum(x["kt"] for x in t["inflow"])
            t["inflow_cargoes"] = round(sum(x["cargoes"] for x in t["inflow"]), 1)
        by_src: dict[str, dict] = {}
        for a in (x for x in alloc if x["month"] == m):
            b = by_src.setdefault(a["source"], {"source": a["source"], "cargoes": 0.0, "kt": 0.0})
            b["cargoes"] += a["cargoes"]
            b["kt"] += a["kt"]
        mb = [{**{k: b[k] for k in ("source", "terminal")}, "cargoes": round(b["cargoes"], 1), "kt": round(b["kt"]),
               "cost_musd": round(b.get("cost_musd") or 0, 1)} for b in buys if b["month"] == m and b["kt"] > 0]
        s = summ.get(m, {})
        out_months.append({
            "month": m, "demand_kt": s.get("demand_kt"), "planned_kt": s.get("planned_kt"),
            "shortage_kt": s.get("shortage_kt", 0), "spot_cargoes": s.get("spot_cargoes"),
            "terminals": sorted(terms.values(), key=lambda t: -(t.get("demand_kt") or 0)),
            "by_source": sorted(({**b, "cargoes": round(b["cargoes"], 1), "kt": round(b["kt"])} for b in by_src.values()),
                                key=lambda b: -b["kt"]),
            "purchases": mb,
        })
    tot = {"cargoes": round(sum(b["cargoes"] for b in buys), 1), "kt": round(sum(b["kt"] for b in buys)),
           "cost_musd": round(sum(b.get("cost_musd") or 0 for b in buys), 1)}
    return {"order_id": order_id, "status": o.get("status"), "scenario": o.get("scenario"),
            "scenario_label": order_label(o), "plan_id": o.get("plan_id"),
            "months": out_months, "purchase_total": tot,
            "shortage_note": "부족은 현물까지 최대로 사도 못 채우는 양이다. 재계획으로 줄지 않으므로 검증 시스템은 기록만 하고 승인 요청을 낸다."
            if any(mm["shortage_kt"] for mm in out_months) else None}


REGISTRY = {
    "get_overview": get_overview,
    "list_documents": list_documents,
    "read_document": read_document,
    "list_reviews": list_reviews,
    "get_supply_outlook": get_supply_outlook,
    "forecast_demand": forecast_demand,
    "run_scenario": run_scenario,
    "make_plan": make_plan,
    "get_plan_detail": get_plan_detail,
    "list_orders": list_orders,
    "get_allocation": get_allocation,
    "search_documents": search_documents,
}

def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, **({"required": required} if required else {})}}}


_SCEN = {
    "hormuz_blocked_months": {"type": "integer", "description": "시작월부터 호르무즈 경유(카타르 등) 물량이 끊기는 개월 수. 기본 0"},
    "spot_volume_multiplier": {"type": "number", "description": "현물 확보 가능 물량 배수. 경쟁이 심하면 0.3~0.6. 기본 1"},
    "us_extra_delay_months": {"type": "integer", "description": "미국 프로젝트 추가 지연 개월 수. 기본 0"},
    "demand_multiplier": {"type": "number", "description": "수요 배수. 기본 1"},
    "spot_price_multiplier": {"type": "number", "description": "현물 가격 배수. 기본 1"},
}

TOOL_SPECS = [
    _fn("get_overview", "한국 수급 현황 요약: 제16차 수급계획 기준 연간 수요와 기지 용량, 미국 프로젝트(A) 단계별 수와 한국 계약, 미계약 물량 합계, "
        "사람 확인과 승인 대기 건수, 최근 계획. 전반적인 현황 질문에는 이것부터 쓴다. 빠르다."),
    _fn("list_documents", "읽을 수 있는 문서 목록. A 미국 DOE 반기 보고서, C 배분 실행안, uploaded 사용자가 올린 파일. "
        "사용자가 문서 이름만 말하면 이걸로 경로를 찾는다.",
        {"query": {"type": "string", "description": "파일 이름 일부 (예: Golden_Pass, Cameron). 비우면 전부"}}),
    _fn("read_document", "문서를 판독(Upstage Studio)해서 결과를 저장한다. A면 프로젝트 가동 시점, 한국 계약 물량을 최적화 입력으로 저장하고 "
        "애매하면 사람 확인으로 넘긴다. 미계약 물량은 신규 조달 후보가 된다. C면 실행안을 검사하고 재계획 필요면 다시 계획한다. 30초~2분 걸린다.",
        {"path": {"type": "string", "description": "list_documents의 경로, 또는 첨부 경로"},
         "kind": {"type": "string", "enum": ["A", "C"], "description": "모르면 비운다 (자동 판별)"}}, ["path"]),
    _fn("list_reviews", "보고서 판독에서 사람 확인으로 넘긴 프로젝트 목록과 이유. 사람이 카드에서 반영 또는 제외한다."),
    _fn("get_supply_outlook", "보고서 판독 결과로 본 미국 프로젝트별 단계, 가동 시점, 한국 계약 물량, 2027년 12월 가동 확률. "
        "summary에 전체 합계가 있고 projects는 가동 확률 높은 순이다. 특정 프로젝트는 project로 거른다.",
        {"project": {"type": "string", "description": "프로젝트 이름 일부. 비우면 전부"}}),
    _fn("forecast_demand", "전국 용도별(도시가스, 발전) 월별 수요 예측 (kt). 수급계획 B의 연간 목표에 맞춘 값."),
    _fn("run_scenario", "2027~2031 조달 최적화를 돌려 어디서 얼마나 사고 비용이 얼마인지 낸다. procurement에 연도별 조달 구성(현물, 미국 신규, 중동 의존도, HHI, 평균 단가), "
        "신규 계약 후보별 권장 계약 물량과 현물 대비 절감액, 장기 80% : 현물 20% 원칙을 지키는지(stability_rule, 해마다 더 필요한 장기계약 물량)가 있다. 기본 시나리오와 비교도 한다. 몇 초 걸린다. 실행안과 승인 요청은 만들지 않는다.",
        {"name": {"type": "string", "description": "시나리오 이름 (영문, 공백 없이)"}, **_SCEN,
         "allow_new_contracts": {"type": "boolean", "description": "false면 미국 신규 계약 없이 기존 계약과 현물로만. 기본 true"},
         "min_stable_share": {"type": "number", "description": "장기(안정) 계약 최소 비중. 기본 0.8 (장기 80%, 현물 20% 원칙). 0이면 원칙 없이"}}, ["name"]),
    _fn("make_plan", "실제 계획 주기: 2027~2031 조달 최적화, 앞 3개월 실행안 PDF 작성, 검증 시스템 검사, 문제가 있으면 최대 2번 재계획, 마지막에 승인 대기 초안을 만든다. "
        "1~3분 걸린다. 승인은 사람이 카드에서 한다.", {"name": {"type": "string"}, **_SCEN}),
    _fn("get_plan_detail", "계획 초안의 앞 3개월 조달 상세: 월별로 어느 공급원에서 몇 척(kt)을 사는지(장기계약, 현물), 현물 추가 구매 비용, 부족량. "
        "기지별 입고와 재고는 하역 가능 여부를 보는 참고 정보로 같이 있다. order_id를 비우면 가장 최근 계획.",
        {"order_id": {"type": "string"}, "month": {"type": "string", "description": "YYYY-MM. 비우면 3개월 전부"}}),
    _fn("list_orders", "계획 초안 목록 (승인 대기 PENDING_APPROVAL, 사람 확인 NEEDS_REVIEW, 넘김 ESCALATED, 승인 APPROVED).",
        {"status": {"type": "string", "description": "특정 상태만 볼 때"}}),
    _fn("get_allocation", "최근 시나리오의 공급원-기지-월별 카고 배분 결과.",
        {"scenario": {"type": "string"}, "month": {"type": "string", "description": "YYYY-MM"}, "terminal": {"type": "string"}}),
    _fn("search_documents", "판독한 보고서에서 근거 문장을 찾는다.",
        {"query": {"type": "string"}, "top_k": {"type": "integer"}}, ["query"]),
]
