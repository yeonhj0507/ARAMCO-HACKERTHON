"""승인용 근거 보고서 (마크다운).

숫자와 표는 여기서 결정적으로 만든다. 문장 다듬기는 Studio Instruct 노드나 Solar에
이 마크다운을 넘겨서 하면 된다 (숫자는 바꾸지 말라고 지시).
"""
from __future__ import annotations

from pathlib import Path

from .planner import summarize
from .studio_client import search_documents


def _md_table(df) -> str:
    if df is None or len(df) == 0:
        return "(없음)\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def write_report(res: dict, base: dict, month: str, order_id: str, out_dir: Path) -> Path:
    s, b = summarize(res), summarize(base)
    sc = res["scenario"]
    a = res["allocation"]
    am = a[a.month == month][["source", "terminal", "cargoes", "kt", "cost_musd"]]
    prof = res["profiles"][["project", "docket", "slip_count", "total_slip_months", "latest_expected", "operating"]]
    hits = search_documents("delay delayed revised extend deadline", top_k=4)

    lines = [
        f"# 배분 근거 보고서 ({order_id})",
        "",
        f"- 시나리오: `{sc['name']}` (호르무즈 차단 {sc['hormuz_blocked_months']}개월, 현물가 x{sc['spot_price_multiplier']}, "
        f"현물 물량 x{sc['spot_volume_multiplier']}, 미국 추가 지연 {sc['us_extra_delay_months']}개월)",
        f"- 대상 월: {month}",
        "",
        "## 1. 요약",
        f"- 총비용 {s['total_cost_musd']:,} 백만 달러 (기본 대비 {s['total_cost_musd'] - b['total_cost_musd']:+,.1f})",
        f"- 현물 카고 {s['spot_cargoes']}척 (기본 대비 {s['spot_cargoes'] - b['spot_cargoes']:+d})",
        f"- 미국 미계약 물량 협상 카고 {s['us_uncontracted_cargoes']}척",
        f"- 공급 부족 {s['total_shortage_kt']} kt",
        "",
        f"## 2. {month} 배분안",
        _md_table(am),
        "## 3. 미국 공급 리스크 (DOE 반기 보고서 추출)",
        _md_table(prof),
        "## 4. 근거 문장",
    ]
    for h in hits:
        lines.append(f"- {h['project']} / {h['docket']} / {h['report_date']} p.{h['page']}: {h['text']}")
    lines += ["", "## 5. 승인", "- 상태: PENDING_APPROVAL", "- 승인자: ", ""]
    path = out_dir / f"{order_id}_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
