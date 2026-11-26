"""Flutter 앱이 부르는 백엔드 (FastAPI).

    python main.py api            # http://localhost:8000, 문서: http://localhost:8000/docs

오래 걸리는 일(Studio 실행, 계획 주기)은 작업(job)으로 받아 바로 job_id를 돌려주고,
앱은 /jobs/{id}를 몇 초마다 조회한다. 작업 상태는 서버 메모리에만 있다 (데모용).
"""
from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from lng import cycle, planner, supply, tools, workflows

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = ROOT / "data" / "uploads"
ORDERS = ROOT / "orders"
SERVE_DIRS = [ROOT / "data", ROOT / "submission", ROOT / "orders"]

def _jsonable(o):
    """NaN, inf, numpy 값을 JSON에 맞게 바꾼다 (pandas에서 온 빈 칸이 NaN으로 오는 경우)."""
    import math
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            o = o.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


app = FastAPI(title="LNG 공급망 통합 에이전트 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pool = ThreadPoolExecutor(max_workers=3)
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


# ---------- 작업 ----------
def _submit(kind: str, title: str, fn, *args) -> dict:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": kind, "title": title, "status": "running", "log": [],
           "created_at": datetime.now().isoformat(timespec="seconds"), "result": None, "error": None}
    with _lock:
        _jobs[jid] = job

    def log(msg):
        if isinstance(msg, dict):  # 구조화된 이벤트 (채팅 도구 호출 등)
            job.setdefault("events", []).append(_jsonable(msg))
        else:
            job["log"].append(str(msg))

    def run():
        try:
            job["result"] = _jsonable(fn(*args, log=log))
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "error", str(e)
            job["log"].append(traceback.format_exc(limit=3))
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")

    _pool.submit(run)
    return job


@app.get("/jobs")
def list_jobs():
    return sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)[:30]


@app.get("/jobs/{jid}")
def get_job(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "작업이 없습니다")
    return _jobs[jid]


# ---------- 상태 ----------
@app.get("/health")
def health():
    return {"ok": True, "fake_studio": workflows.fake_mode(),
            "agents": {k: bool(os.getenv(v[0])) for k, v in workflows.AGENT_ENV.items()}}


def _orders() -> list[dict]:
    return tools.list_orders()["orders"]


@app.get("/status")
def status():
    allp = workflows.load_params(include_pending=True)
    by = {}
    for p in allp:
        s = (p.get("review") or {}).get("status", "auto")
        by[s] = by.get(s, 0) + 1
    plan = workflows.load_plan()
    orders = _orders()
    return {
        "a_params": {"total": len(allp), **by},
        "b_plan": {"name": plan.get("plan_name"), "period": f"{plan.get('plan_start_year')}~{plan.get('plan_end_year')}",
                   "terminals": len(plan.get("terminal_rows") or [])} if plan else None,
        "orders": {"pending": sum(o["status"] == "PENDING_APPROVAL" for o in orders),
                   "needs_review": sum(o["status"] in ("NEEDS_REVIEW", "ESCALATED") for o in orders),
                   "approved": sum(o["status"] == "APPROVED" for o in orders)},
        "last_order": orders[0] if orders else None,
        "fake_studio": workflows.fake_mode(),
    }


# ---------- 문서 처리 (워크플로우 A, B, C) ----------
def _run_doc(kind: str, path: Path, key: str, log=print) -> dict:
    log(f"문서 판독 중: {path.name}")
    if kind == "A":
        out = workflows.ingest_a(path, key)
    elif kind == "B":
        out = workflows.ingest_b(path, key)
    else:
        out = cycle.check_plan(path, log=log)
        return {"kind": "C", "fields": out["studio"], "code_check": out.get("code_check"),
                "disagree": out.get("disagree"), "replan": _slim_cycle(out.get("replan"))}
    log(f"완료: {out.get('config_status')}")
    return {"kind": kind, "fields": {k: out.get(k) for k in workflows.KEYS[kind]}, "review": out.get("review")}


