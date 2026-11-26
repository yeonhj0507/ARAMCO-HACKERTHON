"""Solar Pro 채팅 오케스트레이터 (OpenAI SDK 호환 tool calling).

환경변수
  UPSTAGE_API_KEY   필수
  UPSTAGE_BASE_URL  기본 https://api.upstage.ai/v1
  UPSTAGE_MODEL     기본 solar-pro-4 (Console Getting Started 예제 기준)
"""
from __future__ import annotations

import json
import time
import os

from .tools import REGISTRY, TOOL_SPECS

SYSTEM_PROMPT = """너는 한국 LNG 조달 담당자와 채팅으로 일하는 공급망 에이전트다. 핵심 질문은 "어디서 얼마나 더 사고, 비용은 얼마인가"와
"중동(호르무즈)과 현물에 덜 기대도록 공급처를 어떻게 다원화할까"다. 담당자는 화면을 찾아다니지 않고 너에게 말로 일을 시킨다.

할 수 있는 일
- 현황 요약: get_overview (수요는 제16차 수급계획 전산 자료, 미국 공급은 보고서 판독 결과)
- 미국 프로젝트 보고서 읽기: read_document (A). 가동 시점, 한국 계약, 미계약 물량을 뽑아 신규 계약 후보로 만든다.
  C는 배분 실행안 검사다. 파일 이름만 들으면 list_documents로 경로를 찾는다. 첨부하면 메시지 끝에 [첨부: 경로]가 붙는다.
- 보고서 판독에서 사람 확인으로 넘긴 프로젝트: list_reviews
- 미국 프로젝트 가동 전망: get_supply_outlook
- 조달 최적화 (2027~2031): run_scenario. 어디서 얼마나, 비용, 신규 계약 후보별 권장 물량과 절감액, 중동 의존도와 HHI,
  신규 계약 없이 조달했을 때와의 비교(diversification_effect)가 나온다. 몇 초 걸린다.
- 실제 계획 (최적화, 앞 3개월 실행안, 검증 시스템 검사, 재계획, 승인 대기 초안): make_plan. 1~3분 걸린다.
- 계획의 기지별 배분: get_plan_detail, 계획 초안과 승인 대기: list_orders

규칙
1. 물량, 비용, 비율 같은 숫자는 도구 결과에서 그대로 인용한다. 직접 계산하거나 추정하지 않는다.
2. 도구 결과는 화면에 카드로 같이 보인다. 표를 다시 나열하지 말고 핵심과 다음 할 일을 2~4문장으로 말한다.
   조달 질문에는 (1) 어느 프로젝트와 언제부터 몇 MTPA 계약을 권하는지 (2) 신규 계약 효과(절감액, 현물 감소) (3) 남는 위험을 말한다.
3. 반영, 제외, 승인은 사람이 카드의 버튼으로 한다. 너는 승인하거나 반영했다고 말하지 않는다.
4. 비용이나 조달 구성을 물으면 run_scenario, 계획이나 지시서를 만들라고 하면 make_plan을 쓴다.
5. 판독이나 검증 결과가 검토 필요나 재계획 필요라고 하면 reason을 짧게 풀어 말한다. 부족(shortage)이 있는데 승인 요청이면
   현물까지 최대로 사도 못 채우는 양이라 재계획으로는 줄지 않는다는 점과 부족한 달을 말한다.
6. 도구 결과에 _목록_요약이 있으면 목록 일부만 넘긴 것이다. "데이터가 잘렸다"고 하지 말고 합계로 답한다.
7. 신규 계약 후보의 가동 확률(p_by_year)이 낮으면(FID 전 등) 일정 위험을 같이 말한다.
8. 조달 원칙은 "연간 조달의 80% 이상 장기계약(안정성), 20% 이하 현물(수익성)"이다. stability_rule.met이 false면
   어느 해에 장기계약이 얼마나(kt, MTPA) 더 필요한지 말하고, 미국 신규 계약이 그 해에 아직 가동 전이면 그 점을 짚는다.
   그 공백을 메울 다른 장기 공급처는 지금 데이터에 없으니 "추가 공급처 자료가 필요하다"고 말하고, 없는 공급처를 지어내지 않는다.
9. 시키지 않은 긴 작업(make_plan, 여러 문서 읽기)은 먼저 하지 말고 제안만 한다.
10. 사용자에게는 내부 이름(Studio A, Studio C, 워크플로우, 코드 검산)을 쓰지 않는다. "보고서 판독", "검증 시스템", "교차 검산"이라고 말한다.
답은 한국어 존댓말로 짧게 한다."""


