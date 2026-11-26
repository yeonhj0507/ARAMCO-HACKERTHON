# LNG 수급 에이전트 앱 (Flutter)

백엔드(`run.bat api`)를 먼저 띄운 뒤 실행합니다.

```powershell
cd app
flutter create . --platforms=windows,web --project-name lng_agent_app   # 처음 한 번
flutter pub get
flutter run -d windows        # 또는 -d chrome
```

백엔드 주소가 다르면 `--dart-define=API_BASE=http://주소:8000`.

기본 화면은 대화입니다. 말로 시키면 에이전트(Solar)가 도구를 골라 쓰고, 결과는 카드로 보입니다.
- PDF를 첨부하면 에이전트가 종류(A 반기 보고서, B 수급계획, C 실행안)를 판별해 Studio 워크플로우로 읽습니다.
- 도구 사용은 "Studio로 문서 읽기 · 42초" 한 줄로 접혀 있고, 누르면 단계와 원본 결과가 보입니다.
- 반영, 제외, 승인은 카드의 버튼으로 사람이 직접 합니다. 에이전트는 초안까지만 만듭니다.
- 왼쪽 "직접 보기"는 같은 일을 화면으로 하는 경로입니다 (확인할 일, 승인, 공급 전망, 문서 읽기, 계획 세우기).

글꼴: Pretendard (SIL Open Font License, fonts/LICENSE.txt)
