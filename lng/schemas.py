"""Upstage Studio Extract 노드에 넣을 필드 스키마.

Studio에서 Extract 에이전트를 만들 때 아래 EXTRACT_SCHEMA의 필드를 그대로 등록하면 된다.
Classify 노드는 DOC_TYPES 중 하나로 분류하도록 설정한다.
"""

DOC_TYPES = [
    "application",          # 수출 허가 신청서
    "order",                # 허가 명령서
    "semi_annual_report",   # 반기 보고서 (핵심)
    "amendment_request",    # 기한 연장, 지배구조 변경 등 정정 신청
    "other",
]

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": DOC_TYPES, "description": "문서 종류"},
        "project": {"type": "string", "description": "LNG 프로젝트 또는 허가 보유자 이름"},
        "docket": {"type": "string", "description": "DOE 도켓 번호 (예: 10-161-LNG)"},
        "terminal_location": {"type": "string", "description": "터미널 위치 (주 단위)"},
        "report_date": {"type": "string", "format": "date", "description": "문서 작성 또는 제출일"},
        "authorized_mtpa": {"type": "number", "description": "허가 수출 물량, MTPA로 환산"},
        "expected_operational_date": {"type": "string", "format": "date", "description": "설비 가동 예정일"},
        "progress_note": {"type": "string", "description": "건설 및 가동 진행 상황 요약 한 줄"},
        "long_term_contracts": {
            "type": "array",
            "description": "장기 수출 계약 목록",
            "items": {
                "type": "object",
                "properties": {
                    "buyer": {"type": "string"},
                    "buyer_country": {"type": "string", "description": "ISO 2자리 국가코드"},
                    "mtpa": {"type": "number"},
                    "start_year": {"type": "integer"},
                    "term_years": {"type": "integer"},
                },
            },
        },
        "uncontracted_mtpa": {"type": "number", "description": "아직 계약되지 않은 물량 (명시된 경우만)"},
        "evidence": {
            "type": "array",
            "description": "각 필드의 근거가 된 원문 문장과 페이지",
            "items": {"type": "object", "properties": {"page": {"type": "integer"}, "text": {"type": "string"}}},
        },
    },
    "required": ["doc_type", "project", "report_date"],
}

# 1 MTPA를 kt/월로 바꾸는 계수
MTPA_TO_KT_PER_MONTH = 1000.0 / 12.0
CARGO_KT = 70.0  # 표준 카고 1척 물량 가정 (약 7만톤)
