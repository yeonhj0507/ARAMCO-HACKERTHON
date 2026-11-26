"""공급 예측: Studio로 뽑은 DOE 반기 보고서 레코드 -> 공급원별 월 가용 물량.

아이디어
  - 같은 프로젝트의 보고서를 시간순으로 놓고 '가동 예정일'이 몇 번, 몇 개월 밀렸는지 본다.
  - 과거 지연 패턴으로 '남은 지연'의 평균 tau(개월)를 잡고,
    가동 시점이 최신 예정일 + 지수분포 지연을 따른다고 본다.
      P(m월까지 가동) = 1 - exp(-(m - 최신예정월 + 1) / tau),  m >= 최신예정월
  - 한국 구매자(buyer_country == KR) 계약 물량 x 가동확률 = 미국산 장기계약 기대 물량
  - 미계약 물량 x 한국 확보 가능 비율 = 추가 협상 후보 물량
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .schemas import MTPA_TO_KT_PER_MONTH

# 구매자 이름으로 한국 기업 판별 (Studio가 국가를 못 채우는 경우가 많음)
KR_BUYERS = re.compile(r"\bKOGAS\b|korea\s+gas|\bSK\s*(gas|e&s|energy|innovation|earthon)|\bGS\s*(energy|caltex|e&r)|posco|hanwha|"
                       r"\bE1\b|\bKEPCO\b|korea\s+(south|east|west|southern|western|midland)|hyundai|samsung\s*c&t|\bLX\s+international", re.I)
KR_SHARE_OF_UNCONTRACTED = 0.3  # 미계약 물량 중 한국이 협상으로 확보할 수 있다고 보는 비율 (가정)


def _month_index(ts: pd.Timestamp) -> int:
    return ts.year * 12 + ts.month - 1


_SECURED = re.compile(r"([\d.]+)\s*MTPA[^.,;]{0,12}(확보|secured|contracted|under contract)", re.I)
# 날짜가 없을 때 단계별 '마지막 보고일로부터 가동까지 개월 수'와 지연 불확실성(tau) 가정
STAGE_DEFAULT_MONTHS = {"commissioning": (6, 3.0), "construction": (30, 9.0)}
# 날짜가 적혀 있어도 단계별로 최소한의 일정 불확실성(tau)을 둔다. FID 전 프로젝트의 목표일은 특히 자주 밀린다 (가정)
STAGE_MIN_TAU = {"pre_fid": 12.0, "construction": 3.0}
PROFILE_COLUMNS = ["project", "docket", "reports", "dated_reports", "slip_count", "total_slip_months", "tau_months",
                   "stage", "base_operating", "first_lng_date", "latest_expected", "date_source", "operating", "contracts", "contracted_mtpa", "kr_contracts", "kr_mtpa",
                   "uncontracted_mtpa"]


def _docket_key(d: str | None) -> str | None:
    """'12-88-LNG, 12-156-LNG'와 '12-88-LNG'처럼 표기가 달라도 같은 프로젝트로 묶이게 첫 도켓 번호만 쓴다."""
    m = re.search(r"\d{2}-\d{1,3}-(LNG|CNG)", d or "", re.I)
    return m.group(0).upper() if m else None


def is_korean_buyer(c: dict) -> bool:
    return c.get("buyer_country") == "KR" or bool(KR_BUYERS.search(c.get("buyer") or ""))


def cumulative_contracts(reps: list[dict]) -> list[dict]:
    """반기 보고서는 보통 '이번 기간에 새로 맺은 계약'만 적는다. 그래서 보고서 전체를 합쳐 구매자별로 본다.

    같은 구매자가 여러 보고서에 나오면 물량이 가장 큰 값을 쓴다 (중복 언급을 두 번 세지 않도록).
    """
    by_buyer: dict[str, dict] = {}
    for r in reps:
        for c in r.get("long_term_contracts", []) or []:
            key = re.sub(r"[^a-z0-9]", "", (c.get("buyer") or "").lower())
            if not key:
                continue
            cur = by_buyer.get(key)
            if cur is None or (c.get("mtpa") or 0) > (cur.get("mtpa") or 0):
                merged = dict(cur or {})
                merged.update({k: v for k, v in c.items() if v not in (None, "")})
                merged["first_seen"] = (cur or {}).get("first_seen") or r.get("report_date")
                by_buyer[key] = merged
    return list(by_buyer.values())


def _uncontracted(last: dict, contracted: float) -> float:
    """미계약 물량. 추출값이 있으면 그대로, 비었거나 0이면 문장에 '확보한 물량'이 적힌 경우에만 '허가 - 확보'로 계산한다.

    DOE 허가 물량은 실제 설비 용량보다 큰 경우가 많아서, 확보 물량이 명시되지 않으면 계산하지 않는다 (과대추정 방지).
    """
    val = last.get("uncontracted_mtpa")
    auth = last.get("authorized_mtpa")
    if val:
        return float(val)
    m = _SECURED.search(last.get("progress_note") or "")
    if not (auth and m):
        return 0.0
    return max(0.0, float(auth) - float(m.group(1)))


def project_profiles(records: list[dict], extra_delay_months: int = 0) -> pd.DataFrame:
    """프로젝트별 지연 이력, 남은 지연 평균(tau), 누적 계약을 계산한다.

    가동 예정일이 적힌 보고서끼리만 지연을 비교한다. 초기 보고서(FID 전)는 날짜가 없는 경우가 많다.
    """
    by_proj = defaultdict(list)
    for r in records:
        if r.get("doc_type") == "semi_annual_report" and r.get("report_date"):
            by_proj[r.get("source_folder") or _docket_key(r.get("docket")) or r.get("project")].append(r)

    rows = []
    for key, reps in by_proj.items():
        reps.sort(key=lambda r: r["report_date"])
        dated = [r for r in reps if r.get("expected_operational_date")]
        exp_dates = [pd.Timestamp(r["expected_operational_date"]) for r in dated]
        slips = [_month_index(b) - _month_index(a) for a, b in zip(exp_dates, exp_dates[1:])]
        pos = [x for x in slips if x > 0]
        slip_ratio = len(pos) / max(1, len(slips))
        mean_slip = sum(pos) / len(pos) if pos else 0.0
        tau = 0.5 + mean_slip * slip_ratio
        if dated and dated[-1].get("expected_operational_date_inferred"):
            tau = max(tau, 6.0)  # 문장에서 연도만 추정한 경우는 불확실성을 크게 둔다

        last = reps[-1]
        stage = next((r.get("stage") for r in reversed(reps) if r.get("stage")), None)
        first_lng = next((r.get("first_lng_date") for r in reversed(reps) if r.get("first_lng_date")), None)
        contracts = cumulative_contracts(reps)
        contracted = sum(c.get("mtpa") or 0 for c in contracts)
        kr = [c for c in contracts if is_korean_buyer(c)]
        base_operating = any(r.get("base_operating") for r in reps)
        date_source = "reported"
        if first_lng:  # 실제로 첫 LNG를 생산했으면 가동 중
            latest_exp, operating, date_source = pd.Timestamp(first_lng), extra_delay_months == 0, "first_lng"
        elif base_operating:  # 본 설비는 이미 가동 중 (보고서는 확장 공사 얘기를 주로 함)
            latest_exp, operating, date_source = pd.Timestamp(reps[0]["report_date"]), True, "base_operating"
        elif exp_dates:
            latest_exp = exp_dates[-1]
            operating = exp_dates[-1] <= pd.Timestamp(dated[-1]["report_date"])
            date_source = "inferred" if dated[-1].get("expected_operational_date_inferred") else "reported"
        elif stage in STAGE_DEFAULT_MONTHS:  # 날짜가 없으면 단계별 기본 소요기간으로 대략 잡는다
            months, stage_tau = STAGE_DEFAULT_MONTHS[stage]
            tau = max(tau, stage_tau)
            latest_exp = pd.Timestamp(last["report_date"]) + pd.DateOffset(months=months)
            operating, date_source = False, f"stage:{stage}"
        else:
            latest_exp, operating, date_source = None, False, "none"  # 계획 기간 안에는 공급 없다고 본다
        if latest_exp is not None and not operating:
            latest_exp = latest_exp + pd.DateOffset(months=extra_delay_months)
        latest_str = latest_exp.strftime("%Y-%m") if latest_exp is not None else None
        rows.append({
            "project": last.get("project"),
            "docket": last.get("docket"),
            "reports": len(reps),
            "dated_reports": len(dated),
            "slip_count": len(pos),
            "total_slip_months": sum(pos),
            "tau_months": round(tau, 2),
            "stage": stage,
            "base_operating": base_operating,
            "first_lng_date": first_lng,
            "latest_expected": latest_str,
            "date_source": date_source,
            "operating": operating,
            "contracts": len(contracts),
            "contracted_mtpa": round(contracted, 2),
            "kr_contracts": kr,
            "kr_mtpa": sum(c.get("mtpa") or 0 for c in kr),
            "uncontracted_mtpa": round(_uncontracted(last, contracted), 2),
        })
    return pd.DataFrame(rows, columns=PROFILE_COLUMNS, dtype=object)  # 빈 값을 None으로 유지 (pandas 3)


def _missing(v) -> bool:
    """None, NaN, pd.NA, 빈 문자열. pandas 3은 빈 문자열 칸을 None이 아니라 NaN으로 담는다."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def prob_operational(profile: pd.Series, month: pd.Timestamp) -> float:
    if bool(profile["operating"]) and not _missing(profile["operating"]):
        return 1.0
    if _missing(profile["latest_expected"]):
        return 0.0
    delta = _month_index(month) - _month_index(pd.Timestamp(profile["latest_expected"]))
    if delta < 0:
        return 0.0
    return 1.0 - math.exp(-(delta + 1) / profile["tau_months"])