@app.post("/documents/upload")
async def upload(kind: str = Form(...), file: UploadFile = File(...)):
    kind = kind.upper()
    if kind not in workflows.KEYS:
        raise HTTPException(400, "kind는 A, B, C 중 하나")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "upload.pdf").name
    dst = UPLOADS / kind / f"{datetime.now():%Y%m%d%H%M%S}_{name}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(await file.read())
    return _submit(f"doc_{kind}", f"{kind}: {name}", _run_doc, kind, dst, Path(name).stem)


class RunExisting(BaseModel):
    kind: str
    path: str


@app.post("/documents/run")
def run_existing(req: RunExisting):
    p = _safe_path(req.path)
    key = p.stem  # a_cases는 폴더 이름이 곧 프로젝트 키
    return _submit(f"doc_{req.kind.upper()}", f"{req.kind.upper()}: {p.name}", _run_doc, req.kind.upper(), p, key)


@app.get("/samples")
def samples():
    """데모에서 바로 고를 수 있는 문서."""
    def ls(d: Path, pattern="*.pdf"):
        return [str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted(d.glob(pattern))] if d.exists() else []
    return {"A": ls(ROOT / "submission") + ls(ROOT / "data" / "a_cases"),
            "B": ls(ROOT / "data" / "plans"),
            "C": ls(ROOT / "data" / "allocations") + ls(ROOT / "data" / "exec")}


def _safe_path(rel: str) -> Path:
    p = (ROOT / rel).resolve()
    if not any(str(p).startswith(str(d.resolve())) for d in SERVE_DIRS) or not p.exists():
        raise HTTPException(404, "파일이 없습니다")
    return p


@app.get("/files")
def get_file(path: str):
    return FileResponse(_safe_path(path))


# ---------- 공급 파라미터와 검토 ----------
@app.get("/params")
def params():
    rows = workflows.load_params(include_pending=True)
    keys = workflows.KEYS["A"]
    return _jsonable([{"case_key": r["case_key"], **{k: r.get(k) for k in keys}, "review": r.get("review")} for r in rows])


@app.get("/reviews")
def reviews():
    return [{"case_key": r["case_key"], **{k: r.get(k) for k in workflows.KEYS["A"]}} for r in workflows.pending_reviews()]


class ReviewAction(BaseModel):
    approver: str = "담당자"
    note: str = ""
    overrides: dict = {}


@app.post("/reviews/{key}/approve")
def approve(key: str, act: ReviewAction):
    try:
        return workflows.approve_param(key, act.approver, act.note, act.overrides)["review"]
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/reviews/{key}/reject")
def reject(key: str, act: ReviewAction):
    return workflows.reject_param(key, act.approver, act.note)["review"]


@app.get("/supply")
def supply_outlook():
    """A 결과로 본 프로젝트별 가동 시점과 2027년 가동 확률 (최적화는 돌리지 않음)."""
    import pandas as pd
    ps = workflows.load_params()
    if not ps:
        return {"source": "없음", "projects": []}
    prof = supply.profiles_from_params(ps)
    months = list(pd.date_range("2027-01-01", periods=12, freq="MS"))
    rows = []
    for _, p in prof.iterrows():
        probs = [supply.prob_operational(p, m) for m in months]
        rows.append({"project": p["project"], "docket": p["docket"], "stage": p["stage"], "operating": bool(p["operating"]),
                     "online_month": p["latest_expected"], "tau_months": p["tau_months"], "kr_mtpa": p["kr_mtpa"],
                     "uncontracted_mtpa": p["uncontracted_mtpa"], "p_2027_12": round(probs[-1], 2)})
    return _jsonable({"source": f"보고서 판독 {len(ps)}건", "projects": rows})


@app.get("/plan")
def plan():
    return workflows.load_plan() or {}


