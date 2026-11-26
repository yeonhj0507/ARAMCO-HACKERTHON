"""한 번의 계획 주기: 최적화 -> 실행안 PDF -> Studio C 검증 -> 승인 요청 또는 재계획.

  승인 요청   주문 초안(orders/{order_id}.json)을 PENDING_APPROVAL로 만든다. 승인은 사람이 main.py approve로.
  재계획 필요 최적화를 처음부터 다시 돌려 새 실행안을 만들고 다시 검증한다 (최대 max_replans번).
              그래도 안 되면 ESCALATED로 담당자에게 넘긴다.
  Studio 판정과 코드 검산이 다르면 NEEDS_REVIEW로 둘 다 남기고 담당자에게 넘긴다.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

from . import execdoc, planner, workflows

ROOT = Path(__file__).resolve().parents[1]
ORDERS_DIR = ROOT / "orders"


def _scenario_text(sc: planner.Scenario) -> str:
    parts = []
    if sc.hormuz_blocked_months:
        parts.append(f"호르무즈 해협 {sc.hormuz_blocked_months}개월 차단")
    if sc.spot_volume_multiplier != 1.0:
        parts.append(f"현물 확보량 {sc.spot_volume_multiplier:.0%}")
    if sc.spot_price_multiplier != 1.0:
        parts.append(f"현물 가격 {sc.spot_price_multiplier:.0%}")
    if sc.us_extra_delay_months:
        parts.append(f"미국 프로젝트 추가 지연 {sc.us_extra_delay_months}개월")
    if sc.demand_multiplier != 1.0:
        parts.append(f"수요 {sc.demand_multiplier:.0%}")
    return ", ".join(parts) or "기본 계획"


def scenario_from_dict(d: dict | None) -> planner.Scenario:
    allowed = {f.name for f in fields(planner.Scenario)}
    return planner.Scenario(**{k: v for k, v in (d or {}).items() if k in allowed})


def make_exec_doc(sc: planner.Scenario, attempt: int = 1) -> tuple[dict, Path, dict, dict]:
    res = planner.run(sc)
    if "allocation" not in res:
        raise RuntimeError(f"최적화가 풀리지 않았습니다: {res.get('status')}")
    tables = execdoc.build_tables(res)
    plan_id = f"ALLOC-{tables['months'][0].replace('-', '')}-{sc.name.upper()}-{datetime.now():%m%d%H%M}-{attempt}"
    pdf = execdoc.write_pdf(tables, workflows.EXEC_DIR / f"{plan_id}.pdf", plan_id, _scenario_text(sc), asdict(sc))
    return res, pdf, tables, {"plan_id": plan_id}


def _write_order(res: dict, tables: dict, plan_id: str, studio: dict, status: str, extra: dict) -> dict:
    order_id = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    a = res["allocation"]
    a = a[a.month.isin(tables["months"])]
    purchases = a[a.source.isin(["SPOT", "US_UNCONTRACTED"])]
    order = {
        "order_id": order_id, "status": status, "created_at": datetime.now().isoformat(timespec="seconds"),
        "plan_id": plan_id, "scenario": res["scenario"]["name"], "scenario_label": planner.scenario_label(res["scenario"]),
        "scenario_params": {k: v for k, v in res["scenario"].items() if k not in ("notes",)}, "months": tables["months"],
        "studio_check": {k: studio.get(k) for k in workflows.KEYS["C"]},
        "allocation_instructions": a[["month", "source", "terminal", "cargoes", "kt"]].to_dict(orient="records"),
        "purchase_requests": purchases[["month", "source", "terminal", "cargoes", "kt", "cost_musd"]].to_dict(orient="records"),
        "inputs_used": res.get("inputs_used"), "procurement": planner.procurement(res), **extra,
    }
    ORDERS_DIR.mkdir(exist_ok=True)
    (ORDERS_DIR / f"{order_id}.json").write_text(json.dumps(order, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return order


def run_cycle(sc: planner.Scenario, max_replans: int = 2, log=print, origin: dict | None = None) -> dict:
    """origin: 바깥 실행안을 검증하다 재계획하는 경우, 원래 실행안과 걸린 항목 (주문 초안에 남긴다)."""
    history = []
    base_extra = {"replan_of": origin} if origin else {}
    for attempt in range(1, max_replans + 2):
        res, pdf, tables, meta = make_exec_doc(sc, attempt)
        plan_id = meta["plan_id"]
        code = execdoc.check_tables(tables, plan_id)
        studio = workflows.check_exec(pdf, plan_id)
        diff = execdoc.compare_checks(studio, code)
        step = {"attempt": attempt, "plan_id": plan_id, "pdf": str(pdf), "studio_decision": studio.get("decision"),
                "code_decision": code["decision"], "disagree": diff}
        history.append(step)
        log(f"[{attempt}] {plan_id}: 검증 시스템 {studio.get('decision')} / 교차 검산 {code['decision']}"
            + (f" / 다른 항목 {diff}" if diff else ""))
        if diff:
            order = _write_order(res, tables, plan_id, studio, "NEEDS_REVIEW",
                                 {**base_extra, "code_check": code, "disagree": diff, "cycle": history})
            return {"status": "NEEDS_REVIEW", "order": order, "history": history}
        if studio.get("decision") == "승인 요청":
            order = _write_order(res, tables, plan_id, studio, "PENDING_APPROVAL", {**base_extra, "cycle": history})
            return {"status": "PENDING_APPROVAL", "order": order, "history": history}
        log("  재계획 필요 -> 최적화를 다시 돌립니다.")
    order = _write_order(res, tables, plan_id, studio, "ESCALATED", {**base_extra, "cycle": history})
    return {"status": "ESCALATED", "order": order, "history": history}


def check_plan(pdf: str | Path, log=print) -> dict:
    """사람이 고친 실행안처럼 바깥에서 들어온 실행안을 검증한다. 재계획 필요면 같은 시나리오로 다시 계획한다."""
    pdf = Path(pdf)
    side = pdf.with_suffix(".json")
    meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    plan_id = meta.get("plan_id") or pdf.stem
    studio = workflows.check_exec(pdf, plan_id)
    out = {"plan_id": plan_id, "studio": studio}
    if meta.get("tables"):
        code = execdoc.check_tables(meta["tables"], plan_id)
        out["code_check"] = code
        out["disagree"] = execdoc.compare_checks(studio, code)
    log(f"{plan_id}: 검증 시스템 {studio.get('decision')}" + (f" / 교차 검산 {out['code_check']['decision']}" if "code_check" in out else ""))
    if studio.get("decision") == "재계획 필요":
        if meta.get("scenario") is not None:
            log("  걸린 항목: " + ", ".join(k for k in execdoc.DECISION_KEYS[:-1] if studio.get(k)))
            log("  같은 시나리오 조건으로, 지금 가진 최신 입력(보고서 판독 결과, 수요 기준 자료)을 써서 최적화를 다시 돌립니다.")
            sc = scenario_from_dict({**meta["scenario"], "use_studio": True})
            violations = {k: studio.get(k) for k in execdoc.DECISION_KEYS[:-1] if studio.get(k)}
            out["replan"] = run_cycle(sc, log=log, origin={"plan_id": plan_id, "file": pdf.name, "violations": violations})
        else:
            out["replan"] = None
            log("  시나리오 정보(.json)가 없어 재계획은 하지 않았습니다. run-cycle로 다시 계획하세요.")
    return out