def _contract_active(c: dict, month: pd.Timestamp) -> bool:
    start = c.get("start_year") or 0
    term = c.get("term_years") or 99
    return start <= month.year < start + term


def us_supply_forecast(records: list[dict], months: list[pd.Timestamp], extra_delay_months: int = 0):
    """US_LT(한국 장기계약 기대 물량)와 US_UNCONTRACTED(협상 후보 물량)의 월별 kt를 돌려준다."""
    prof = project_profiles(records, extra_delay_months)
    return _forecast_from_profiles(prof, months)


def _forecast_from_profiles(prof: pd.DataFrame, months: list[pd.Timestamp]):
    rows, detail = [], []
    for m in months:
        lt, unc = 0.0, 0.0
        for _, p in prof.iterrows():
            prob = prob_operational(p, m)
            kr = sum(c["mtpa"] for c in p["kr_contracts"] if _contract_active(c, m))
            lt += kr * MTPA_TO_KT_PER_MONTH * prob
            unc += p["uncontracted_mtpa"] * KR_SHARE_OF_UNCONTRACTED * MTPA_TO_KT_PER_MONTH * prob
            detail.append({"project": p["project"], "month": m.strftime("%Y-%m"), "p_operational": round(prob, 3)})
        rows.append({"source": "US_LT", "month": m.strftime("%Y-%m"), "avail_kt": lt})
        rows.append({"source": "US_UNCONTRACTED", "month": m.strftime("%Y-%m"), "avail_kt": unc})
    return pd.DataFrame(rows), prof, pd.DataFrame(detail)


