"""Studio 워크플로우 v1을 데이터셋 케이스로 돌려서 정답지와 키별로 비교한다.

    python scripts/eval_studio.py                 7건 전부 Studio로 실행 후 비교
    python scripts/eval_studio.py --cases A,D     일부만
    python scripts/eval_studio.py --reuse         API 호출 없이 저장된 응답(submission/runs)으로 다시 비교

원본 응답은 submission/runs/{case_id}.json, 비교 결과는 submission/runs/eval_report.json에 남는다.
reason은 자유 문장이라 점수에서 빼고 내용만 보여준다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from lng.studio_client import parse_job_output, run_studio_job  # noqa: E402

SUB = ROOT / "submission"
RUNS = SUB / "runs"
SKIP_SCORE = {"reason"}
_CITE = re.compile(r"【†?\d+】")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def _unwrap(v):
    if isinstance(v, dict) and "_value" in v:
        return _unwrap(v["_value"])
    if isinstance(v, list):
        return [_unwrap(x) for x in v]
    return v


def _as_json(s: str):
    s = _FENCE.sub("", s.strip())
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", s, re.S)  # 앞뒤에 설명 문장이 붙은 경우
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def find_answer(obj, keys: list[str], depth: int = 0):
    """응답 어딘가에 들어 있는, 출력 키를 가장 많이 가진 dict를 찾는다."""
    if depth > 8:
        return None, 0
    best, score = None, 0
    if isinstance(obj, str) and "{" in obj:
        return find_answer(_as_json(obj), keys, depth + 1)
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


def compare(expected, got):
    """(일치 여부, 비고). 값은 맞는데 타입이 다르면 '형식'으로 표시한다 (채점에서 틀릴 수 있음)."""
    if got is None:
        return False, "출력 없음"
    if expected == got and type(expected) is type(got):
        return True, ""
    if isinstance(got, str) and _CITE.search(got):
        stripped = _CITE.sub("", got).strip()
        ok, _ = compare(expected, stripped if not isinstance(expected, (bool, int, float, list)) else _as_json(stripped) if stripped[:1] in "[{" else stripped)
        return False, "인용 표시" + (", 지우면 일치" if ok or str(expected) == stripped else "")
    if isinstance(got, list) and any(isinstance(x, str) and _CITE.search(x) for x in got):
        return False, "인용 표시"
    if isinstance(expected, bool):
        if isinstance(got, str) and got.strip().lower() == str(expected).lower():
            return False, "형식(문자열)"
        return False, ""
    if isinstance(expected, (int, float)) and not isinstance(got, bool):
        try:
            if abs(float(got) - float(expected)) < 1e-6:
                return (True, "") if isinstance(got, (int, float)) else (False, "형식(문자열)")
        except (TypeError, ValueError):
            pass
        return False, ""
    if isinstance(expected, list):
        if isinstance(got, str):
            parsed = _as_json(got)
            if isinstance(parsed, list) and sorted(map(str, parsed)) == sorted(map(str, expected)):
                return False, "형식(문자열)"
            return False, ""
        if isinstance(got, list) and sorted(str(x).strip() for x in got) == sorted(str(x).strip() for x in expected):
            return True, ""
        return False, ""
    if isinstance(expected, str) and isinstance(got, str) and expected.strip() == got.strip():
        return True, ""
    return False, ""


def strict_check(job: dict, case: dict, seconds: float | None) -> list[str]:
    """채점과 같은 조건으로 본다: 판정 노드(마지막 노드) 1개의 출력만, 키 이름 그대로, 값은 가공하지 않는다.
    위의 키별 비교는 인용 표시나 _value 감싸기를 풀어서 보지만, 운영진 채점은 그렇게 해 주지 않는다."""
    issues = []
    if job.get("status") not in (None, "completed"):
        issues.append(f"실행 상태 {job.get('status')} (오류는 0점)")
    out = job.get("output") or []
    last = out[-1] if out else {}
    obj = None
    for c in last.get("content") or []:
        if c.get("type") not in (None, "output_text"):
            continue
        try:
            v = json.loads(c.get("text") or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(v, dict):
            obj = v
            break
    if obj is None:
        return issues + ["판정 노드 출력이 JSON 객체가 아님 (정답 키를 이 노드 하나에서 낼 것)"]
    for k, exp in case["answer"].items():
        if k not in obj:
            near = [g for g in obj if g.replace("_", "").lower() == k.replace("_", "").lower()]
            issues.append(f"키 없음 {k}" + (f" (이름이 다른 {near[0]}가 있음, 0점)" if near else ""))
            continue
        v = obj[k]
        if isinstance(v, dict) and "_value" in v:
            issues.append(f"{k} 값이 _value로 감싸져 있음")
            continue
        num = isinstance(exp, (int, float)) and not isinstance(exp, bool) and isinstance(v, (int, float)) and not isinstance(v, bool)
        if type(exp) is not type(v) and not num:
            issues.append(f"{k} 형식 {type(v).__name__} (정답지 {type(exp).__name__})")
        if isinstance(v, str) and _CITE.search(v) or isinstance(v, list) and any(isinstance(x, str) and _CITE.search(x) for x in v):
            issues.append(f"{k}에 인용 표시")
    extra = [g for g in obj if g not in case["answer"]]
    if extra:
        issues.append(f"정답지에 없는 키 {', '.join(extra)} (output_keys에 없으면 채점 안 됨)")
    if seconds is not None and seconds > 900:
        issues.append(f"{seconds:.0f}초, 15분 초과 (0점)")
    elif seconds is not None and seconds > 600:
        issues.append(f"{seconds:.0f}초, 15분 제한에 가까움")
    return issues


def job_seconds(job: dict) -> float | None:
    """Studio 쪽 기록으로 본 실행 시간 (--reuse에서도 쓸 수 있게)."""
    t0 = job.get("created_at")
    ts = [o.get("updated_at") or o.get("created_at") for o in job.get("output") or [] if isinstance(o, dict)]
    ts = [t for t in ts if isinstance(t, (int, float))]
    return round(max(ts) - t0, 1) if isinstance(t0, (int, float)) and ts else None


def run_case(case: dict, reuse: bool, base: Path = SUB, runs: Path = RUNS) -> dict:
    cid = case["case_id"]
    raw_path = runs / f"{cid}.json"
    t0 = time.time()
    if reuse:
        if not raw_path.exists():
            return {"case_id": cid, "error": "저장된 응답이 없습니다. --reuse 없이 먼저 실행하세요."}
        job = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        files = case["file"] if isinstance(case["file"], list) else [case["file"]]
        try:
            job = run_studio_job(str(base / files[0]), key=cid, raw_dir=runs)
        except Exception as e:
            return {"case_id": cid, "error": str(e)}
    fields, texts = parse_job_output(job)
    keys = list(case["answer"])
    got, hit = find_answer({"fields": fields, "texts": texts, "output": job.get("output")}, keys)
    if hit < 3:  # Validate 검사 결과처럼 reason 하나만 겹치는 dict는 정답 후보가 아님
        got = None
    steps = [o.get("model") or o.get("step_type") for o in job.get("output") or [] if isinstance(o, dict)]
    got = {k: _unwrap(v) for k, v in (got or {}).items()}
    rows = []
    for k, exp in case["answer"].items():
        ok, note = compare(exp, got.get(k)) if k not in SKIP_SCORE else (None, "")
        rows.append({"key": k, "expected": exp, "got": got.get(k), "ok": ok, "note": note})
    secs = job_seconds(job) if reuse else round(time.time() - t0, 1)
    return {"case_id": cid, "seconds": secs, "rows": rows, "strict": strict_check(job, case, secs),
            "extra_keys": sorted(set(got) - set(keys)), "last_step": steps,
            "structured": bool(got) and not any(isinstance(v, str) and "```" in v for v in texts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer", default=None, help="정답지 경로 (기본: submission/*_answer.json)")
    ap.add_argument("--cases", default="", help="쉼표로 구분한 case_id")
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--agent", default="", help="다른 워크플로우의 에이전트 ID (기본: .env)")
    ap.add_argument("--config", default="", help="설정 번호 (기본: .env)")
    a = ap.parse_args()

    ans_path = Path(a.answer) if a.answer else next(iter(sorted(SUB.glob("*_answer.json"))), None)
    if not ans_path or not ans_path.exists():
        sys.exit("정답지를 찾지 못했습니다. scripts/make_submission.py를 먼저 실행하세요.")
    answer = json.loads(ans_path.read_text(encoding="utf-8"))
    cases = answer["cases"]
    if a.cases:
        want = {c.strip() for c in a.cases.split(",")}
        cases = [c for c in cases if c["case_id"] in want]
    if a.agent:
        os.environ["UPSTAGE_STUDIO_AGENT_ID"] = a.agent
    if a.config:
        os.environ["UPSTAGE_STUDIO_CONFIG_ID"] = a.config
    base = ans_path.parent
    runs = base / "runs"
    runs.mkdir(parents=True, exist_ok=True)

    print(f"{len(cases)}건 {'저장된 응답으로 비교' if a.reuse else 'Studio 실행 중'}...")
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        results = list(ex.map(lambda c: run_case(c, a.reuse, base, runs), cases))

    total = hit = 0
    by_key: dict[str, list[int]] = {}
    for r in results:
        if r.get("error"):
            print(f"\n[{r['case_id']}] 실패: {r['error']}")
            continue
        scored = [x for x in r["rows"] if x["ok"] is not None]
        n_ok = sum(x["ok"] for x in scored)
        total += len(scored)
        hit += n_ok
        print(f"\n[{r['case_id']}] {n_ok}/{len(scored)}  ({r['seconds']}초, 마지막 노드: {', '.join(map(str, r['last_step']))})")
        if not any(x["got"] is not None for x in r["rows"]):
            print("   마지막 노드 출력에서 정답 키를 찾지 못했습니다. Instruct가 마지막 노드인지 확인하세요.")
        elif not r["structured"]:
            print("   주의: 키를 코드 블록 문자열에서 꺼냈습니다. Studio 출력이 필드가 아니라서 채점에서 0점일 수 있습니다.")
        for x in r["rows"]:
            if x["ok"] is not None:
                by_key.setdefault(x["key"], [0, 0])
                by_key[x["key"]][0] += x["ok"]
                by_key[x["key"]][1] += 1
            if x["ok"] is False:
                note = f"  [{x['note']}]" if x["note"] else ""
                print(f"   X {x['key']}: 정답 {json.dumps(x['expected'], ensure_ascii=False)}"
                      f"  출력 {json.dumps(x['got'], ensure_ascii=False)}{note}")
            elif x["ok"] is None:
                print(f"   - {x['key']}: {x['got']}")
        if r["extra_keys"]:
            print(f"   정답지에 없는 키: {', '.join(r['extra_keys'])}")

    print("\n===== 제출 점검 (채점과 같은 조건: 판정 노드 1개, 키 이름 그대로, 15분 제한) =====")
    bad = 0
    for r in results:
        if r.get("error"):
            bad += 1
            print(f"  [{r['case_id']}] 실패: 실행 오류 (0점)")
            continue
        if r.get("strict"):
            bad += 1
            print(f"  [{r['case_id']}] 문제 {len(r['strict'])}건 ({r['seconds']}초)")
            for x in r["strict"]:
                print(f"     - {x}")
        else:
            print(f"  [{r['case_id']}] 통과 ({r['seconds']}초)")
    print(f"  => {'전부 통과' if bad == 0 else f'{bad}건 확인 필요'}")
    if total:
        print(f"\n전체 {hit}/{total} ({hit / total:.0%})")
        print("키별: " + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in by_key.items()))
    (runs / "eval_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"자세한 결과: {runs / 'eval_report.json'}")


if __name__ == "__main__":
    main()