# ---------- 계획 주기 ----------
class CycleReq(BaseModel):
    name: str = ""
    hormuz: int = 0
    spot_volume: float = 1.0
    spot_price: float = 1.0
    us_delay: int = 0
    demand: float = 1.0


_slim_cycle = tools.slim_cycle


def _run_cycle(req: CycleReq, log=print) -> dict:
    sc = planner.Scenario(name=req.name or (f"hormuz{req.hormuz}" if req.hormuz else "baseline"),
                          hormuz_blocked_months=req.hormuz, spot_volume_multiplier=req.spot_volume,
                          spot_price_multiplier=req.spot_price, us_extra_delay_months=req.us_delay,
                          demand_multiplier=req.demand)
    res = cycle.run_cycle(sc, log=log)
    return _slim_cycle(res)


@app.post("/cycle")
def start_cycle(req: CycleReq):
    return _submit("cycle", f"계획 주기: {req.name or ('호르무즈 ' + str(req.hormuz) + '개월' if req.hormuz else '기본')}",
                   _run_cycle, req)


@app.post("/scenario")
def scenario(req: CycleReq):
    """최적화만 돌려 기본 시나리오와 비교 (실행안과 C 검증 없음, 몇 초)."""
    return _jsonable(tools.run_scenario(req.name or "custom", req.hormuz, req.spot_price, req.spot_volume, req.us_delay, req.demand))


# ---------- 승인 ----------
@app.get("/orders")
def orders():
    return _orders()


@app.get("/orders/{order_id}")
def order(order_id: str):
    p = ORDERS / f"{order_id}.json"
    if not p.exists():
        raise HTTPException(404, "주문 초안이 없습니다")
    o = json.loads(p.read_text(encoding="utf-8"))
    o["scenario_label"] = tools.order_label(o)
    return o


@app.get("/orders/{order_id}/detail")
def order_detail(order_id: str):
    r = tools.get_plan_detail(order_id)
    if "error" in r:
        raise HTTPException(404, r["error"])
    return _jsonable(r)


@app.post("/orders/{order_id}/approve")
def approve_order(order_id: str, act: ReviewAction):
    o = order(order_id)
    if o["status"] != "PENDING_APPROVAL":
        raise HTTPException(400, f"승인 대기 상태가 아닙니다 ({o['status']})")
    try:
        return tools.approve_order(order_id, act.approver)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- 채팅 ----------
_sessions: dict[str, object] = {}


class ChatReq(BaseModel):
    session: str = "default"
    message: str


@app.post("/chat")
def chat(req: ChatReq):
    used = []
    try:
        from lng.orchestrator import Orchestrator
        orch = _sessions.get(req.session)
        if orch is None:
            orch = _sessions[req.session] = Orchestrator()
        reply = orch.ask(req.message, on_tool=lambda n, a: used.append({"name": n, "args": a}))
        return {"reply": reply, "tools": used, "offline": False}
    except Exception as e:  # noqa: BLE001  키가 없거나 API 오류면 키워드 라우터로 도구만 부른다
        _sessions.pop(req.session, None)
        from lng.orchestrator import offline_route
        name, args = offline_route(req.message)
        result = tools.REGISTRY[name](**args)
        return {"reply": json.dumps(result, ensure_ascii=False, default=str)[:4000], "tools": [{"name": name, "args": args}],
                "offline": True, "note": f"Solar 호출 없이 키워드로 도구를 골랐습니다 ({type(e).__name__})"}


