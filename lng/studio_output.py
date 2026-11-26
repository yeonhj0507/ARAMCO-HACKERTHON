"""Studio 워크플로우 응답(job)에서 마지막 Instruct 노드의 출력 필드를 꺼낸다.

A, B, C 워크플로우 모두 Instruct가 마지막 노드이고 출력 필드가 정해져 있다.
응답 안 어디에 담기든(text, additional_values, 코드 블록 문자열) 출력 키를 가장 많이 가진 dict를 찾는다.
"""
from __future__ import annotations

import json
import re

from .studio_client import parse_job_output

META_KEYS = {"cache_hit", "citations", "job_execution_id", "occurrence_id", "previous_step_name", "step_run_id"}
CITE = re.compile(r"【†?\d+】")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def unwrap(v):
    if isinstance(v, dict) and "_value" in v:
        return unwrap(v["_value"])
    if isinstance(v, list):
        return [unwrap(x) for x in v]
    return v


def as_json(s: str):
    s = _FENCE.sub("", s.strip())
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def find_answer(obj, keys: list[str], depth: int = 0):
    """출력 키를 가장 많이 가진 dict와 그 개수."""
    if depth > 8:
        return None, 0
    best, score = None, 0
    if isinstance(obj, str) and "{" in obj:
        return find_answer(as_json(obj), keys, depth + 1)
    if isinstance(obj, dict):
        hit = sum(k in obj for k in keys)
        if hit > score:
            best, score = obj, hit
        for v in obj.values():
            b, sc = find_answer(v, keys, depth + 1)
            if sc > score:
                best, score = b, sc
    elif isinstance(obj, list):
        for v in obj:
            b, sc = find_answer(v, keys, depth + 1)
            if sc > score:
                best, score = b, sc
    return best, score


def _clean(v):
    if isinstance(v, str):
        return CITE.sub("", v).strip()
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def extract_output(job: dict, keys: list[str], min_hits: int = 3) -> dict:
    """job에서 출력 필드를 꺼내 정리한다. 키를 못 찾으면 ValueError.

    인용 표시는 지운다 (Studio 설정에서 껐어야 하지만 파이프라인은 방어적으로 처리).
    """
    fields, texts = parse_job_output(job)
    got, hit = find_answer({"fields": fields, "texts": texts, "output": job.get("output")}, keys)
    if not got or hit < min_hits:
        last = [o.get("model") for o in job.get("output") or [] if isinstance(o, dict)]
        raise ValueError(f"응답에서 출력 키를 찾지 못했습니다 (마지막 노드: {last}). Instruct가 마지막 노드인지 확인하세요.")
    out = {k: _clean(unwrap(v)) for k, v in got.items() if k not in META_KEYS}
    missing = [k for k in keys if k not in out]
    if missing:
        out["_missing_keys"] = missing
    return out
