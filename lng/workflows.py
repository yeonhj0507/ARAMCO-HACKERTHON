"""Studio 워크플로우 A, B, C 실행과 결과 저장.

  A 공급 파라미터: 프로젝트별 DOE 보고서 2건 합본 -> data/studio_params/{key}.json
  B 수요와 기지:   장기 천연가스 수급계획 PDF   -> data/plan_params/{key}.json (+ latest.json)
  C 실행안 검증:   배분 실행안 PDF             -> data/exec/{plan_id}.studio.json

환경변수 (.env)
  UPSTAGE_STUDIO_AGENT_ID / UPSTAGE_STUDIO_CONFIG_ID   워크플로우 A
  UPSTAGE_STUDIO_AGENT_B  / UPSTAGE_STUDIO_CONFIG_B    워크플로우 B
  UPSTAGE_STUDIO_AGENT_C  / UPSTAGE_STUDIO_CONFIG_C    워크플로우 C
  LNG_STUDIO_FAKE=1    API 대신 정답지(또는 코드 검산)로 결과를 만든다. 오프라인 데모와 테스트용
  LNG_IGNORE_STUDIO=1  저장된 A, B 결과를 무시하고 샘플 데이터로만 계획 (테스트용)
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .studio_client import run_studio_job
from .studio_output import extract_output

ROOT = Path(__file__).resolve().parents[1]
PARAMS_DIR = ROOT / "data" / "studio_params"
PLAN_DIR = ROOT / "data" / "plan_params"
EXEC_DIR = ROOT / "data" / "exec"
RAW_DIR = ROOT / "data" / "studio_raw_v1"

AGENT_ENV = {
    "A": ("UPSTAGE_STUDIO_AGENT_ID", "UPSTAGE_STUDIO_CONFIG_ID"),
    "B": ("UPSTAGE_STUDIO_AGENT_B", "UPSTAGE_STUDIO_CONFIG_B"),
    "C": ("UPSTAGE_STUDIO_AGENT_C", "UPSTAGE_STUDIO_CONFIG_C"),
}
KEYS = {
    "A": ["docket", "stage", "operating", "online_month", "slip_months", "kr_buyers", "kr_mtpa",
          "uncontracted_mtpa", "config_status", "reason"],
    "B": ["plan_name", "plan_start_year", "plan_end_year", "base_demand_rows", "mgmt_demand_rows",
          "actual_demand_rows", "terminal_rows", "reserve_requirement", "config_status", "reason"],
    "C": ["plan_id", "period_start", "period_end", "total_planned_kt", "spot_cargoes", "shortage_rows",
          "over_contract_rows", "capacity_rows", "safety_rows", "mismatch_rows", "decision", "reason"],
}
ANSWER_FILES = [ROOT / "data" / "plans" / "b_answer.json", ROOT / "data" / "allocations" / "c_answer.json",
                *sorted((ROOT / "submission").glob("*_answer.json"))]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fake_mode() -> bool:
    return os.getenv("LNG_STUDIO_FAKE", "") not in ("", "0")


def _fake_output(kind: str, pdf: Path) -> dict:
    """오프라인: 정답지에 같은 파일이 있으면 그 정답, C는 실행안 옆 표 데이터로 코드 검산."""
    for f in ANSWER_FILES:
        if not f.exists():
            continue
        ans = json.loads(f.read_text(encoding="utf-8"))
        if set(KEYS[kind]) - set(ans.get("output_keys", [])):
            continue
        for c in ans["cases"]:
            files = c["file"] if isinstance(c["file"], list) else [c["file"]]
            if pdf.name in files:
                return dict(c["answer"])
    if kind == "C":
        from . import execdoc
        side = pdf.with_suffix(".json")
        if side.exists():
            t = json.loads(side.read_text(encoding="utf-8"))
            return execdoc.check_tables(t["tables"], t["plan_id"])
    raise FileNotFoundError(f"가짜 모드: {pdf.name}에 해당하는 정답이 없습니다.")


def run_workflow(kind: str, pdf: str | Path, key: str) -> dict:
    pdf = Path(pdf)
    if fake_mode():
        out = _fake_output(kind, pdf)
        out["_fake"] = True
        return out
    agent_env, cfg_env = AGENT_ENV[kind]
    agent = os.getenv(agent_env)
    if not agent:
        raise RuntimeError(f"{agent_env}가 .env에 없습니다. 워크플로우 {kind}의 에이전트 ID를 넣어주세요.")
    job = run_studio_job(str(pdf), agent_id=agent, key=f"{kind}__{key}", raw_dir=RAW_DIR, config_id=os.getenv(cfg_env))
    return extract_output(job, KEYS[kind])


# ---------- A: 공급 파라미터 ----------
def ingest_a(pdf: str | Path, key: str) -> dict:
    out = run_workflow("A", pdf, key)
    rec = {**out, "case_key": key, "source_file": Path(pdf).name, "processed_at": _now(),
           "review": {"status": "auto" if out.get("config_status") == "반영" else "pending"}}
    old = PARAMS_DIR / f"{key}.json"
    if old.exists():  # 다시 처리해도 이전 사람 검토 기록은 남긴다
        prev = json.loads(old.read_text(encoding="utf-8"))
        if (prev.get("review") or {}).get("status") in ("approved", "rejected"):
            rec["previous_review"] = {**prev["review"], **{k: prev.get(k) for k in KEYS["A"]}}
    PARAMS_DIR.mkdir(parents=True, exist_ok=True)
    (PARAMS_DIR / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def load_params(include_pending: bool = False) -> list[dict]:
    """최적화에 넣을 A 결과. 검토 필요는 사람이 승인한 것만 (include_pending이면 전부)."""
    if os.getenv("LNG_IGNORE_STUDIO") == "1" or not PARAMS_DIR.exists():
        return []
    out = []
    for f in sorted(PARAMS_DIR.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        status = (r.get("review") or {}).get("status")
        if include_pending or status in ("auto", "approved"):
            out.append(r)
    return out


def pending_reviews() -> list[dict]:
    return [r for r in load_params(include_pending=True) if (r.get("review") or {}).get("status") == "pending"]


def _coerce(key: str, value):
    """검토자가 고친 값을 출력 키 형식에 맞춘다."""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if key in ("operating",):
        return v.lower() in ("true", "1", "yes", "y")
    if key in ("slip_months",):
        return int(v or 0)
    if key in ("kr_mtpa", "uncontracted_mtpa"):
        return float(v or 0)
    if key in ("kr_buyers",):
        return [x.strip() for x in v.split(";") if x.strip()]
    return v


def approve_param(key: str, approver: str, note: str = "", overrides: dict | None = None) -> dict:
    """검토 필요 건을 반영한다. overrides가 있으면 검토자가 원문을 보고 고친 값으로 바꾸고 원래 값은 남긴다."""
    p = PARAMS_DIR / f"{key}.json"
    r = json.loads(p.read_text(encoding="utf-8"))
    changed = {}
    for k, v in (overrides or {}).items():
        if k not in KEYS["A"] or k in ("config_status", "reason"):
            raise ValueError(f"고칠 수 없는 키: {k}")
        changed[k] = {"studio": r.get(k), "reviewer": _coerce(k, v)}
        r[k] = changed[k]["reviewer"]
    r["review"] = {"status": "approved", "approver": approver, "note": note, "at": _now(), "overrides": changed}
    p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    return r


def reject_param(key: str, approver: str, note: str = "") -> dict:
    p = PARAMS_DIR / f"{key}.json"
    r = json.loads(p.read_text(encoding="utf-8"))
    r["review"] = {"status": "rejected", "approver": approver, "note": note, "at": _now()}
    p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    return r


# ---------- B: 수요와 기지 ----------
def ingest_b(pdf: str | Path, key: str | None = None) -> dict:
    key = key or Path(pdf).stem
    out = run_workflow("B", pdf, key)
    rec = {**out, "case_key": key, "source_file": Path(pdf).name, "processed_at": _now(),
           "review": {"status": "auto" if out.get("config_status") == "반영" else "pending"}}
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    (PLAN_DIR / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    if rec["review"]["status"] == "auto":
        (PLAN_DIR / "latest.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


REFERENCE_PLAN = Path(__file__).resolve().parents[1] / "data" / "reference" / "demand_plan.json"


def load_plan() -> dict | None:
    """수요와 기지 기준 자료. 제16차 장기 천연가스 수급계획 값을 전산 자료(data/reference/demand_plan.json)로 쓴다.
    (예전 워크플로우 B는 쓰지 않는다. 수요는 이미 전산화된 값이라 문서에서 읽을 이유가 없다.)"""
    if os.getenv("LNG_IGNORE_STUDIO") == "1":
        return None
    p = REFERENCE_PLAN if REFERENCE_PLAN.exists() else PLAN_DIR / "latest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------- C: 실행안 검증 ----------
def check_exec(pdf: str | Path, plan_id: str) -> dict:
    out = run_workflow("C", pdf, plan_id)
    EXEC_DIR.mkdir(parents=True, exist_ok=True)
    (EXEC_DIR / f"{plan_id}.studio.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