# ---------- Studio 워크플로우 A 파라미터 경로 ----------
# A가 프로젝트별로 내는 값: docket, stage, operating, online_month, slip_months, kr_buyers, kr_mtpa,
# uncontracted_mtpa, config_status. 위의 보고서 레코드 경로(project_profiles)와 같은 열을 만들어
# prob_operational, us_supply_forecast 계산을 그대로 쓴다.
REFERENCE_CONTRACTS = Path(__file__).resolve().parents[1] / "data" / "reference" / "kr_contracts.csv"


def _reference_contracts() -> dict[str, list[dict]]:
    """보고서에 물량이 안 적힌 한국 계약을 담당자가 공개 자료로 채워 넣는 표 (case_key 기준)."""
    if not REFERENCE_CONTRACTS.exists():
        return {}
    ref = pd.read_csv(REFERENCE_CONTRACTS).fillna("")
    out: dict[str, list[dict]] = defaultdict(list)
    for _, r in ref.iterrows():
        if not r.get("case_key") or not r.get("mtpa"):
            continue
        out[str(r["case_key"])].append({"buyer": r["buyer"], "buyer_country": "KR", "mtpa": float(r["mtpa"]),
                                        "start_year": int(r["start_year"]) if str(r.get("start_year", "")).strip() else 0,
                                        "term_years": int(r["term_years"]) if str(r.get("term_years", "")).strip() else 99,
                                        "source": r.get("source", "")})
    return out


