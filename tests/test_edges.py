import datetime as dt

import numpy as np
import pytest

from twvix.calendar import select_expiries, trading_days_after
from twvix.chain import build_chain
from helpers import synthetic_quotes

R = 0.015
T = 30 / 365
D = dt.date


def test_truncation_two_consecutive_missing_bids():
    q = synthetic_quotes(T=T, R=R, step=0.5)
    base = build_chain(q, R, T)
    # 在 K0 下方挖掉兩個連續履約價的買價 -> 更低履約價全部排除
    cut = base.K0 - 5.0
    drop = q["strike"].isin([cut, cut - 0.5]) & (q["cp"] == "P")
    q2 = q.copy()
    q2.loc[drop, "bid"] = np.nan
    c = build_chain(q2, R, T)
    assert c.strikes.min() > cut
    assert c.strikes.max() == base.strikes.max()


def test_single_missing_strike_does_not_truncate():
    q = synthetic_quotes(T=T, R=R, step=0.5)
    base = build_chain(q, R, T)
    k = base.K0 - 5.0
    q2 = q.copy()
    q2.loc[(q2["strike"] == k) & (q2["cp"] == "P"), "bid"] = np.nan
    c = build_chain(q2, R, T)
    assert c.strikes.min() == base.strikes.min()
    assert k not in c.strikes


def test_zero_bid_is_invalid():
    q = synthetic_quotes(T=T, R=R, step=0.5)
    q.loc[q["strike"] > 150, "bid"] = 0.0  # 買權價外全部無買價
    c = build_chain(q, R, T)
    assert c.strikes.max() <= 152


def test_k0_not_above_f_and_next_strike_above():
    c = build_chain(synthetic_quotes(F=100.3, T=T, R=R, step=0.5), R, T)
    assert c.K0 <= c.F < c.K0 + 0.5


def test_too_few_strikes_raises():
    q = synthetic_quotes(T=T, R=R, lo=0.99, hi=1.01, step=0.5)
    q.loc[:, "bid"] = np.where(q["strike"].between(99.9, 100.1), q["bid"], np.nan)
    with pytest.raises(ValueError):
        build_chain(q, R, T)


def test_trading_days_after():
    # 週五 -> 下週三：週一、二、三 = 3 天
    assert trading_days_after(D(2026, 11, 13), D(2026, 11, 18), set()) == 3
    assert trading_days_after(D(2026, 11, 13), D(2026, 11, 18), {D(2026, 11, 16)}) == 2


EXP = [D(2026, 11, 18), D(2026, 12, 16), D(2027, 1, 20)]


@pytest.mark.parametrize(
    "day,near",
    [
        (D(2026, 11, 9), D(2026, 11, 18)),
        (D(2026, 11, 13), D(2026, 11, 18)),  # 剩 3 個交易日，不換
        (D(2026, 11, 16), D(2026, 12, 16)),  # 剩 2 個，換
        (D(2026, 11, 17), D(2026, 12, 16)),
        (D(2026, 11, 18), D(2026, 12, 16)),  # 到期日當天
        (D(2026, 11, 19), D(2026, 12, 16)),
    ],
)
def test_roll(day, near):
    got = select_expiries(day, EXP, set())
    assert got[0] == near
    assert got[1] == EXP[EXP.index(near) + 1]


def test_roll_delayed_by_holiday():
    # 11/17 休市：11/13(五) 距 11/18 剩 11/16、11/18 = 2 個交易日 -> 提前到 11/13 換
    assert select_expiries(D(2026, 11, 13), EXP, {D(2026, 11, 17)})[0] == D(2026, 12, 16)


def test_settle_basis_ignores_bid_ask():
    import datetime as dt

    from twvix.pipeline import compute_day
    from helpers import synthetic_quotes as sq

    rows = []
    for e, T in ((dt.date(2026, 11, 18), 9 / 365), (dt.date(2026, 12, 16), 37 / 365)):
        q = sq(F=100, T=T, sigma=0.2, step=0.5)
        q["expiry"] = e
        q["settle"] = q["bid"]
        q["bid"], q["ask"] = np.nan, np.nan  # 買賣價全無，結算價仍可算
        rows.append(q)
    import pandas as pd

    df = pd.concat(rows)
    cfg = {"risk_free_rate": R, "price_basis": "settle", "holidays": set(), "settle_min_valid": 1e-6}
    out = compute_day(df, dt.date(2026, 11, 9), cfg)
    assert out["price_basis"] == "settle"
    assert abs(out["vix"] - 20) < 0.3