LLM_LIMIT = 9000  # 도구 결과 한 건을 모델에 넘길 때 최대 글자 수


def _dump(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str, separators=(",", ":"))


def for_llm(result) -> str:
    """도구 결과를 모델에 넘길 JSON으로. 길면 가장 긴 목록부터 앞쪽만 남기고, 몇 개 중 몇 개인지 적는다.
    JSON을 중간에서 자르지 않는다 (잘린 JSON을 보면 모델이 데이터가 잘렸다고 답한다)."""
    import copy

    txt = _dump(result)
    if len(txt) <= LLM_LIMIT or not isinstance(result, dict):
        return txt if len(txt) <= LLM_LIMIT else txt[:LLM_LIMIT]
    r = copy.deepcopy(result)
    notes = {}
    for _ in range(30):
        lists = [(k, v) for k, v in r.items() if isinstance(v, list) and len(v) > 3]
        if not lists or len(_dump(r)) <= LLM_LIMIT:
            break
        k, v = max(lists, key=lambda kv: len(_dump(kv[1])))
        total = notes.get(k, (len(v), 0))[0]
        keep = max(3, int(len(v) * 0.7))
        r[k] = v[:keep]
        notes[k] = (total, keep)
    if notes:
        r["_목록_요약"] = {k: f"전체 {t}개 중 앞 {n}개만 넘김 (정렬 순서 기준). 합계와 개수는 summary를 쓴다"
                         for k, (t, n) in notes.items()}
    txt = _dump(r)
    return txt if len(txt) <= LLM_LIMIT else txt[:LLM_LIMIT]


class Orchestrator:
    def __init__(self, model: str | None = None, max_steps: int = 6):
        from openai import OpenAI

        key = os.getenv("UPSTAGE_API_KEY")
        if not key:
            raise RuntimeError("UPSTAGE_API_KEY가 없습니다. 키 없이 보려면 main.py chat --offline을 쓰세요.")
        self.client = OpenAI(api_key=key, base_url=os.getenv("UPSTAGE_BASE_URL") or "https://api.upstage.ai/v1")
        self.model = model or os.getenv("UPSTAGE_MODEL") or "solar-pro-4"
        self.max_steps = max_steps
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def ask(self, text: str, on_tool=None, on_result=None) -> str:
        """on_tool(name, args): 도구 호출 직전, on_result(name, args, result, seconds): 호출 직후."""
        self.messages.append({"role": "user", "content": text})
        for _ in range(self.max_steps):
            resp = self.client.chat.completions.create(model=self.model, messages=self.messages, tools=TOOL_SPECS)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                self.messages.append({"role": "assistant", "content": msg.content})
                return msg.content
            self.messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                if on_tool:
                    on_tool(call.function.name, args)
                t0 = time.time()
                try:
                    result = REGISTRY[call.function.name](**args)
                except Exception as e:  # 도구 오류는 모델에게 그대로 알려준다
                    result = {"error": str(e)}
                if on_result:
                    on_result(call.function.name, args, result, round(time.time() - t0, 1))
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": for_llm(result)})
        return "도구 호출 단계가 너무 길어져서 멈췄습니다. 질문을 나눠서 다시 해주세요."


def offline_route(text: str) -> tuple[str, dict]:
    """Solar 없이 데모할 때 쓰는 단순한 키워드 라우터."""
    import re

    nums = [int(x) for x in re.findall(r"(\d+)\s*개월", text)]
    att = re.search(r"\[첨부:\s*([^\]]+)\]", text)
    if att:
        return "read_document", {"path": att.group(1).strip()}
    hormuz = {"hormuz_blocked_months": nums[0] if nums else 3} if any(k in text for k in ("호르무즈", "카타르", "봉쇄")) else {}
    if any(k in text for k in ("계획 세워", "계획을 세워", "지시서", "구매 요청", "실행안 만들")):
        return "make_plan", hormuz
    if any(k in text for k in ("비용", "얼마나", "조달", "다원화", "어디서")) or hormuz:
        extra = {"allow_new_contracts": False} if "신규 계약 없이" in text or "현물로만" in text else {}
        return "run_scenario", {"name": f"hormuz_{hormuz.get('hormuz_blocked_months', 0)}m", **hormuz, **extra}
    if "현황" in text:
        return "get_overview", {}
    if any(k in text for k in ("확인할", "검토")):
        return "list_reviews", {}
    if "승인" in text or "초안" in text:
        return "list_orders", {}
    if any(k in text for k in ("문서", "파일", "보고서")):
        return "list_documents", {}
    if "수요" in text:
        return "forecast_demand", {}
    return "get_supply_outlook", {}