def profiles_from_params(params: list[dict], extra_delay_months: int = 0, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    as_of = (as_of or pd.Timestamp.today()).to_period("M").to_timestamp()
    refs = _reference_contracts()
    rows = []
    for p in params:
        stage = p.get("stage")
        operating = bool(p.get("operating"))
        slip = int(p.get("slip_months") or 0)
        tau = 0.5 + max(slip, 0)
        online = (p.get("online_month") or "").strip()
        date_source = "studio"
        if online:
            latest = pd.Timestamp(online + "-01")
        elif not p.get("operating") and stage in STAGE_DEFAULT_MONTHS:
            months, stage_tau = STAGE_DEFAULT_MONTHS[stage]
            latest, tau, date_source = as_of + pd.DateOffset(months=months), max(tau, stage_tau), f"stage:{stage}"
        else:
            latest, date_source = None, "none"
        if latest is not None and not operating:
            latest = latest + pd.DateOffset(months=extra_delay_months)
            tau = max(tau, STAGE_MIN_TAU.get(stage, 0.0))
        kr = []
        if float(p.get("kr_mtpa") or 0) > 0:
            kr.append({"buyer": ", ".join(p.get("kr_buyers") or []) or "KR buyer", "buyer_country": "KR",
                       "mtpa": float(p["kr_mtpa"]), "start_year": 0, "term_years": 99, "source": "studio"})
        kr += refs.get(p.get("case_key", ""), [])
        rows.append({
            "project": p.get("case_key"), "docket": p.get("docket"), "reports": 2, "dated_reports": 2 if online else 0,
            "slip_count": 1 if slip > 0 else 0, "total_slip_months": max(slip, 0), "tau_months": round(tau, 2),
            "stage": stage, "base_operating": False, "first_lng_date": online if p.get("operating") else None,
            "latest_expected": latest.strftime("%Y-%m") if latest is not None else None, "date_source": date_source,
            "operating": bool(p.get("operating")), "contracts": len(kr), "contracted_mtpa": sum(c["mtpa"] for c in kr),
            "kr_contracts": kr, "kr_mtpa": sum(c["mtpa"] for c in kr),
            "uncontracted_mtpa": float(p.get("uncontracted_mtpa") or 0),
        })
    return pd.DataFrame(rows, columns=PROFILE_COLUMNS, dtype=object)  # 빈 값을 None으로 유지 (pandas 3)


def us_supply_from_params(params: list[dict], months: list[pd.Timestamp], extra_delay_months: int = 0):
    prof = profiles_from_params(params, extra_delay_months)
    return _forecast_from_profiles(prof, months)


# ---------- 신규 조달 후보 (워크플로우 A의 미계약 물량) ----------
NEW_US_PREFIX = "US_NEW_"


def us_candidates(prof: pd.DataFrame, months: list[pd.Timestamp], min_prob: float = 0.05):
    """미계약 물량이 있는 미국 프로젝트를 하나씩 신규 계약 후보로 만든다.
    반환: (월별 최대 공급 가능량 kt 표, 후보 정보 목록). 최대량 = 미계약 x 한국 확보 가능 비율 x 가동 확률."""
    rows, meta = [], []
    for _, p in prof.iterrows():
        unc = float(p["uncontracted_mtpa"] or 0)
        if unc <= 0:
            continue
        probs = [prob_operational(p, m) for m in months]
        if max(probs) < min_prob:
            continue
        cap = round(unc * KR_SHARE_OF_UNCONTRACTED, 2)
        src = NEW_US_PREFIX + str(p["project"])
        for m, pr in zip(months, probs):
            rows.append({"source": src, "month": m.strftime("%Y-%m"), "avail_kt": cap * MTPA_TO_KT_PER_MONTH * pr})
        meta.append({"source": src, "project": p["project"], "docket": p["docket"], "stage": p["stage"],
                     "online_month": p["latest_expected"], "uncontracted_mtpa": unc, "max_contract_mtpa": cap,
                     "p_by_year": {str(m.year): round(pr, 2) for m, pr in zip(months, probs) if m.month == 12}})
    return pd.DataFrame(rows, columns=["source", "month", "avail_kt"]), meta
