import datetime as dt

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from twvix.chain import build_chain
from twvix.crash import crash_probs, fit_smile, quality
from twvix.pipeline import compute_crash
from helpers import synthetic_quotes

R = 0.015
GAMMAS = [0, 1, 2, 4]
THS = [0.9, 0.8]


def lognormal_P(th, gamma, sigma, T):
    """q 為對數常態時，p ∝ q s^γ 仍為對數常態：ln s 的平均上移 γσ²T、變異數不變。"""
    sd = sigma * np.sqrt(T)
    return norm.cdf((np.log(th) + sd**2 / 2 - gamma * sd**2) / sd)


@pytest.mark.parametrize("sigma,T", [(0.2, 30 / 365), (0.3, 45 / 365), (0.15, 20 / 365)])
def test_lognormal_q_and_p_match_analytic(sigma, T):
    c = build_chain(synthetic_quotes(sigma=sigma, T=T, R=R, step=0.25), R, T)
    sm = fit_smile(c)
    got = crash_probs(sm, THS, GAMMAS)
    for (th, g), v in got.items():
        exp = lognormal_P(th, g, sigma, T)
        assert v == pytest.approx(exp, rel=2e-3, abs=1e-6), (th, g)
    # γ=0 的解析解即 N(-d2)
    d2 = (np.log(1 / 0.9) - sigma**2 * T / 2) / (sigma * np.sqrt(T))
    assert got[(0.9, 0)] == pytest.approx(norm.cdf(-d2), rel=2e-3)


def test_monotone_in_gamma_and_threshold():
    c = build_chain(synthetic_quotes(sigma=0.25, T=30 / 365, R=R, step=0.25), R, 30 / 365)
    p = crash_probs(fit_smile(c), THS, GAMMAS)
    for th in THS:
        seq = [p[(th, g)] for g in GAMMAS]
        assert all(a > b for a, b in zip(seq, seq[1:]))
    for g in GAMMAS:
        assert p[(0.9, g)] > p[(0.8, g)]


def test_quality_clean_on_synthetic():
    c = build_chain(synthetic_quotes(sigma=0.25, T=30 / 365, R=R, step=0.25), R, 30 / 365)
    q = quality(fit_smile(c))
    assert q["flags"] == []
    assert q["mass"] == pytest.approx(1.0, abs=5e-3)


def test_skewed_smile_recovered():
    """用已知的偏斜 SVI 生成價格，擬合後的 Q 機率應與直接由真實曲線算出的一致。"""
    from twvix.smile import SVI, black76

    F, T = 100.0, 30 / 365
    true = SVI(a=0.002, b=0.12, rho=-0.7, m=0.0, s=0.1)
    rows = []
    for K in np.arange(60, 160, 0.25):
        iv = float(true.vol(np.log(K / F), T))
        for cp in ("C", "P"):
            p = float(black76(F, K, T, iv, R, cp))
            rows.append({"strike": float(K), "cp": cp, "bid": p, "ask": p})
    c = build_chain(pd.DataFrame(rows), R, T)
    sm = fit_smile(c)
    assert sm.rmse < 1e-4
    from twvix.crash import Smile

    ref = Smile(true, c.F, T, R, 0.0, 0, -1, 1)
    a, b = crash_probs(sm, [0.9], [0, 2]), crash_probs(ref, [0.9], [0, 2])
    for k in a:
        assert a[k] == pytest.approx(b[k], rel=5e-3)
    # 獨立驗證：對「真實曲線」的 put 價格直接做有限差分，Q = Rf * dP/dK
    h = 1e-3
    Kc = 0.9 * c.F
    Pf = lambda K: float(black76(c.F, K, T, float(true.vol(np.log(K / c.F), T)), R, "P"))
    q_fd = np.exp(R * T) * (Pf(Kc + h) - Pf(Kc - h)) / (2 * h)
    assert a[(0.9, 0)] == pytest.approx(q_fd, rel=5e-3)


def test_compute_crash_30d_between_near_and_next_and_flags():
    cfg = {"crash_thresholds": THS, "gammas": GAMMAS}
    T1, T2 = 20 / 365, 50 / 365
    c1 = build_chain(synthetic_quotes(sigma=0.25, T=T1, R=R, step=0.25), R, T1)
    c2 = build_chain(synthetic_quotes(sigma=0.25, T=T2, R=R, step=0.25), R, T2)
    rows, flags = compute_crash(c1, c2, cfg)
    d = pd.DataFrame(rows).pivot_table(index=["threshold", "gamma"], columns="horizon", values="prob")
    lo, hi = d[["near", "next"]].min(axis=1), d[["near", "next"]].max(axis=1)
    assert ((d["30d"] >= lo - 1e-12) & (d["30d"] <= hi + 1e-12)).all()
    assert flags == []


def test_extrapolation_flag_when_threshold_outside_strikes():
    cfg = {"crash_thresholds": THS, "gammas": GAMMAS}
    T = 30 / 365
    T2 = 60 / 365
    c = build_chain(synthetic_quotes(sigma=0.25, T=T, R=R, step=0.25, lo=0.85, hi=1.6), R, T)
    c2 = build_chain(synthetic_quotes(sigma=0.25, T=T2, R=R, step=0.25), R, T2)
    _, flags = compute_crash(c, c2, cfg)
    assert any("threshold_0.80_extrapolated" in f for f in flags)
