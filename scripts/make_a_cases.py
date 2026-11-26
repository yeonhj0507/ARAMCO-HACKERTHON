"""워크플로우 A 입력 만들기: 프로젝트(사업자 폴더)마다 최신 반기 보고서 2건을 PDF 1개로 합친다.

    python scripts/make_a_cases.py

보고서 날짜는 이전에 Studio로 처리한 data/studio_output의 report_date를 쓰고, 없으면 파일 수정 시각을 쓴다.
내용이 같은 파일(사본)은 하나만 쓴다. 보고서가 1건뿐인 프로젝트는 1건짜리 케이스가 되고, A는 이를 검토 필요로 넘긴다.
출력: data/a_cases/{폴더}.pdf, data/a_cases/manifest.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
DOE = ROOT / "data" / "doe"
OUT = ROOT / "data" / "a_cases"


def report_dates() -> dict[tuple[str, str], str]:
    out = {}
    for f in (ROOT / "data" / "studio_output").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("source_folder") and r.get("source_file") and r.get("report_date"):
            out[(r["source_folder"], r["source_file"])] = r["report_date"]
    return out


_MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                            "september", "october", "november", "december"])}
_DATE = re.compile(r"(january|february|march|april|may|june|july|august|september|october|november|december|"
                   r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2}),?\s+(20\d{2})", re.I)


def date_from_pdf(pdf: Path) -> str | None:
    """첫 쪽 본문에서 처음 나오는 영문 날짜 (서신 날짜나 RECEIVED 도장). 스캔본이면 None."""
    try:
        text = PdfReader(str(pdf)).pages[0].extract_text() or ""
    except Exception:  # noqa: BLE001
        return None
    m = _DATE.search(text)
    if not m:
        return None
    mon = m.group(1).lower().rstrip(".")
    month = _MONTHS.get(mon) or next(v for k, v in _MONTHS.items() if k.startswith(mon[:3]))
    return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"


def main() -> int:
    dates = report_dates()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for folder in sorted(p for p in DOE.iterdir() if p.is_dir()):
        seen, files = set(), []
        for pdf in folder.glob("*.pdf"):
            h = hashlib.sha1(pdf.read_bytes()).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            d = dates.get((folder.name, pdf.name)) or date_from_pdf(pdf)
            files.append((d or "", pdf.stat().st_mtime, pdf, d is not None))
        if not files:
            continue
        files.sort(key=lambda x: (x[0], x[1]))
        pick = files[-2:]
        w = PdfWriter()
        for _, _, pdf, _ in pick:
            for page in PdfReader(str(pdf)).pages:
                w.add_page(page)
        dst = OUT / f"{folder.name}.pdf"
        with open(dst, "wb") as fh:
            w.write(fh)
        rows.append({"case_key": folder.name, "file": dst.name, "reports": len(pick),
                     "previous": pick[0][2].name if len(pick) == 2 else "", "latest": pick[-1][2].name,
                     "dates": " / ".join(x[0] or "날짜 미상" for x in pick)})
    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8-sig") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print(f"케이스 {len(rows)}건 (보고서 1건짜리 {sum(r['reports'] == 1 for r in rows)}건) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
