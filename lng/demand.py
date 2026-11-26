"""수요 예측: 월별 공급 실적(용도별) -> Holt-Winters로 예측 -> 기지별로 나누기.

실데이터가 전국 합계라면 기지별 수요는 terminals.csv의 demand_share로 나눈다 (가정).
기지별 실적이 있으면 by_terminal=True 경로로 바꾸면 된다.
"""
from __future__ import annotations

import warnings

import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing


def forecast_national(history: pd.DataFrame, months: list[pd.Timestamp]) -> pd.DataFrame:
    """history: columns [month(YYYY-MM), use, supply_kt]"""
    out = []
    end = max(months)
    for use, g in history.groupby("use"):
        s = g.assign(month=pd.to_datetime(g["month"])).set_index("month")["supply_kt"].asfreq("MS")
        steps = (end.year - s.index[-1].year) * 12 + (end.month - s.index[-1].month)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(s, trend="add", seasonal="add", seasonal_periods=12).fit()
        fc = model.forecast(steps)
        for m in months:
            out.append({"use": use, "month": m.strftime("%Y-%m"), "demand_kt": float(max(0.0, fc.loc[m]))})
    return pd.DataFrame(out)


def split_by_terminal(national: pd.DataFrame, terminals: pd.DataFrame, multiplier: float = 1.0) -> pd.DataFrame:
    total = national.groupby("month", as_index=False)["demand_kt"].sum()
    rows = []
    for _, t in terminals.iterrows():
        for _, r in total.iterrows():
            rows.append({"terminal": t["terminal"], "month": r["month"], "demand_kt": r["demand_kt"] * t["demand_share"] * multiplier})
    return pd.DataFrame(rows)


# ---------- Studio 워크플로우 B (장기 수급계획) 반영 ----------
def _rows(rows: list[str]) -> dict[int, tuple[float, float, float]]:
    out = {}
    for r in rows or []:
        parts = [x.strip() for x in str(r).split(",")]
        if len(parts) >= 4 and parts[0].isdigit():
            out[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
    return out


def plan_annual_targets(plan: dict, years: list[int], kind: str = "base") -> dict[int, dict[str, float]]:
    """계획의 연간 수요(kt)를 연도별로. 표에 있는 연도 사이는 직선 보간, 범위 밖은 가장 가까운 연도 값."""
    anchors = _rows(plan.get(f"{kind}_demand_rows") or [])
    if not anchors:
        return {}
    ys = sorted(anchors)
    out = {}
    for y in years:
        if y <= ys[0]:
            c, p_, _ = anchors[ys[0]]
        elif y >= ys[-1]:
            c, p_, _ = anchors[ys[-1]]
        else:
            lo = max(a for a in ys if a <= y)
            hi = min(a for a in ys if a >= y)
            w = 0 if hi == lo else (y - lo) / (hi - lo)
            c = anchors[lo][0] + w * (anchors[hi][0] - anchors[lo][0])
            p_ = anchors[lo][1] + w * (anchors[hi][1] - anchors[lo][1])
        out[y] = {"city_gas": c, "power": p_}
    return out


def apply_plan(national: pd.DataFrame, plan: dict | None, kind: str = "base") -> tuple[pd.DataFrame, dict]:
    """월별 예측의 계절 모양은 두고, 연간 합계를 계획 수요에 맞춘다. 반환: (보정된 예측, 연도별 배율)."""
    if not plan:
        return national, {}
    df = national.copy()
    df["year"] = df["month"].str[:4].astype(int)
    targets = plan_annual_targets(plan, sorted(df["year"].unique()), kind)
    factors = {}
    for (use, y), g in df.groupby(["use", "year"]):
        if y not in targets or use not in targets[y]:
            continue
        annualized = g["demand_kt"].mean() * 12
        if annualized <= 0:
            continue
        f = targets[y][use] / annualized
        factors[f"{use}_{y}"] = round(f, 3)
        df.loc[g.index, "demand_kt"] = g["demand_kt"] * f
    return df.drop(columns="year"), factors


def apply_terminal_plan(terminals: pd.DataFrame, plan: dict | None) -> tuple[pd.DataFrame, list[str]]:
    """가스공사 기지 저장용량을 계획의 운영 용량(kt)으로 바꾼다. 건설 예정분과 민간 기지는 넣지 않는다."""
    if not plan:
        return terminals, []
    t = terminals.copy()
    changed = []
    for r in plan.get("terminal_rows") or []:
        parts = [x.strip() for x in str(r).split(",")]
        if len(parts) < 4 or parts[1] != "KOGAS":
            continue
        code, op_kt = parts[0], float(parts[2] or 0)
        if op_kt > 0 and code in set(t["terminal"]):
            old = float(t.loc[t.terminal == code, "storage_kt"].iloc[0])
            t.loc[t.terminal == code, "storage_kt"] = op_kt
            changed.append(f"{code} {old:.0f}->{op_kt:.0f}kt")
    return t, changed
