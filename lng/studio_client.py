"""Upstage Studio 연동부.

흐름 (Upstage Document Agent API v2, OpenAI SDK 호환)
  1. Files API로 PDF 업로드 -> file_id
  2. Responses API로 Studio 에이전트(agt_...) 실행 -> job_id (background)
  3. 상태가 completed가 될 때까지 폴링
  4. output의 output_text에서 text와 additional_values(JSON 문자열)를 읽어 레코드로 변환

환경변수
  UPSTAGE_API_KEY            필수 (Studio 가입 시 기본 키가 자동 생성됨, up_로 시작)
  과금: Studio API로 돌린 워크플로우는 요금제의 Studio 사용량에서 차감된다 (Console 직접 호출은 종량제).
  UPSTAGE_STUDIO_AGENT_ID    필수, Studio 에이전트 화면의 Code 버튼에서 확인 (agt_...)
  UPSTAGE_STUDIO_CONFIG_ID   선택 (cfg_...). 비우면 기본 설정으로 실행되는데, 최신 버전이 아닐 수 있음
  UPSTAGE_STUDIO_BASE_URL    선택, 기본 https://api.upstage.ai/v2
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .schemas import DOC_TYPES

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "studio_output"
RAW_DIR = ROOT / "data" / "studio_raw"
POLL_SECONDS = 5
TIMEOUT_SECONDS = 600


def _studio_client():
    from openai import OpenAI

    key = os.getenv("UPSTAGE_API_KEY")
    if not key:
        raise RuntimeError("UPSTAGE_API_KEY가 없습니다. .env에 넣어주세요.")
    return OpenAI(api_key=key, base_url=os.getenv("UPSTAGE_STUDIO_BASE_URL") or "https://api.upstage.ai/v2")


def check_setup() -> dict:
    """키로 보이는 에이전트 목록과, .env의 에이전트 ID가 그 안에 있는지 확인."""
    client = _studio_client()
    agent_id = os.getenv("UPSTAGE_STUDIO_AGENT_ID") or ""
    out = {"agent_id_in_env": agent_id}
    try:
        res = client.get("/agents", cast_to=dict, options={"params": {"limit": 100}})
        items = res.get("data") or res.get("agents") or []
        out["visible_agents"] = [{"id": a.get("id"), "name": a.get("name")} for a in items if isinstance(a, dict)]
        out["agent_found"] = any(a.get("id") == agent_id for a in items if isinstance(a, dict))
        if not items:
            out["raw_keys"] = list(res.keys())
    except Exception as e:
        out["agents_error"] = str(e)
    return out


def parse_job_output(job: dict) -> tuple[dict, list[str]]:
    """완료된 job(dict)에서 추출 결과를 꺼낸다.

    output_text의 additional_values(JSON 문자열)와 text가 JSON이면 둘 다 합친다.
    Extract 결과가 어느 쪽에 담기는지는 에이전트 구성에 따라 다를 수 있어서 둘 다 본다.
    """
    merged: dict = {}
    texts: list[str] = []
    for item in job.get("output") or []:
        for c in item.get("content") or []:
            if c.get("type") not in (None, "output_text"):
                continue
            text = c.get("text") or ""
            if text:
                texts.append(text)
                try:
                    val = json.loads(text)
                    if isinstance(val, dict):
                        merged.update(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            av = c.get("additional_values")
            if av:
                try:
                    val = json.loads(av) if isinstance(av, str) else av
                    if isinstance(val, dict):
                        merged.update(val)
                except (json.JSONDecodeError, TypeError):
                    pass
    return merged, texts


def run_studio_job(file_path: str, agent_id: str | None = None, save: bool = True, key: str | None = None,
                   raw_dir: Path | None = None, config_id: str | None = None) -> dict:
    """PDF 한 건을 Studio 에이전트로 실행하고 완료된 job을 dict로 돌려준다 (가공 없음).

    save면 원본 응답을 raw_dir(기본 data/studio_raw)/{key}.json에 저장한다.
    """
    agent_id = (agent_id or os.getenv("UPSTAGE_STUDIO_AGENT_ID") or "").strip()
    if not re.fullmatch(r"agt_[A-Za-z0-9_-]+", agent_id):
        raise RuntimeError(f"UPSTAGE_STUDIO_AGENT_ID가 올바른 형식이 아닙니다 ('{agent_id}'). "
                           "Studio 에이전트 화면의 Code 버튼에서 agt_로 시작하는 실제 ID를 복사해 .env에 넣어주세요.")
    client = _studio_client()
    path = Path(file_path)
    key = key or path.stem  # 저장 파일 이름 (사업자 폴더가 달라도 겹치지 않게 ingest에서 지정)

    try:
        with open(path, "rb") as f:
            uploaded = client.files.create(file=f, purpose="user_data")
    except Exception as e:
        raise RuntimeError(f"[1단계 파일 업로드 실패] {e}") from e

    extra = {}
    config_id = config_id or os.getenv("UPSTAGE_STUDIO_CONFIG_ID")
    if config_id:
        extra["config_id"] = str(config_id)
    try:
        job = client.responses.create(
            model=agent_id,
            input=[{"role": "user", "content": [{"type": "input_file", "file_id": uploaded.id}]}],
            background=True,
            include=["last"],
            extra_body=extra or None,
        )
    except Exception as e:
        raise RuntimeError(f"[2단계 에이전트 실행 실패] {e}") from e

    start = time.time()
    status = getattr(job, "status", None)
    while status in ("queued", "in_progress", "cancelling", None):
        if time.time() - start > TIMEOUT_SECONDS:
            raise TimeoutError(f"{path.name}: {TIMEOUT_SECONDS}초 안에 끝나지 않았습니다 (job {job.id}).")
        time.sleep(POLL_SECONDS)
        job = client.responses.retrieve(job.id, include=["last"])
        status = job.status

    job_dict = job.model_dump()
    if save:
        out_dir = Path(raw_dir) if raw_dir else RAW_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{key}.json").write_text(json.dumps(job_dict, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if status != "completed":
        err = job_dict.get("error") or job_dict.get("failure_message")
        raise RuntimeError(f"{path.name}: Studio job {status} ({err})")
    return job_dict


def run_studio_agent(file_path: str, agent_id: str | None = None, save: bool = True, key: str | None = None) -> dict:
    """PDF 한 건을 Studio 에이전트로 처리해서 내부 스키마 레코드를 돌려준다 (예전 문서 1건 단위 스키마).

    원본 응답은 data/studio_raw/에 그대로 저장해 둔다 (필드 매핑 고칠 때 확인용).
    """
    path = Path(file_path)
    key = key or path.stem
    job_dict = run_studio_job(file_path, agent_id, save=save, key=key)
    fields, texts = parse_job_output(job_dict)
    rec = normalize_record(fields)
    rec.setdefault("source_file", path.name)
    rec.setdefault("source_folder", path.parent.name)
    if not fields:
        rec["_raw_text"] = texts[:3]  # JSON이 안 나왔으면 원문 일부라도 남김
    if save:
        DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
        (DEFAULT_DIR / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


META_KEYS = {"previous_step_name", "step_run_id", "occurrence_id", "job_execution_id", "cache_hit"}
_MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                            "august", "september", "october", "november", "december"])}
_DATE_KR = re.compile(r"(20\d{2})년\s*(\d{1,2})월(?:\s*(\d{1,2})일)?")
_DATE_EN = re.compile(r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(?:(\d{1,2}),?\s+)?(20\d{2})", re.I)
_DATE_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_FIRST_LNG_DONE = re.compile(r"(첫\s*LNG\s*(생산|출하|카고)?[을를]?\s*(달성|생산했|생산하였|시작했)|first\s+lng\s+(was\s+)?(achieved|produced)|achieved\s+first\s+lng|"
                             r"상업\s*운전[을를]?\s*(개시|시작)|commercial\s+operations?\s+(commenced|began|started))", re.I)
_TARGET_YEAR = re.compile(r"(상업\s*운전|가동|첫\s*LNG|commercial operation|first lng|cod|in[- ]service)[^.]{0,40}?(20\d{2})[^.]{0,15}?(목표|예상|예정|expected|anticipated|target)"
                          r"|(expected|anticipated|targeted|target)[^.]{0,40}?(20\d{2})", re.I)
STAGES = [  # 우선순위 순서
    ("operating", re.compile(r"첫\s*LNG\s*(생산|출하)?[을를]?\s*달성|first\s+lng\s+(was\s+)?achieved|achieved\s+first\s+lng|상업\s*운전[을를]?\s*(개시|시작)|상업\s*운전\s*중|commercial\s+operations?\s+(commenced|began)|in\s+commercial\s+operation", re.I)),
    ("commissioning", re.compile(r"시운전|커미셔닝|commissioning|start-?up", re.I)),
    ("construction", re.compile(r"\bFID\b|최종\s*투자\s*결정|착공|건설\s*금융|under\s+construction|건설[이은는]?\s*(일정대로\s*)?(계속\s*)?진행|공사[가는]?\s*(계속\s*)?진행|construction\s+(is\s+)?(ongoing|continues|progress)", re.I)),
    ("pre_fid", re.compile(r"상업\s*협의|판매\s*협의|협의[를를]?\s*진행\s*중|commercial discussions|marketing|permitting|인허가|건설을\s*향해", re.I)),
    ("construction", re.compile(r"건설|공사|construction|EPC", re.I)),  # 약한 신호: 위에서 못 정했을 때만
]


# 기존 설비가 이미 가동 중이라는 표현 (확장 공사 얘기와 같이 나와도 본 설비는 가동 중)
_BASE_OPERATING = re.compile(r"상업\s*운전에\s*들어|상업\s*운전을\s*(개시|시작)|생산하며|수출\s*(중|하고)|운전을\s*재개|"
                             r"LNG\s*생산[^.]{0,20}(시작|개시)|화물\s*(수출|선적)[^.]{0,10}(시작|개시)|기존\s*(액화)?\s*설비[^.]{0,20}(가동|운전)|"
                             r"in\s+(commercial\s+)?operation|operational\s+since|continues?\s+to\s+export|commenced\s+(commercial\s+)?operations?", re.I)


def _dates_in(text: str) -> list[tuple[int, str]]:
    """문장 안의 날짜를 (위치, YYYY-MM-DD)로. 일이 없으면 그 달 1일."""
    out = []
    for m in _DATE_KR.finditer(text):
        out.append((m.start(), f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3) or 1):02d}"))
    for m in _DATE_EN.finditer(text):
        out.append((m.start(), f"{m.group(3)}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2) or 1):02d}"))
    for m in _DATE_ISO.finditer(text):
        out.append((m.start(), m.group(0)))
    return sorted(out)


def derive_status(note: str) -> dict:
    """진행 요약 문장에서 단계(stage), 실제 첫 LNG 날짜, 목표 연도를 뽑는다."""
    note = note or ""
    out: dict = {}
    for name, pat in STAGES:
        if pat.search(note):
            out["stage"] = name
            break
    m = _FIRST_LNG_DONE.search(note)
    if m:
        dates = [d for pos, d in _dates_in(note) if pos <= m.end() + 5]
        if dates:
            out["first_lng_date"] = dates[-1]  # 달성 문구 바로 앞(가장 가까운) 날짜
        out["stage"] = "operating"
    if _BASE_OPERATING.search(note):
        out["base_operating"] = True
    t = _TARGET_YEAR.search(note)
    if t and "first_lng_date" not in out:
        out["target_year"] = int(t.group(2) or t.group(5))
    return out


def _unwrap(v, path: str, conf: dict, evidence: list):
    """Studio Extract 값 {"_value", "confidence", "page", ...}를 값만 남기고, 신뢰도와 페이지는 따로 모은다."""
    if isinstance(v, dict) and "_value" in v:
        val = v["_value"]
        conf[path] = {"confidence": v.get("confidence"), "score": v.get("confidence_score"), "page": v.get("page")}
        if val not in ("", None) and (v.get("page") or -1) > 0:
            evidence.append({"page": v.get("page"), "field": path, "text": str(val)[:300]})
        return None if val == "" else val
    if isinstance(v, dict):
        return {k: _unwrap(x, f"{path}.{k}" if path else k, conf, evidence) for k, x in v.items()}
    if isinstance(v, list):
        return [_unwrap(x, f"{path}[{i}]", conf, evidence) for i, x in enumerate(v)]
    return v


def normalize_record(raw: dict) -> dict:
    """Studio 출력 하나를 내부 스키마로 맞춘다.

    - 값이 {"_value": ...} 형태면 값만 꺼내고, 신뢰도는 _confidence, 근거 페이지는 evidence에 넣는다.
    - Classify 없이 Extract만 쓰는 에이전트라 doc_type이 없으면 반기 보고서로 본다.
    - 진행 요약 문장에서 단계(pre_fid/construction/commissioning/operating)와 실제 첫 LNG 날짜를 뽑는다.
    - 가동 예정일이 비어 있으면 '상업운전은 2030년 목표'처럼 목표/예상 연도가 적힌 문장에서만 채운다 (추정 표시).
    """
    src = dict(raw.get("fields", raw))
    conf: dict = {}
    evidence: list = list(src.pop("evidence", []) or [])
    rec = {k: _unwrap(v, k, conf, evidence) for k, v in src.items() if k not in META_KEYS}
    if conf:
        rec["_confidence"] = conf
    rec["evidence"] = evidence

    if rec.get("doc_type") not in DOC_TYPES or (rec.get("doc_type") == "other" and rec.get("project") and rec.get("report_date")):
        rec["doc_type"] = "semi_annual_report" if rec.get("project") else "other"
    for key in ("authorized_mtpa", "uncontracted_mtpa"):
        if isinstance(rec.get(key), str):
            m = re.search(r"[\d.]+", rec[key])
            rec[key] = float(m.group()) if m else None

    contracts = []
    for c in rec.get("long_term_contracts") or []:
        if not isinstance(c, dict) or not c.get("buyer"):
            continue
        c = dict(c)
        for k in ("start_year", "term_years"):
            c[k] = c.get(k) or None  # 0은 '문서에 없음'으로 본다
        c["mtpa"] = float(c["mtpa"]) if c.get("mtpa") not in (None, "") else 0.0
        contracts.append(c)
    rec["long_term_contracts"] = contracts

    status = derive_status(rec.get("progress_note") or "")
    if status.get("stage"):
        rec["stage"] = rec.get("stage") or status["stage"]
    if status.get("first_lng_date"):
        rec["first_lng_date"] = rec.get("first_lng_date") or status["first_lng_date"]
    if status.get("base_operating"):
        rec["base_operating"] = True
    if rec.get("expected_operational_date_inferred"):  # 예전 규칙으로 추정한 값은 다시 판단
        rec.pop("expected_operational_date", None)
        rec.pop("expected_operational_date_inferred", None)
    if not rec.get("expected_operational_date") and status.get("target_year"):
        rec["expected_operational_date"] = f"{status['target_year']}-12-01"
        rec["expected_operational_date_inferred"] = True
    return rec


def renormalize_all() -> int:
    """data/studio_raw의 원본 응답을 다시 읽어 data/studio_output을 새로 만든다 (매핑을 고친 뒤 재처리 없이 반영)."""
    n = 0
    for p in sorted(RAW_DIR.glob("*.json")):
        job = json.loads(p.read_text(encoding="utf-8"))
        if job.get("status") != "completed":
            continue
        fields, _ = parse_job_output(job)
        if not fields:
            continue
        rec = normalize_record(fields)
        old = DEFAULT_DIR / p.name
        if old.exists():  # 원래 파일명 정보 유지
            rec.setdefault("source_file", json.loads(old.read_text(encoding="utf-8")).get("source_file"))
        rec.setdefault("source_file", p.stem + ".pdf")
        (DEFAULT_DIR / p.name).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1
    return n


def load_extractions(directory: str | Path = DEFAULT_DIR) -> list[dict]:
    """저장된 Studio 결과를 전부 읽는다."""
    out = []
    for p in sorted(Path(directory).glob("*.json")):
        out.append(normalize_record(json.loads(p.read_text(encoding="utf-8"))))
    return out


def search_documents(query: str, records: list[dict] | None = None, top_k: int = 5) -> list[dict]:
    """근거 문장 검색. 단어 겹침 점수로 간단히 찾는다 (나중에 임베딩 검색으로 교체 가능)."""
    records = records if records is not None else load_extractions()
    terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
    hits = []
    for rec in records:
        chunks = rec.get("evidence") or [{"page": None, "text": rec.get("progress_note", "")}]
        haystack_meta = f"{rec.get('project','')} {rec.get('docket','')}".lower()
        for ch in chunks:
            text = (ch.get("text") or "").lower()
            score = sum(text.count(t) + haystack_meta.count(t) for t in terms)
            if score > 0:
                hits.append({
                    "score": score,
                    "project": rec.get("project"),
                    "docket": rec.get("docket"),
                    "report_date": rec.get("report_date"),
                    "page": ch.get("page"),
                    "text": ch.get("text"),
                    "source_file": rec.get("source_file"),
                })
    hits.sort(key=lambda h: (-h["score"], h["report_date"] or ""))
    return hits[:top_k]
