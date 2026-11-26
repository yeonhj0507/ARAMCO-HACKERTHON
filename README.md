# LNG 조달 다원화 에이전트

Aramco × 고려대학교 × Upstage AI Hackathon

미국 DOE에 제출된 LNG 수출 프로젝트 반기 보고서를 Upstage Studio로 판독해 신규 공급처 후보(가동 시점, 한국 계약, 미계약 물량)를 만들고,
2027~2031년 조달 최적화로 **어디서 얼마나 더 사고 비용은 얼마인지**를 계산합니다.
장기계약 80% 이상, 현물 20% 이하 원칙을 지키는지, 중동(호르무즈) 의존도가 얼마나 줄어드는지도 함께 봅니다.
앞 3개월 실행안은 Studio 검증 워크플로우가 검사하고, 승인은 사람이 합니다.

## 빠르게 실행 (Windows)

```bat
setup.bat              :: .venv 생성, 패키지 설치, 테스트, .env 파일 만들기
run.bat api            :: 백엔드 http://localhost:8000
```

```powershell
cd app
flutter pub get
flutter run -d windows
```

- 저장소에는 미국 프로젝트 53건의 판독 결과(`data/studio_params/`)와 수요 기준 자료(`data/reference/`)가 들어 있어서, **키 없이도 조달 최적화와 앱이 동작**합니다.
- `.env`에 `UPSTAGE_API_KEY`를 넣으면 채팅이 Solar로 답합니다. 키가 없으면 키워드로 도구를 고르는 오프라인 모드로 동작합니다.
- 새 보고서를 판독하거나 실행안을 검증하려면 `.env`에 Studio 에이전트 ID와 설정 번호가 필요합니다 (`.env.example` 참고).

## 구성

| 단계 | 하는 일 | 위치 |
|---|---|---|
| 보고서 판독 (Studio 워크플로우 A, 채점 대상) | DOE 반기 보고서 2건에서 docket, 단계, 가동 시점, 지연, 한국 계약, 미계약 물량, 반영 여부 | `lng/workflows.py`, `submission/` |
| 공급 전망 | 단계와 지연 이력으로 가동 확률 계산, 미계약 물량을 신규 계약 후보로 | `lng/supply.py` |
| 수요 | 제16차 장기 천연가스 수급계획 전망에 맞춘 월별 예측 (전산 기준 자료) | `lng/demand.py`, `data/reference/demand_plan.json` |
| 조달 최적화 | MILP. 신규 계약 규모, 현물 구매, 기지 하역과 재고, 장기 80% 원칙 | `lng/optimizer.py`, `lng/planner.py` |
| 실행안 검증 (Studio 워크플로우 C) | 앞 3개월 실행안 PDF의 계약 한도, 저장 용량, 안전재고, 합계 검사. 걸리면 재계획 | `lng/cycle.py`, `lng/execdoc.py` |
| 채팅 에이전트 | Solar tool calling, 결과는 카드로 표시, 승인과 반영은 사람이 버튼으로 | `lng/orchestrator.py`, `lng/tools.py`, `api/server.py` |
| 앱 | Flutter (Windows, 웹) | `app/` |

## 자주 쓰는 명령

```bat
run.bat eval-studio                 :: 제출 케이스 7건을 Studio로 돌려 정답지와 비교 (제출 점검 포함)
run.bat ingest-a                    :: data\a_cases의 보고서를 판독해 data\studio_params에 저장
run.bat review                      :: 사람 확인이 필요한 판독 결과
run.bat run-cycle --hormuz 3        :: 계획 수립, 실행안 검증, 승인 대기 초안
.venv\Scripts\python -m pytest -q tests
```

## 저장소에 없는 것

- `.env` (API 키, 에이전트 ID)
- `data/doe/` DOE 보고서 원본과 `data/a_cases/` 합본 케이스: 용량이 커서 뺐습니다. `scripts/make_a_cases.py`로 다시 만듭니다.
- 실행하면 생기는 결과물: `orders/`, `data/exec/`, Studio 원본 응답(`data/studio_raw*`), 평가 결과(`*/runs/`)

## 가정 (발표 때 밝힐 것)

- 한국이 미국 프로젝트 미계약 물량의 30%까지 계약할 수 있다고 봅니다.
- 신규 계약 단가 = 미국 장기계약 단가 + 60 $/t, 계약 물량의 90%는 take-or-pay.
- FID 전 프로젝트의 가동 시점 불확실성을 크게 둡니다 (tau 12개월 이상).
- 기존 장기계약은 2031년까지 유지된다고 봅니다.
- 장기계약이 모자라 80% 원칙을 못 지키는 해는 필요한 추가 물량만 보여줍니다. 그 공백을 메울 다른 공급처 자료는 아직 없습니다.
