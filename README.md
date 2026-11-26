# LNG 공급망 배분 에이전트 (해커톤 MVP)

DOE LNG 수출 서류를 Upstage Studio로 추출해서 미국산 공급을 예측하고, 수요를 예측한 뒤,
MILP로 공급원별, 기지별, 월별 배분을 정하고, 구매 요청서 초안과 근거 보고서까지 만든다.
Solar Pro 채팅으로 조사, 분석, 명령을 할 수 있다.

> 지금 들어 있는 데이터는 전부 **샘플**이다. 구조 테스트용이라 실제 값이 아니다.

## Windows에서 처음 세팅

```bat
setup.bat                 :: .venv 생성, 패키지 설치, 샘플 데이터, 테스트까지
run.bat demo
run.bat chat --offline
run.bat chat              :: .env에 UPSTAGE_API_KEY, UPSTAGE_MODEL 넣은 뒤
run.bat ingest docs\doe   :: .env에 UPSTAGE_STUDIO_AGENT_ID 넣은 뒤, 폴더 안 PDF를 Studio로 처리
```

VS Code로 폴더를 열면 `.venv` 인터프리터와 `.env`를 자동으로 잡는다.

## 실행 (직접)

```bash
pip install -r requirements.txt
python scripts/make_sample_data.py      # 샘플 데이터 다시 만들기
python main.py demo                     # 기본 vs 호르무즈 시나리오 비교
python main.py chat --offline           # 키 없이 도구 호출 체험
export UPSTAGE_API_KEY=...              # Console에서 발급
export UPSTAGE_MODEL=...                # Console Models 페이지에서 tool calling 지원 모델 확인
python main.py chat                     # Solar 오케스트레이터
python main.py approve <order_id> --approver 이름   # 사람만 승인
python -m pytest -q tests               # 최적해 제약 검증
```

## 구조

```
lng/
  schemas.py        Studio Extract 필드 스키마 (Studio 화면에 그대로 등록)
  studio_client.py  Studio 결과 JSON 로더, 근거 문장 검색, API 연동 자리(TODO)
  supply.py         반기 보고서 가동일 지연 이력 -> 가동 확률 -> 한국향 월별 가용 물량
  demand.py         Holt-Winters 수요 예측, 기지별 분할
  optimizer.py      MILP (PuLP + CBC)
  planner.py        시나리오 -> 공급/수요 -> 최적화 한 번에
  tools.py          채팅 도구 (조사, 분석, 명령 초안). 승인 함수는 LLM에 노출 안 함
  report.py         승인용 근거 보고서 마크다운
  orchestrator.py   Solar tool calling 루프, 오프라인 키워드 라우터
data/sample/        기지, 공급원, 수요 이력 (샘플)
data/studio_output/ Studio Extract 결과 (샘플)
orders/             생성된 지시서, 보고서 (실행 시 생김)
```

## 실데이터로 바꿀 곳

| 파일 | 실데이터 출처 |
|---|---|
| data/studio_output/*.json | DOE 반기 보고서를 Studio Classify -> Extract로 처리한 결과 |
| data/sample/demand_history.csv | 공공데이터포털 한국가스공사 생산기지 용도별 월 공급량 |
| data/sample/terminals.csv | 16차 장기 천연가스 수급계획 별첨 인프라 현황 |
| data/sample/sources.csv | 가스공사 도입계약 공개 보도, 국가별 수입단가 |

Studio 쪽 순서
1. Studio에서 에이전트 생성: Parse -> Classify(`schemas.DOC_TYPES`) -> Extract(`schemas.EXTRACT_SCHEMA`)
2. DOE PDF 몇 건으로 테스트하고 결과 JSON을 `data/studio_output/`에 저장
3. 결과 키 이름이 다르면 `studio_client.normalize_record()`만 고친다
4. API로 돌릴 때는 `.env`에 `UPSTAGE_STUDIO_AGENT_ID`(agt_...)를 넣고 `run.bat ingest <PDF 또는 폴더>`
   원본 응답은 `data/studio_raw/`, 변환 결과는 `data/studio_output/`에 저장된다

## 모델 가정 (발표 때 명시)

- 카고는 도착월 기준, 리드타임은 무시
- 공급원-월 단위로 카고 수는 정수, 기지 간에는 분할 하역 허용 (계산 속도 때문)
- 장기계약 연간 물량 안에서 월별 유연성 허용, take-or-pay 하한 적용
- 호르무즈 경유 물량은 차단 개월 동안 0, take-or-pay도 그만큼 줄어듦 (불가항력 가정)
- 기지 간 주배관 이송 쌍별 월 400kt 상한, 제주는 통영에서 내항선으로만 공급
- 공급 부족 페널티 20,000 $/t (공급 중단 비용을 크게 둠)
- 미국 프로젝트 가동 시점 = 최신 예정일 + 지수분포 지연, 평균은 과거 지연 이력으로 추정
- 미국 미계약 물량 중 30%를 한국이 협상으로 확보 가능, 단가 +60 $/t
