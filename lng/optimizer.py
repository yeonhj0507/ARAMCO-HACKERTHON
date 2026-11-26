"""카고 단위 배분 MILP (PuLP + CBC).

결정변수
  N[s,m]    공급원 s의 m월 도착 카고 수 (정수, 1카고 = CARGO_KT)
  x[s,t,m]  그 물량 중 기지 t로 보내는 양 (kt, 연속). 카고 분할 하역을 허용하는 근사.
  I[t,m]    월말 재고 (kt)
  u[t,m]    공급 부족량 (kt)
  f[a,b,m]  주배관망으로 기지 a -> b 이송량 (kt)

목적 (사전식 2단계)
  1단계: 공급 부족량 합계 최소화
  2단계: 부족량을 1단계 값으로 묶고, 구매비 + 운송비 + 재고유지비 + 배관이송비 + 장기 80% 원칙 위반 벌점 최소화 (백만 달러)

단순화 가정 (발표 때 명시)
  - 카고는 선적한 달에 도착한다고 본다 (리드타임 무시).
  - 기지 간 배관 이송은 쌍별 월 상한만 둔다.
  - 제주는 배관 연결이 없고 대형 카고를 직접 받지 않는다. 통영에서 소형 내항선으로 받는다고 본다.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

import pandas as pd
import pulp

from .schemas import CARGO_KT

SHIP_COST_USD_T_PER_DAY = 1.2
HOLD_COST_USD_T_MONTH = 2.0
PIPE_COST_USD_T = 5.0
SHORTAGE_PENALTY_USD_T = 20000.0  # 공급 중단의 사회적 비용을 크게 둠 (가정). 2단계에서는 보조 역할만 한다
# 비용 단계 MIP 상대 갭. 5년 총비용이 17만 백만 달러 규모라 0.5%면 시나리오 간 차이(수백 백만 달러)가 갭에 묻힌다
MIP_GAP = 0.0002
SHORTAGE_TOL_KT = 1.0  # 2단계에서 1단계 최소 부족량보다 더 허용하는 양 (수치 오차 흡수)
PIPE_CAP_KT = 400.0
# 공급 안정성 원칙: 연간 조달의 80% 이상은 장기계약(안정), 단기(현물)는 20% 이하로 수익성을 노린다.
# 장기계약이 모자라 원칙을 못 지키는 만큼은 '안정성 부족' 물량으로 두고 벌점을 매긴다 (그 해에 더 필요한 장기계약 물량).
MIN_STABLE_SHARE = 0.80
STABILITY_PENALTY_USD_T = 400.0  # 원칙 위반 1톤당 위험 비용 (가정). 부족 벌점보다 작고 현물-장기 가격차보다 크게
SAFETY_RATIO = 0.15
END_INV_RATIO = 0.40
NO_PIPELINE = {"JEJU"}
COASTAL_LINKS = {("TONGYEONG", "JEJU"): (150.0, 15.0)}  # (월 상한 kt, 비용 $/t), 가정


def _solver(time_limit: int):
    """HiGHS(파이썬 안에서 실행, 외부 exe 없음)를 먼저 쓰고, 없으면 CBC. 환경변수 LNG_SOLVER=cbc로 강제 가능."""
    choice = os.getenv("LNG_SOLVER", "").lower()
    if choice != "cbc" and "HiGHS" in pulp.listSolvers(onlyAvailable=True):
        return pulp.HiGHS(msg=False, timeLimit=time_limit, gapRel=MIP_GAP)
    return pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, gapRel=MIP_GAP, threads=1)


def solver_name() -> str:
    return type(_solver(1)).__name__


@dataclass
class OptInputs:
    months: list[str]
    terminals: pd.DataFrame      # terminal, storage_kt, max_cargo_per_month, init_inv_ratio
    sources: pd.DataFrame        # source, price_usd_t, voyage_days, top_ratio
    avail: pd.DataFrame          # source, month, avail_kt
    demand: pd.DataFrame         # terminal, month, demand_kt
    min_stable_share: float = MIN_STABLE_SHARE  # 장기계약 최소 비중 (0이면 원칙을 적용하지 않음)


def solve(inp: OptInputs, time_limit: int = 30) -> dict:
    M, T = inp.months, list(inp.terminals["terminal"])
    S = list(inp.sources["source"])
    term = inp.terminals.set_index("terminal")
    src = inp.sources.set_index("source")
    avail = inp.avail.set_index(["source", "month"])["avail_kt"].to_dict()
    dem = inp.demand.set_index(["terminal", "month"])["demand_kt"].to_dict()
    pipe_pairs = [(a, b) for a in T for b in T if a != b and a not in NO_PIPELINE and b not in NO_PIPELINE]
    pipe_pairs += [pair for pair in COASTAL_LINKS if pair[0] in T and pair[1] in T]
    link_cap = {pair: COASTAL_LINKS.get(pair, (PIPE_CAP_KT, PIPE_COST_USD_T))[0] for pair in pipe_pairs}
    link_cost = {pair: COASTAL_LINKS.get(pair, (PIPE_CAP_KT, PIPE_COST_USD_T))[1] for pair in pipe_pairs}

    prob = pulp.LpProblem("lng_allocation", pulp.LpMinimize)
    N = pulp.LpVariable.dicts("N", (S, M), lowBound=0, cat="Integer")
    x = pulp.LpVariable.dicts("x", (S, T, M), lowBound=0)
    I = pulp.LpVariable.dicts("I", (T, M), lowBound=0)
    u = pulp.LpVariable.dicts("u", (T, M), lowBound=0)
    f = pulp.LpVariable.dicts("f", (range(len(pipe_pairs)), M), lowBound=0)

    def kt_cost(s):  # 백만 달러 / kt
        return (src.loc[s, "price_usd_t"] + SHIP_COST_USD_T_PER_DAY * src.loc[s, "voyage_days"]) / 1000.0

    prob += (
        pulp.lpSum(kt_cost(s) * x[s][t][m] for s in S for t in T for m in M)
        + pulp.lpSum(HOLD_COST_USD_T_MONTH / 1000.0 * I[t][m] for t in T for m in M)
        + pulp.lpSum(link_cost[pipe_pairs[k]] / 1000.0 * f[k][m] for k in range(len(pipe_pairs)) for m in M)
        + pulp.lpSum(SHORTAGE_PENALTY_USD_T / 1000.0 * u[t][m] for t in T for m in M)
    )

    # 장기(안정) 80% : 단기(현물) 20% 원칙. 단기 = short_term 열이 True인 공급원 (현물)
    alpha = float(inp.min_stable_share or 0.0)
    short = [s for s in S if "short_term" in src.columns and bool(src.loc[s, "short_term"])]
    gap = {}
    if 0 < alpha < 1 and short:
        for y in sorted({m[:4] for m in M}):
            ms = [m for m in M if m[:4] == y]
            st = pulp.lpSum(CARGO_KT * N[s][m] for s in short for m in ms)
            lt = pulp.lpSum(CARGO_KT * N[s][m] for s in S if s not in short for m in ms)
            gap[y] = pulp.LpVariable(f"stable_gap_{y}", lowBound=0)
            prob += st <= (1 - alpha) / alpha * lt + gap[y], f"stable_{y}"
        prob.setObjective(prob.objective + pulp.lpSum(STABILITY_PENALTY_USD_T / 1000.0 * g for g in gap.values()))

    # 신규 계약 후보: 계약 규모(최대치 대비 비율 0~1)를 같이 정한다. 계약하면 그만큼은 take-or-pay로 받아야 한다.
    cand = [s for s in S if "candidate" in src.columns and bool(src.loc[s, "candidate"])]
    C = {s: pulp.LpVariable(f"contract_{i}", 0, 1) for i, s in enumerate(cand)}
    years = sorted({m[:4] for m in M})
    for i, s in enumerate(S):
        # 월 상한은 카고 단위로 올림, 연간 합계는 계약 물량 이내 (연간 인도계획 ADP의 유연성을 흉내)
        for m in M:
            cap_cargo = math.ceil(avail.get((s, m), 0.0) / CARGO_KT - 1e-9)
            prob += N[s][m] <= cap_cargo, f"avail_{i}_{m}"
            prob += pulp.lpSum(x[s][t][m] for t in T) == CARGO_KT * N[s][m], f"split_{i}_{m}"
        for y in years:
            ms = [m for m in M if m[:4] == y]
            year_av = sum(avail.get((s, m), 0.0) for m in ms)
            if year_av <= 0:
                continue
            lifted = pulp.lpSum(CARGO_KT * N[s][m] for m in ms)
            ratio = src.loc[s, "top_ratio"]
            if s in C:
                prob += lifted <= C[s] * year_av + CARGO_KT / 2, f"annual_{i}_{y}"
                if ratio > 0:
                    prob += lifted >= ratio * year_av * C[s] - CARGO_KT, f"top_{i}_{y}"
            else:
                prob += lifted <= year_av + CARGO_KT / 2, f"annual_{i}_{y}"
                top = ratio * year_av - CARGO_KT  # 정수 카고 여유 1척
                if top > 0:
                    prob += lifted >= top, f"top_{i}_{y}"

    for k, pair in enumerate(pipe_pairs):
        for m in M:
            prob += f[k][m] <= link_cap[pair]

    for t in T:
        cap = term.loc[t, "storage_kt"]
        init = cap * term.loc[t, "init_inv_ratio"]
        for i, m in enumerate(M):
            prev = init if i == 0 else I[t][M[i - 1]]
            inflow = pulp.lpSum(f[k][m] for k, (a, b) in enumerate(pipe_pairs) if b == t)
            outflow = pulp.lpSum(f[k][m] for k, (a, b) in enumerate(pipe_pairs) if a == t)
            d = dem[(t, m)]
            prob += I[t][m] == prev + pulp.lpSum(x[s][t][m] for s in S) + inflow - outflow - (d - u[t][m]), f"bal_{t}_{m}"
            prob += u[t][m] <= d
            prob += I[t][m] <= cap
            prob += I[t][m] >= SAFETY_RATIO * cap
            prob += pulp.lpSum(x[s][t][m] for s in S) <= CARGO_KT * term.loc[t, "max_cargo_per_month"], f"berth_{t}_{m}"
        prob += I[t][M[-1]] >= END_INV_RATIO * cap

    # 사전식(lexicographic) 2단계 풀이
    #   1단계: 공급 부족량 합계만 최소화한다 (비용은 보지 않음).
    #   2단계: 부족량을 1단계 최솟값 이하로 묶어 두고, 비용(+ 안정성 원칙 벌점)을 최소화한다.
    # 한 번에 벌점을 섞어 풀면 상대 갭 0.5% 안에서 피할 수 있는 부족을 남긴 해를 받아들일 수 있어서 나눴다.
    cost_obj = prob.objective
    short_total = pulp.lpSum(u[t][m] for t in T for m in M)
    t0 = time.time()
    prob.setObjective(short_total)
    prob.solve(_solver(max(10, time_limit // 3)))
    min_short = pulp.value(short_total)
    if min_short is None:
        return {"status": pulp.LpStatus[prob.status]}
    prob += short_total <= min_short + SHORTAGE_TOL_KT, "lex_shortage"
    prob.setObjective(cost_obj)
    prob.solve(_solver(time_limit))
    solve_sec = round(time.time() - t0, 1)
    status = pulp.LpStatus[prob.status]
    if status not in ("Optimal", "Not Solved") or prob.objective.value() is None:
        return {"status": status}

    alloc = [
        {"source": s, "terminal": t, "month": m, "cargoes": round(x[s][t][m].value() / CARGO_KT, 2),
         "kt": round(x[s][t][m].value(), 1), "cost_musd": round(kt_cost(s) * x[s][t][m].value(), 2)}
        for s in S for t in T for m in M if (x[s][t][m].value() or 0) > 0.5
    ]
    inv = [{"terminal": t, "month": m, "inventory_kt": round(I[t][m].value(), 1),
            "shortage_kt": round(u[t][m].value(), 1), "demand_kt": round(dem[(t, m)], 1)} for t in T for m in M]
    pipes = [{"from": a, "to": b, "month": m, "kt": round(f[k][m].value(), 1)}
             for k, (a, b) in enumerate(pipe_pairs) for m in M if (f[k][m].value() or 0) > 0.5]
    alloc_df = pd.DataFrame(alloc)
    inv_df = pd.DataFrame(inv)
    return {
        "status": status,
        "contracts": {s: round(C[s].value() or 0.0, 3) for s in C},
        "stability_gap_kt": {y: round(g.value() or 0.0, 1) for y, g in gap.items()},
        "min_stable_share": alpha,
        "solve_seconds": solve_sec,
        "time_limited": solve_sec >= time_limit + max(10, time_limit // 3) - 0.5,  # True면 최적 보장 없이 시간 제한에서 멈춘 해
        "min_shortage_kt": round(min_short, 1),
        "objective_musd": round(prob.objective.value(), 1),
        # 부족 벌점과 안정성 원칙 벌점은 실제로 내는 돈이 아니라서 따로 둔다 (실제 비용 = objective - penalty)
        "penalty_musd": round(sum(SHORTAGE_PENALTY_USD_T / 1000.0 * (u[t][m].value() or 0) for t in T for m in M)
                              + sum(STABILITY_PENALTY_USD_T / 1000.0 * (g.value() or 0) for g in gap.values()), 1),
        "purchase_musd": round(alloc_df["cost_musd"].sum(), 1) if len(alloc_df) else 0.0,
        "shortage_kt": round(inv_df["shortage_kt"].sum(), 1),
        "allocation": alloc_df,
        "inventory": inv_df,
        "pipeline": pd.DataFrame(pipes),
    }
