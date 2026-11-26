"""최적화 결과 -> 'LNG 배분 실행안' PDF (워크플로우 C 입력)와 코드 검산.

실행안은 연간 최적화 결과 중 앞 EXEC_MONTHS개월분이다. 표에 인쇄되는 값은 모두 정수로 반올림하고,
코드 검산(check_tables)도 인쇄된 값으로 한다. Studio C의 판정과 코드 검산이 다르면 사람이 본다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import planner
from .optimizer import CARGO_KT, SAFETY_RATIO

ROOT = Path(__file__).resolve().parents[1]
EXEC_MONTHS = 3
MISMATCH_KT = 5
SOURCE_NAMES = {"QATAR_LT": "카타르 장기", "OMAN_LT": "오만 장기", "AUSTRALIA_LT": "호주 장기", "MALAYSIA_LT": "말레이시아 장기",
                "OTHER_LT": "기타 장기", "US_LT": "미국 장기", "US_UNCONTRACTED": "미국 미계약", "SPOT": "현물"}


def source_name(s: str) -> str:
    if s.startswith("US_NEW_"):
        return "미국 신규 " + s[len("US_NEW_"):].replace("_LLC", "").replace("_", " ")
    return SOURCE_NAMES.get(s, s)


def build_tables(res: dict, months: int = EXEC_MONTHS) -> dict:
    """planner.run 결과에서 실행안 표 세 개를 만든다."""
    ms = sorted(res["inventory"]["month"].unique())[:months]
    alloc, inv, avail = res["allocation"], res["inventory"], res["avail"]
    terms = res.get("terminals")
    if terms is None:
        terms = planner._static()[0]
    terms = terms.set_index("terminal")

    supply = []
    for s in sorted(avail["source"].unique()):
        for m in ms:
            av = float(avail[(avail.source == s) & (avail.month == m)]["avail_kt"].sum())
            plan_c = int(round(alloc[(alloc.source == s) & (alloc.month == m)]["cargoes"].sum()))
            av_c = math.ceil(av / CARGO_KT - 1e-9)
            if av_c == 0 and plan_c == 0:
                continue
            supply.append({"source": s, "month": m, "avail_cargoes": av_c, "plan_cargoes": plan_c,
                           "plan_kt": int(plan_c * CARGO_KT)})

    stock = []
    for _, r in inv[inv.month.isin(ms)].sort_values(["terminal", "month"]).iterrows():
        cap = float(terms.loc[r.terminal, "storage_kt"])
        stock.append({"terminal": r.terminal, "month": r.month, "demand_kt": int(round(r.demand_kt)),
                      "inventory_kt": int(round(r.inventory_kt)), "capacity_kt": int(round(cap)),
                      "safety_kt": int(round(cap * SAFETY_RATIO)), "shortage_kt": int(round(r.shortage_kt))})

    summary = []
    for m in ms:
        summary.append({"month": m,
                        "demand_kt": sum(x["demand_kt"] for x in stock if x["month"] == m),
                        "planned_kt": sum(x["plan_kt"] for x in supply if x["month"] == m),
                        "shortage_kt": sum(x["shortage_kt"] for x in stock if x["month"] == m),
                        "spot_cargoes": sum(x["plan_cargoes"] for x in supply if x["month"] == m and x["source"] == "SPOT")})
    return {"months": ms, "supply": supply, "stock": stock, "summary": summary}


def check_tables(t: dict, plan_id: str) -> dict:
    """워크플로우 C와 같은 규칙을 코드로 계산한 결과 (출력 키도 같다)."""
    sup, stock, summ = t["supply"], t["stock"], t["summary"]
    over = [f"{x['source']},{x['month']},{x['plan_cargoes']},{x['avail_cargoes']}" for x in sup if x["plan_cargoes"] > x["avail_cargoes"]]
    cap = [f"{x['terminal']},{x['month']},{x['inventory_kt']},{x['capacity_kt']}" for x in stock if x["inventory_kt"] > x["capacity_kt"]]
    safe = [f"{x['terminal']},{x['month']},{x['inventory_kt']},{x['safety_kt']}" for x in stock if x["inventory_kt"] < x["safety_kt"]]
    mism = []
    for s in summ:
        tot = sum(x["plan_kt"] for x in sup if x["month"] == s["month"])
        if abs(tot - s["planned_kt"]) > MISMATCH_KT:
            mism.append(f"{s['month']},{tot},{s['planned_kt']}")
    short = [f"{s['month']},{s['shortage_kt']}" for s in summ if s["shortage_kt"] > 0]
    spot = sum(x["plan_cargoes"] for x in sup if x["source"] == "SPOT")
    bad = over or cap or safe or mism
    if bad:
        parts = [n for n, v in [("계약 초과", over), ("저장용량 초과", cap), ("안전재고 미달", safe), ("합계 불일치", mism)] if v]
        reason = f"{', '.join(parts)} 항목이 있어 재계획이 필요하다."
    else:
        reason = f"현물 카고 {spot}척" + (f", 부족 월 {', '.join(r.split(',')[0] for r in short)}" if short else ", 부족 월 없음") + "."
    return {"plan_id": plan_id, "period_start": t["months"][0], "period_end": t["months"][-1],
            "total_planned_kt": sum(x["plan_kt"] for x in sup), "spot_cargoes": spot,
            "shortage_rows": short, "over_contract_rows": over, "capacity_rows": cap, "safety_rows": safe,
            "mismatch_rows": mism, "decision": "재계획 필요" if bad else "승인 요청", "reason": reason}


DECISION_KEYS = ["over_contract_rows", "capacity_rows", "safety_rows", "mismatch_rows", "decision"]


def compare_checks(studio: dict, code: dict) -> list[str]:
    """Studio 판정과 코드 검산이 다른 키 (목록은 순서 무시)."""
    diff = []
    for k in DECISION_KEYS + ["shortage_rows", "spot_cargoes", "total_planned_kt"]:
        a, b = studio.get(k), code.get(k)
        if isinstance(a, list) and isinstance(b, list):
            if sorted(map(str, a)) != sorted(map(str, b)):
                diff.append(k)
        elif str(a) != str(b):
            diff.append(k)
    return diff


# ---------- PDF ----------
def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "KR" in pdfmetrics.getRegisteredFontNames():
        return "KR"
    for path in [ROOT / "data" / "fonts" / "NanumGothic-Regular.ttf", Path("C:/Windows/Fonts/malgun.ttf"),
                 Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")]:
        if path.exists():
            pdfmetrics.registerFont(TTFont("KR", str(path)))
            return "KR"
    raise RuntimeError("한글 글꼴을 찾지 못했습니다 (data/fonts/NanumGothic-Regular.ttf 또는 맑은 고딕).")


def write_pdf(t: dict, path: Path, plan_id: str, scenario_text: str, scenario: dict | None = None) -> Path:
    """실행안 PDF와, 같은 이름의 .json(표 데이터와 시나리오, 재계획과 오프라인 검산용)을 쓴다."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    f = _font()
    h1 = ParagraphStyle("h1", fontName=f, fontSize=15, leading=20, spaceAfter=6)
    h2 = ParagraphStyle("h2", fontName=f, fontSize=11, leading=15, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", fontName=f, fontSize=9, leading=13)

    def table(header, rows, widths):
        tb = Table([header] + rows, colWidths=widths, repeatRows=1)
        tb.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
                                ("ALIGN", (2, 1), (-1, -1), "RIGHT")]))
        return tb

    story = [Paragraph("LNG 배분 실행안 (승인 요청용)", h1),
             Paragraph(f"실행안 번호: {plan_id}", body),
             Paragraph(f"대상 기간: {t['months'][0]} ~ {t['months'][-1]} (연간 최적화 결과 중 앞 {len(t['months'])}개월)", body),
             Paragraph(f"시나리오: {scenario_text}", body),
             Paragraph(f"단위: 물량 kt(천 톤), 카고 1척 = {int(CARGO_KT)} kt. 안전재고 = 저장용량의 {int(SAFETY_RATIO * 100)}%", body),
             Paragraph("1. 공급원별 카고 계획", h2),
             table(["공급원", "코드", "월", "가용 카고", "계획 카고", "계획 물량(kt)"],
                   [[source_name(x["source"]), x["source"], x["month"], x["avail_cargoes"], x["plan_cargoes"],
                     f"{x['plan_kt']:,}"] for x in t["supply"]], [70, 105, 55, 55, 55, 70]),
             Paragraph("2. 기지별 월말 재고", h2),
             table(["기지", "월", "수요(kt)", "월말 재고(kt)", "저장용량(kt)", "안전재고(kt)", "부족(kt)"],
                   [[x["terminal"], x["month"], f"{x['demand_kt']:,}", f"{x['inventory_kt']:,}", f"{x['capacity_kt']:,}",
                     f"{x['safety_kt']:,}", f"{x['shortage_kt']:,}"] for x in t["stock"]], [75, 50, 60, 70, 70, 65, 50]),
             Paragraph("3. 월별 수급 요약", h2),
             table(["월", "수요 합계(kt)", "계획 입고 합계(kt)", "부족 합계(kt)", "현물 카고"],
                   [[s["month"], f"{s['demand_kt']:,}", f"{s['planned_kt']:,}", f"{s['shortage_kt']:,}", s["spot_cargoes"]]
                    for s in t["summary"]], [60, 85, 100, 85, 60]),
             Spacer(1, 10),
             Paragraph("작성: 배분 최적화 엔진 / 검토: 수급계획팀 담당자", body)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40).build(story)
    path.with_suffix(".json").write_text(json.dumps({"plan_id": plan_id, "scenario_text": scenario_text, "scenario": scenario,
                                                     "tables": t}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