# ---------- 채팅 (기본 화면. 에이전트가 도구를 부르고, 결과는 카드로 보인다) ----------
# 도구 이름: (끝난 뒤 이름, 실행 중 문구)
TOOL_LABELS = {
    "get_overview": ("수급 현황 요약", "수급 현황을 모으고 있어요"),
    "list_documents": ("문서 목록 확인", "문서를 찾고 있어요"),
    "read_document": ("문서 판독", "AI가 문서를 판독하고 있어요"),
    "list_reviews": ("확인할 항목 조회", "사람 확인이 필요한 항목을 보고 있어요"),
    "get_supply_outlook": ("공급 전망 조회", "프로젝트별 가동 전망을 보고 있어요"),
    "forecast_demand": ("수요 예측 조회", "수요 예측을 보고 있어요"),
    "run_scenario": ("조달 최적화", "2027~2031 조달 계획을 최적화하고 있어요"),
    "make_plan": ("계획 수립과 검증", "계획을 세우고 검증 시스템으로 실행안을 검사하고 있어요"),
    "list_orders": ("계획 초안 조회", "계획 초안을 보고 있어요"),
    "get_plan_detail": ("조달 상세 조회", "월별 조달 상세를 보고 있어요"),
    "get_allocation": ("배분 결과 조회", "배분 결과를 보고 있어요"),
    "search_documents": ("근거 검색", "보고서에서 근거를 찾고 있어요"),
}


def _label(name: str) -> str:
    return TOOL_LABELS.get(name, (name, name))[0]


def _summarize(name: str, result) -> str:
    """도구 결과를 한 줄로."""
    if not isinstance(result, dict):
        return str(result)[:120]
    if "error" in result:
        return f"오류: {result['error']}"[:160]
    if name == "get_overview":
        us = result.get("us_supply_A") or {}
        return f"미국 프로젝트 {us.get('projects', 0)}건, 확인 대기 {(result.get('waiting_for_people') or {}).get('reviews')}건"
    if name == "list_documents":
        return f"문서 {result.get('total')}건"
    if name == "read_document":
        f = result.get("fields") or {}
        if result.get("kind") == "C":
            return f"{result.get('file')}: {f.get('decision')}"
        return f"{result.get('file')}: {f.get('config_status')}"
    if name == "list_reviews":
        return f"확인할 항목 {result.get('count')}건"
    if name == "get_supply_outlook":
        ps = result.get("projects") or []
        return f"프로젝트 {len(ps)}건, 2027년 말 가동 가능성 높음 {sum((p.get('p_2027_12') or 0) >= 0.5 for p in ps)}건"
    if name == "forecast_demand":
        return f"월별 수요 {len(result.get('national_demand_kt') or [])}개월"
    if name == "run_scenario":
        nc = [c for c in (result.get("procurement") or {}).get("new_contracts", []) if c.get("recommended")]
        eff = result.get("diversification_effect") or {}
        rule = (result.get("procurement") or {}).get("stability_rule") or {}
        rule_txt = "" if not rule else (", 장기 80% 원칙 충족" if rule.get("met") else
                                        f", 장기계약 부족 {', '.join(rule.get('gap_years', {}))}년")
        return (f"5년 총비용 {result.get('total_cost_musd')}M$, 신규 계약 {len(nc)}곳 "
                f"{sum(c['contract_mtpa'] for c in nc):.1f} MTPA, 신규 계약 효과 {eff.get('cost_saving_musd', 0)}M$ 절감{rule_txt}")
    if name == "make_plan":
        return f"{result.get('status')}, 실행안 {len(result.get('history') or [])}번 작성"
    if name == "list_orders":
        os_ = result.get("orders") or []
        return f"초안 {len(os_)}건, 승인 대기 {sum(o['status'] == 'PENDING_APPROVAL' for o in os_)}건"
    if name == "get_allocation":
        return f"배분 {result.get('total_rows')}행"
    if name == "get_plan_detail":
        ms = result.get("months") or []
        return f"{len(ms)}개월, 기지 {len(ms[0]['terminals']) if ms else 0}곳, 추가 구매 {(result.get('purchase_total') or {}).get('cargoes')}척"
    if name == "search_documents":
        return f"근거 {len(result.get('hits') or [])}건"
    return ", ".join(f"{k}" for k in list(result)[:5])


