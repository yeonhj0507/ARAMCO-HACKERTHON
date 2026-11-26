"""해커톤 제출용 데이터셋 PDF, 정답지 JSON, 유형표 xlsx를 만든다.

    python scripts/make_submission.py --team 팀명 [--stage 최종제출]

케이스 1건 = 프로젝트 1개의 연속 반기 보고서 2건 (직전 + 최신)을 PDF 1개로 합친 것.
정답 값은 원문을 직접 읽고 아래 규칙대로 정했다. 규칙은 Studio 워크플로우 프롬프트와 같다.

출력 키 규칙
- docket: 최신 보고서에 처음 나오는 FE 도켓 번호 (예: 12-88-LNG)
- stage: 가장 앞선 트레인 기준. pre_fid(FID 전) / construction(FID 후 건설)
         / commissioning(첫 LNG 생산 후 상업운전 전) / operating(상업운전 중)
- operating: 첫 LNG를 생산했으면 true (시운전 카고 포함)
- online_month: 이미 생산했으면 첫 LNG 생산 월, 아니면 최신 보고서의 가동 예정 시점
                (상업운전, 첫 수출, COD 중 적힌 것). 연도만 있으면 그 해 12월. 없으면 ""
- slip_months: 최신과 직전 보고서의 가동 예정 시점 차이(개월). 가동 중이거나 한쪽이 없으면 0.
               허가 기한 연장(FERC/DOE deadline)은 일정 변경으로 보지 않는다
- kr_buyers: 두 보고서에 LNG 구매 계약(SPA)이 체결됐다고 적힌 한국 회사, 보고서 표기 그대로.
             원료가스 공급 계약, EPC 등 구매자가 아닌 한국 회사는 넣지 않는다
- kr_mtpa: 한국 구매자 계약 물량 합계, 적혀 있지 않으면 0
- uncontracted_mtpa: 미계약 물량이 적혀 있거나 (허가 용량 - 확보 물량)으로 바로 계산되면 그 값, 아니면 0
- config_status: 반영 / 검토 필요.
    검토 필요: 두 보고서의 도켓이 다를 때, 핵심 값을 읽을 수 없을 때,
               개발 중단이 공시됐는데 한국 구매 계약이 남아 있을 때
    도켓이 다르면 나머지 값은 최신 보고서 한 건만으로 채우고 slip_months=0
- reason: 1~2문장 근거
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
DOE = ROOT / "data" / "doe"
TEMPLATE_XLSX = ROOT / "Studio_해커톤_미션_템플릿" / "팀명_미션_유형표_템플릿.xlsx"

OUTPUT_KEYS = ["docket", "stage", "operating", "online_month", "slip_months",
               "kr_buyers", "kr_mtpa", "uncontracted_mtpa", "config_status", "reason"]
DECISION_VALUES = ["반영", "검토 필요"]

# docs: (폴더/파일, 문서 종류, 유형, 시험 목적)
CASES = [
    {
        "case_id": "A",
        "name": "Golden Pass",
        "docs": [
            ("Golden_Pass_LNG_Terminal_LLC/20260401_DOE_GP_Semi-Annual_Report.pdf",
             "반기 보고서 2026-04", "① 단순", "첫 LNG 생산일(2026-03-30)을 online_month로 읽는지"),
            ("Golden_Pass_LNG_Terminal_LLC/DOE_Semi-Annual_Report_1012026_Final_Golden_Pass_LNG.pdf",
             "반기 보고서 2026-10", "① 단순", "원료가스 공급 계약(Apex, Matador)을 LNG 구매자로 보지 않는지"),
        ],
        "answer": {
            "docket": "12-88-LNG", "stage": "commissioning", "operating": True,
            "online_month": "2026-03", "slip_months": 0, "kr_buyers": [], "kr_mtpa": 0,
            "uncontracted_mtpa": 0, "config_status": "반영",
            "reason": "2026년 3월 30일 첫 LNG를 생산해 시운전 단계다. 한국 구매자 계약은 없다.",
        },
    },
    {
        "case_id": "B",
        "name": "Commonwealth",
        "docs": [
            ("Commonwealth_LNG_LLC/Commonwealth_LNG_--_DOE_Semi-Annual_Report_(April_2026).pdf",
             "반기 보고서 2026-04", "① 단순", "FID 전 단계와 첫 수출 예정 연도(2029) 읽기"),
            ("Commonwealth_LNG_LLC/Commonwealth_LNG_--_DOE_Semi-Annual_Report_(Oct_2026).pdf",
             "반기 보고서 2026-10", "③ 예외", "FID 후 건설 전환, 연도만 있는 날짜(2030)를 12월로 두고 12개월 지연 계산, 미계약 물량 9.5-8.5 계산"),
        ],
        "answer": {
            "docket": "19-134-LNG", "stage": "construction", "operating": False,
            "online_month": "2030-12", "slip_months": 12, "kr_buyers": [], "kr_mtpa": 0,
            "uncontracted_mtpa": 1.0, "config_status": "반영",
            "reason": "2026년 FID를 내려 건설 단계이고, 가동 목표가 2029년에서 2030년으로 12개월 밀렸다. 한국 구매자 계약은 없다.",
        },
    },
    {
        "case_id": "C",
        "name": "Cameron",
        "docs": [
            ("Cameron_LNG_LLC/2026-04-01_Cameron_LNG_Semi-Annual_Report.pdf",
             "반기 보고서 2026-04", "② 여러 양식, ③ 예외", "도켓 6개가 나열된 양식, 증설 허가 기한 연장(2028→2033)을 일정 지연으로 보지 않는지"),
            ("Cameron_LNG_LLC/2026-09-29_Cameron_LNG_Semi-Annual_Report_0.pdf",
             "반기 보고서 2026-09 (스캔본)", "④ 저품질", "텍스트 레이어가 없는 스캔본에서 상업운전 시점(2020-08) 읽기"),
        ],
        "answer": {
            "docket": "11-145-LNG", "stage": "operating", "operating": True,
            "online_month": "2020-08", "slip_months": 0, "kr_buyers": [], "kr_mtpa": 0,
            "uncontracted_mtpa": 0, "config_status": "반영",
            "reason": "2020년 8월 10일부터 Train 1~3이 상업운전 중이라 운영 단계다. 한국 구매자 계약은 없다.",
        },
    },
    {
        "case_id": "D",
        "name": "Lake Charles LNG Export",
        "docs": [
            ("Lake_Charles_LNG_Export_Company_LLC/20251001_LCLNG-EXPORT-DOE_FE-OrderNos_3252_3868_S.A.Rpt_.ir_.pdf",
             "반기 보고서 2025-10", "② 여러 양식", "보도자료 링크가 섞인 SPA 목록에서 한국 구매자(SK Gas Trading) 찾기"),
            ("Lake_Charles_LNG_Export_Company_LLC/20260401_LCLNG-EXPORT-DOE_FE-OrderNos_3252_3868_S.A.Rpt_.ir_.pdf",
             "반기 보고서 2026-04", "③ 예외", "개발 중단 공시와 한국 계약이 함께 있을 때 검토 필요로 넘기는지, 상대 일정(착공 후 52개월)을 날짜로 만들지 않는지"),
        ],
        "answer": {
            "docket": "13-04-LNG", "stage": "pre_fid", "operating": False,
            "online_month": "", "slip_months": 0, "kr_buyers": ["SK Gas Trading LLC"], "kr_mtpa": 0,
            "uncontracted_mtpa": 0, "config_status": "검토 필요",
            "reason": "FID 전에 개발 중단이 발표됐는데 SK Gas Trading과의 LNG 구매 계약이 남아 있어 검토가 필요하다. 가동 시점은 착공 후 52개월로만 적혀 있어 정할 수 없다.",
        },
    },
    {
        "case_id": "E",
        "name": "Gato Negro",
        "docs": [
            ("Gato_Negro_Permitium_Uno_S_A_P_I_de_C_V/24-43_April_2026.pdf",
             "반기 보고서 2026-04 (스캔본)", "④ 저품질", "스캔본에서 COD 목표(late 2030) 읽기"),
            ("Gato_Negro_Permitium_Uno_S_A_P_I_de_C_V/scan_20261008112921.pdf",
             "반기 보고서 2026-10 (스캔본)", "④ 저품질, ③ 예외", "COD 2030→2031 지연 계산, 한국 EPC(Samsung E&A)를 구매자로 넣지 않는지"),
        ],
        "answer": {
            "docket": "24-43-LNG", "stage": "pre_fid", "operating": False,
            "online_month": "2031-12", "slip_months": 12, "kr_buyers": [], "kr_mtpa": 0,
            "uncontracted_mtpa": 0, "config_status": "반영",
            "reason": "FID 전이고, 상업운전 목표가 2030년 말에서 2031년 말로 12개월 밀렸다. 한국 구매자 계약은 없다.",
        },
    },
    {
        "case_id": "F",
        "name": "Plaquemines",
        "docs": [
            ("Venture_Global_Plaquemines_LNG_LLC/VG_Plaquemines_April_2026_DOE_Progress_Report_(040126).pdf",
             "진행 보고서 2026-04", "② 여러 양식", "로펌 서신 양식(a/b/c 항목)에서 단계와 계약 상태 읽기"),
            ("Venture_Global_Plaquemines_LNG_LLC/VG_Plaquemines_October_2026_DOE_Progress_Report.pdf",
             "진행 보고서 2026-10", "③ 예외", "상업운전 예정일(2026-10-31) 대신 첫 LNG 생산 월(2024-12)을 쓰는지, 원료가스 계약 8건을 구매자로 보지 않는지"),
        ],
        "answer": {
            "docket": "16-28-LNG", "stage": "commissioning", "operating": True,
            "online_month": "2024-12", "slip_months": 0, "kr_buyers": [], "kr_mtpa": 0,
            "uncontracted_mtpa": 0, "config_status": "반영",
            "reason": "2024년 12월 첫 LNG를 생산하고 시운전 카고를 수출해 시운전 단계다. 한국 구매자 계약은 없다.",
        },
    },
    {
        "case_id": "G",
        "name": "Lake Charles 도켓 불일치",
        "docs": [
            ("Lake_Charles_Exports_LLC/20260401_LCE_LCLNG-EXPORT-DOE_FE-Orders_3324_3324-A_S.A.Rpt_.ir_.pdf",
             "반기 보고서 2026-04 (Lake Charles Exports, 11-59-LNG)", "③ 예외", "이름이 비슷한 다른 허가 보유자 보고서가 섞였을 때 도켓 불일치를 잡는지"),
            ("Lake_Charles_LNG_Export_Company_LLC/20261001_LCLNG-EXPORT-DOE_FE-OrderNos_3252_3868_S.A.Rpt_.ir_Lake_Charles_LNG_Exports.pdf",
             "반기 보고서 2026-10 (Lake Charles LNG Export, 13-04-LNG)", "③ 예외", "불일치 시 최신 보고서 값만 쓰고 지연을 계산하지 않는지"),
        ],
        "answer": {
            "docket": "13-04-LNG", "stage": "pre_fid", "operating": False,
            "online_month": "", "slip_months": 0, "kr_buyers": [], "kr_mtpa": 0,
            "uncontracted_mtpa": 0, "config_status": "검토 필요",
            "reason": "두 보고서의 도켓이 11-59-LNG와 13-04-LNG로 달라 같은 허가의 연속 보고서로 볼 수 없어 검토가 필요하다. 최신 보고서 기준으로 FID 전이고 개발 중단 상태다.",
        },
    },
]


def build(team: str, stage: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    answer_cases, rows = [], []
    for i, case in enumerate(CASES, start=1):
        fname = f"{team}_{stage}_set{i:02d}.pdf"
        writer = PdfWriter()
        page = 1
        for rel, doc_type, kind, purpose in case["docs"]:
            reader = PdfReader(str(DOE / rel))
            n = len(reader.pages)
            for p in reader.pages:
                writer.add_page(p)
            pages = f"{page}" if n == 1 else f"{page}-{page + n - 1}"
            rows.append([fname, pages, f"{case['case_id']} {case['name']}", doc_type, kind, purpose,
                         case["answer"]["config_status"]])
            page += n
        with open(out / fname, "wb") as f:
            writer.write(f)
        answer_cases.append({
            "case_id": case["case_id"],
            "file": fname,
            "documents": [d[1] for d in case["docs"]],
            "answer": {k: case["answer"][k] for k in OUTPUT_KEYS},
        })

    answer = {
        "task": "미국 LNG 수출 프로젝트 DOE 보고서에서 수급 최적화 모델의 공급 파라미터 추출",
        "unit": "프로젝트 1개의 연속 반기 보고서 2건 = 케이스 1건 = 파라미터 레코드 1건",
        "output_keys": OUTPUT_KEYS,
        "decision_values": DECISION_VALUES,
        "cases": answer_cases,
    }
    (out / f"{team}_{stage}_answer.json").write_text(
        json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")

    import openpyxl
    wb = openpyxl.load_workbook(TEMPLATE_XLSX)
    ws = wb["유형표"]
    ws.delete_rows(2, 3)  # 회색 예시 줄 3개 삭제
    for r, row in enumerate(rows, start=2):
        ws.cell(r, 1, r - 1)
        for c, v in enumerate(row, start=2):
            ws.cell(r, c, v)
    wb.save(out / f"{team}_{stage}_유형표.xlsx")
    print(f"케이스 {len(CASES)}건, 문서 {len(rows)}건 -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="팀명")
    ap.add_argument("--stage", default="최종제출")
    ap.add_argument("--out", default=str(ROOT / "submission"))
    a = ap.parse_args()
    build(a.team, a.stage, Path(a.out))
