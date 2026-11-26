"""샘플 데이터 생성 스크립트.

여기서 만드는 숫자는 전부 '구조 테스트용 샘플'이다. 실제 값이 아니다.
실데이터로 바꿀 곳:
  - data/sample/terminals.csv   -> 16차 장기 천연가스 수급계획 [별첨3] 인프라 현황
  - data/sample/sources.csv     -> 가스공사 도입계약 공개자료, 관세청 수입단가
  - data/sample/demand_history.csv -> 공공데이터포털 '한국가스공사 생산기지 용도별 월 공급량'
  - data/studio_output/*.json   -> Upstage Studio Extract 결과 (DOE 반기 보고서)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
STUDIO = ROOT / "data" / "studio_output"
SAMPLE.mkdir(parents=True, exist_ok=True)
STUDIO.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(42)

# 1. 생산기지 (샘플 용량)
terminals = pd.DataFrame(
    [
        # terminal, 저장용량(kt), 월 최대 하역 카고 수, 초기재고 비율, 수요 비중
        ("PYEONGTAEK", 1400, 30, 0.5, 0.32),
        ("INCHEON", 1300, 28, 0.5, 0.30),
        ("TONGYEONG", 1000, 20, 0.5, 0.20),
        ("SAMCHEOK", 900, 16, 0.5, 0.16),
        ("JEJU", 90, 0, 0.5, 0.02),  # 직접 하역 없음, 통영에서 내항선
    ],
    columns=["terminal", "storage_kt", "max_cargo_per_month", "init_inv_ratio", "demand_share"],
)
terminals.to_csv(SAMPLE / "terminals.csv", index=False)

# 2. 공급원 (샘플). QATAR_LT 610만톤은 공개 보도 기준, 단가는 2024 국가별 수입단가 보도 기준.
#    나머지 물량과 운항일수, take-or-pay 비율은 샘플 가정.
sources = pd.DataFrame(
    [
        # source, 유형, 연간물량(MTPA), 단가($/t), 운항일수, 호르무즈 경유, TOP 비율
        ("QATAR_LT", "long_term", 6.1, 745, 20, True, 0.9),
        ("OMAN_LT", "long_term", 4.0, 700, 18, False, 0.9),
        ("AUSTRALIA_LT", "long_term", 9.0, 628, 12, False, 0.9),
        ("MALAYSIA_LT", "long_term", 4.0, 552, 7, False, 0.9),
        ("OTHER_LT", "long_term", 12.0, 650, 12, False, 0.85),
        ("US_LT", "long_term_forecast", 0.0, 549, 30, False, 0.9),  # 물량은 공급 예측 모듈이 채움
        ("SPOT", "spot", 24.0, 900, 20, False, 0.0),
    ],
    columns=["source", "kind", "annual_mtpa", "price_usd_t", "voyage_days", "via_hormuz", "top_ratio"],
)
sources.to_csv(SAMPLE / "sources.csv", index=False)

# 3. 월별 수요 이력 (2016-01 ~ 2025-12, 전국, 용도별, kt). 계절성 + 약한 추세 + 노이즈.
months = pd.date_range("2016-01-01", "2025-12-01", freq="MS")
rows = []
for i, m in enumerate(months):
    season = np.cos(2 * np.pi * (m.month - 1) / 12)  # 1월 최대
    city = 1650 + 750 * season + 2.0 * i + rng.normal(0, 60)
    power = 1700 + 250 * season + 120 * np.cos(2 * np.pi * (m.month - 8) / 12) - 1.5 * i + rng.normal(0, 90)
    rows.append((m.strftime("%Y-%m"), "city_gas", round(city, 1)))
    rows.append((m.strftime("%Y-%m"), "power", round(power, 1)))
pd.DataFrame(rows, columns=["month", "use", "supply_kt"]).to_csv(SAMPLE / "demand_history.csv", index=False)

# 4. Studio Extract 결과 샘플 (DOE 반기 보고서에서 뽑았다고 가정한 레코드)
projects = [
    {
        "project": "US Project A (sample)",
        "docket": "00-000-LNG",
        "terminal_location": "Texas",
        "authorized_mtpa": 15.0,
        "reports": [
            ("2025-04-01", "2026-06-01", "Train 1 construction 72% complete."),
            ("2025-10-01", "2026-09-01", "Commissioning schedule revised due to equipment delivery."),
            ("2026-04-01", "2026-12-01", "Train 1 first LNG expected Q4 2026."),
        ],
        "contracts": [
            {"buyer": "KOGAS", "buyer_country": "KR", "mtpa": 2.0, "start_year": 2027, "term_years": 15},
            {"buyer": "Buyer X", "buyer_country": "JP", "mtpa": 3.0, "start_year": 2027, "term_years": 20},
        ],
        "uncontracted_mtpa": 4.0,
    },
    {
        "project": "US Project B (sample)",
        "docket": "00-001-LNG",
        "terminal_location": "Louisiana",
        "authorized_mtpa": 20.0,
        "reports": [
            ("2025-04-01", "2025-12-01", "Facility in final commissioning."),
            ("2025-10-01", "2025-12-01", "Commercial operation on schedule."),
            ("2026-04-01", "2026-01-01", "Commercial operation commenced January 2026."),
        ],
        "contracts": [
            {"buyer": "KR Private Buyer (sample)", "buyer_country": "KR", "mtpa": 1.5, "start_year": 2026, "term_years": 20},
        ],
    },
    {
        "project": "US Project C (sample)",
        "docket": "00-002-LNG",
        "terminal_location": "Texas",
        "authorized_mtpa": 12.0,
        "reports": [
            ("2025-04-01", "2027-03-01", "Site preparation ongoing."),
            ("2025-10-01", "2027-09-01", "Financing close delayed."),
            ("2026-04-01", "2028-03-01", "Request to extend export commencement deadline filed."),
        ],
        "contracts": [
            {"buyer": "KOGAS", "buyer_country": "KR", "mtpa": 1.0, "start_year": 2028, "term_years": 10},
        ],
        "uncontracted_mtpa": 5.0,
    },
]

for i, p in enumerate(projects):
    for rdate, exp_date, note in p["reports"]:
        rec = {
            "doc_type": "semi_annual_report",
            "project": p["project"],
            "docket": p["docket"],
            "terminal_location": p["terminal_location"],
            "report_date": rdate,
            "authorized_mtpa": p["authorized_mtpa"],
            "expected_operational_date": exp_date,
            "progress_note": note,
            "long_term_contracts": p["contracts"],
            "uncontracted_mtpa": p.get("uncontracted_mtpa"),
            "evidence": [
                {"page": 1, "text": f"[SAMPLE] {note}"},
                {"page": 2, "text": f"[SAMPLE] The facility is expected to be operational by {exp_date}."},
            ],
            "source_file": f"sample_{p['docket']}_{rdate}.pdf",
        }
        fname = STUDIO / f"{p['docket']}_{rdate}.json"
        fname.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

print("sample data written to", SAMPLE, "and", STUDIO)