def _card(name: str, r) -> dict | None:
    """앱이 그릴 결과 카드. 표와 버튼은 카드가 맡고, 에이전트 답은 핵심만 말한다."""
    if not isinstance(r, dict) or "error" in r:
        return None
    if name == "read_document":
        return {"type": "doc", **r}
    if name == "get_overview":
        return {"type": "overview", **r}
    if name == "list_reviews":
        return {"type": "reviews", "items": r.get("items", [])}
    if name == "get_supply_outlook":
        ps = r.get("projects") or []
        return {"type": "supply", "source": r.get("source"), "total": len(ps),
                "likely": sum((p.get("p_2027_12") or 0) >= 0.5 for p in ps),
                "kr": sum((p.get("kr_mtpa") or 0) > 0 for p in ps), "items": ps[:8]}
    if name == "run_scenario":
        return {"type": "scenario", **{k: r.get(k) for k in ("scenario", "scenario_label", "total_cost_musd", "spot_cargoes",
                                                                "total_shortage_kt", "vs_baseline", "procurement",
                                                                "diversification_effect")}}
    if name == "make_plan":
        return {"type": "plan", **r}
    if name == "get_plan_detail":
        return {"type": "plan_detail", **r}
    if name == "list_orders":
        return {"type": "orders", "items": (r.get("orders") or [])[:8]}
    return None


def _compact(result) -> object:
    txt = json.dumps(_jsonable(result), default=str, ensure_ascii=False)
    return json.loads(txt) if len(txt) <= 6000 else {"_truncated": txt[:6000]}


def _run_chat(session: str, message: str, log=print) -> dict:
    ran = []

    def on_tool(name, args):
        log({"type": "tool_start", "name": name, "label": _label(name),
             "running": TOOL_LABELS.get(name, (name, name))[1], "args": args})

    def on_result(name, args, result, secs):
        ran.append(name)
        log({"type": "tool_end", "name": name, "label": _label(name), "args": args, "seconds": secs,
             "summary": _summarize(name, result), "card": _jsonable(_card(name, result)), "result": _compact(result)})

    try:
        from lng.orchestrator import Orchestrator
        orch = _sessions.get(session)
        if orch is None:
            orch = _sessions[session] = Orchestrator()
        log({"type": "thinking", "text": "무엇을 할지 고르고 있어요"})
        reply = orch.ask(message, on_tool=on_tool, on_result=on_result)
        return {"reply": reply, "offline": False}
    except Exception as e:  # noqa: BLE001
        _sessions.pop(session, None)
        if ran:  # 도구는 이미 돌았으니 다시 돌리지 않는다
            return {"reply": "도구 결과는 위 카드에 있어요. 답을 정리하다 Solar 호출이 실패했어요.", "offline": True,
                    "note": f"{type(e).__name__}: {e}"[:200]}
        from lng.orchestrator import offline_route
        import time as _t
        name, args = offline_route(message)
        on_tool(name, args)
        t0 = _t.time()
        try:
            result = tools.REGISTRY[name](**args)
        except Exception as e2:  # noqa: BLE001
            result = {"error": str(e2)}
        on_result(name, args, result, round(_t.time() - t0, 1))
        return {"reply": _summarize(name, result), "offline": True,
                "note": f"Solar 없이 키워드로 도구를 골랐어요 ({type(e).__name__})"}


@app.post("/chat/upload")
async def chat_upload(file: UploadFile = File(...)):
    """채팅 첨부. 저장만 하고, 읽는 건 에이전트가 read_document로 한다."""
    name = Path(file.filename or "upload.pdf").name
    dst = UPLOADS / "chat" / f"{datetime.now():%Y%m%d%H%M%S}_{name}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(await file.read())
    return {"path": str(dst.relative_to(ROOT)).replace("\\", "/"), "name": name}


@app.post("/chat/start")
def chat_start(req: ChatReq):
    return _submit("chat", req.message[:40], _run_chat, req.session, req.message)
