"""워크플로우 C(실행안 검증) 테스트용 배분 실행안 PDF와 정답지를 만든다.

    python scripts/make_allocation_docs.py

시나리오별로 최적화를 돌려 앞 3개월분 실행안을 쓰고, 일부는 담당자가 손으로 고친 것처럼 오류를 하나씩 넣는다.
정답은 PDF에 인쇄된 값으로 lng.execdoc.check_tables가 계산한다 (Studio C와 같은 규칙).
출력: data/allocations/C_setNN.pdf (+ 같은 이름 .json), data/allocations/c_answer.json
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lng import execdoc, planner  # noqa: E402
from lng.optimizer import CARGO_KT  # noqa: E402
from lng.workflows import KEYS  # noqa: E402

OUT = ROOT / "data" / "allocations"


# ---------- 담당자가 손으로 고친 것 같은 오류 ----------
def edit_capacity(t, terminal="INCHEON", month_idx=1, over=50):
    m = t["months"][month_idx]
    for x in t["stock"]:
        if x["terminal"] == terminal and x["month"] == m:
            x["inventory_kt"] = x["capacity_kt"] + over
    return t


def edit_safety(t, terminal="PYEONGTAEK", month_idx=0, under=60):
    m = t["months"][month_idx]
    for x in t["stock"]:
        if x["terminal"] == terminal and x["month"] == m:
            x["inventory_kt"] = x["safety_kt"] - under
    return t


def edit_over_contract(t, source="QATAR_LT", month_idx=1, cargoes=7):
    """가용 카고보다 많이 잡은 계획. 요약 표도 같이 고쳐서 오류는 이것 하나만 남긴다."""
    m = t["months"][month_idx]
    row = next((x for x in t["supply"] if x["source"] == source and x["month"] == m), None)
    if row is None:
        row = {"source": source, "month": m, "avail_cargoes": 0, "plan_cargoes": 0, "plan_kt": 0}
        t["supply"].append(row)
        t["supply"].sort(key=lambda x: (x["source"], x["month"]))
    row["plan_cargoes"] = row["avail_cargoes"] + cargoes
    row["plan_kt"] = int(row["plan_cargoes"] * CARGO_KT)
    for s in t["summary"]:
        s["planned_kt"] = sum(x["plan_kt"] for x in t["supply"] if x["month"] == s["month"])
    return t


def edit_mismatch(t, month_idx=2, delta=700):
    t["summary"][month_idx]["planned_kt"] += delta
    return t


def make_scan(src: Path, dst: Path) -> bool:
    """인쇄 후 스캔한 것처럼 기울이고 흐리게 만든 이미지 PDF. poppler(pdftoppm)가 없으면 건너뛴다."""
    if not shutil.which("pdftoppm"):
        return False
    from PIL import Image, ImageFilter
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", "110", "-gray", "-png", str(src), f"{d}/p"], check=True)
        pages = [Image.open(p).convert("L").rotate(1.3, expand=True, fillcolor=245).filter(ImageFilter.GaussianBlur(0.7)).convert("RGB")
                 for p in sorted(Path(d).glob("p*.png"))]
        pages[0].save(dst, save_all=True, append_images=pages[1:], resolution=110)
    return True


CASES = [
    # case_id, 시나리오, 설명, 오류 편집, 유형, 시험 목적
    ("C1", planner.Scenario(name="baseline"), "기본 계획", None, "① 단순", "깨끗한 실행안을 승인 요청으로 넘기는지"),
    ("C2", planner.Scenario(name="hormuz3", hormuz_blocked_months=3), "호르무즈 해협 3개월 차단", None, "① 단순",
     "카타르 물량이 0인 달과 현물 카고 합계를 읽는지"),
    ("C3", planner.Scenario(name="hormuz3_tight", hormuz_blocked_months=3, spot_volume_multiplier=0.5, demand_multiplier=1.1),
     "호르무즈 3개월 차단, 현물 확보량 50%, 수요 110%", None, "③ 예외", "부족이 나도 오류는 아니므로 승인 요청으로 두고 부족 월을 적는지"),
    ("C4", planner.Scenario(name="baseline"), "기본 계획 (담당자 수정본)", edit_capacity, "③ 예외", "월말 재고가 저장용량을 넘는 수정을 잡는지"),
    ("C5", planner.Scenario(name="hormuz3", hormuz_blocked_months=3), "호르무즈 해협 3개월 차단 (담당자 수정본)", edit_over_contract,
     "③ 예외", "가용 카고가 0인 카타르에 카고를 잡은 수정을 잡는지"),
    ("C6", planner.Scenario(name="baseline"), "기본 계획 (담당자 수정본)", edit_mismatch, "③ 예외", "요약 표 합계가 1번 표 합계와 다른 것을 잡는지"),
    ("C7", planner.Scenario(name="baseline"), "기본 계획 (담당자 수정본)", edit_safety, "③ 예외", "안전재고 아래로 내려간 재고를 잡는지"),
    ("C8", planner.Scenario(name="hormuz3", hormuz_blocked_months=3), "호르무즈 해협 3개월 차단", None, "④ 저품질",
     "기울고 흐린 스캔본에서 C2와 같은 값을 읽는지"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict] = {}
    cases = []
    for i, (cid, sc, text, edit, kind, purpose) in enumerate(CASES, start=1):
        sc = replace(sc, use_studio=False)  # 테스트 세트는 샘플 입력으로 고정 (A, B 결과가 쌓여도 안 바뀌게)
        if sc.name not in cache:
            cache[sc.name] = execdoc.build_tables(planner.run(sc))
        t = copy.deepcopy(cache[sc.name])
        if edit:
            t = edit(t)
        plan_id = f"ALLOC-{t['months'][0].replace('-', '')}-{cid}"
        fname = f"C_set{i:02d}.pdf"
        if kind.startswith("④"):
            with tempfile.TemporaryDirectory() as d:
                clean = execdoc.write_pdf(t, Path(d) / fname, plan_id, text, asdict(sc))
                shutil.copyfile(clean.with_suffix(".json"), (OUT / fname).with_suffix(".json"))
                if not make_scan(clean, OUT / fname):
                    shutil.copyfile(clean, OUT / fname)
                    print(f"{cid}: pdftoppm이 없어 스캔본 대신 원본 PDF로 둡니다.")
        else:
            execdoc.write_pdf(t, OUT / fname, plan_id, text, asdict(sc))
        ans = execdoc.check_tables(t, plan_id)
        ans["reason"] = purpose
        cases.append({"case_id": cid, "file": fname, "documents": ["LNG 배분 실행안"], "type": kind,
                      "purpose": purpose, "answer": ans})
        print(f"{cid} {fname}  {ans['decision']}  부족 {ans['shortage_rows']}  초과 {ans['over_contract_rows']} "
              f"용량 {ans['capacity_rows']} 안전 {ans['safety_rows']} 불일치 {ans['mismatch_rows']}")
    answer = {"task": "LNG 배분 실행안을 승인 전에 검증하고 현물 구매 요청과 재계획 여부를 판정",
              "unit": "실행안 1건 = 케이스 1건", "output_keys": KEYS["C"],
              "decision_values": ["승인 요청", "재계획 필요"], "cases": cases}
    (OUT / "c_answer.json").write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(cases)}건 -> {OUT}")


if __name__ == "__main__":
    main()
