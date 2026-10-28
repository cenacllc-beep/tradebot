"""Fees and incentives for new engines (added 2026-10-22, platform upgrade phases 20-21). One place for the formulas.
The frozen v3 path keeps core.fee: the same formula for weather markets (multiplier 1, taker), but without the small
float tolerance used here, so it is 1c higher in a few cases (for example p 0.10, 100 contracts: 0.64 vs 0.63).

Kalshi (fee schedule; format-checked 2026-10-15 on /series/{ticker}):
- **Taker fee per order** = round up to the cent of 0.07 x fee_multiplier x C x P x (1 - P).
- **Maker fee:**
  - 0 on fee_type "quadratic" series, which covers the weather series checked.
  - "quadratic_with_maker_fees" series also charge makers. This file uses 0.0175 x multiplier x C x P x (1 - P),
    rounded up: a quarter of the taker rate. That rate is NOT verified against Kalshi's current schedule, so maker
    results on those series are flagged.
- Any other fee type: unknown, so there is no estimate and the candidate is rejected (FEE_TOO_HIGH is not claimed
  without a number).

Liquidity incentives (Kalshi's Liquidity Incentive Program, until 2027-01-01) are counted in expected returns ONLY when
INCENTIVES_ELIGIBLE is True. The user must confirm the account's eligibility (US member, SSN on file above IRS
thresholds) before setting it. Until then, reports show incentive estimates separately and never add them in.
Python 3.8+."""
import math
INCENTIVES_ELIGIBLE=False   # set True only after the user confirms eligibility (CLAUDE.md); research reports read it
ELIGIBILITY_CONFIRMED_ON=None   # "YYYY-MM-DD" the user confirmed it, logged in CHANGELOG; PLAN5 L counts rewards only if this is before its window ends
QUADRATIC=("quadratic","quadratic_with_maker_fees")
def _up(x): return math.ceil(x*100-1e-9)/100
def taker(p,n=1,mult=1.0,fee_type="quadratic"):
    if fee_type not in QUADRATIC or p is None: return None
    return _up(0.07*mult*n*p*(1-p))
def maker(p,n=1,mult=1.0,fee_type="quadratic"):
    """(fee, verified). Quadratic series: (0, True). With maker fees: (estimate, False)."""
    if fee_type=="quadratic": return 0.0,True
    if fee_type=="quadratic_with_maker_fees" and p is not None: return _up(0.0175*mult*n*p*(1-p)),False
    return None,False
def net_edge(p_win,price,n=1,mult=1.0,fee_type="quadratic",role="taker"):
    """Expected value per contract after the fee for this order type, or None if the fee is unknown."""
    if role=="taker": f=taker(price,n,mult,fee_type)
    else: f,_=maker(price,n,mult,fee_type)
    if f is None or p_win is None or price is None: return None
    return p_win-price-f/n
def with_incentives(trading_pnl,incentive_estimate):
    """What a report may add up: incentives only when the account is confirmed eligible."""
    return trading_pnl+(incentive_estimate if INCENTIVES_ELIGIBLE else 0.0)
