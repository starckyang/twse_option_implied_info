import numpy as np
import pytest

from twvix.chain import build_chain
from twvix.svix import svix, svix2_T
from twvix.vix import sigma2, vix
from helpers import synthetic_quotes

R = 0.015


@pytest.mark.parametrize("sigma", [0.1, 0.2, 0.4])
def test_flat_vol_vix_single_expiry(sigma):
    T = 30 / 365
    c = build_chain(synthetic_quotes(sigma=sigma, T=T, R=R), R, T)
    assert abs(c.F - 100) < 0.05
    assert np.sqrt(sigma2(c)) == pytest.approx(sigma, rel=2e-3)


def test_flat_vol_vix_interpolated():
    sigma = 0.25
    T1, T2 = 20 / 365, 50 / 365
    c1 = build_chain(synthetic_quotes(sigma=sigma, T=T1, R=R), R, T1)
    c2 = build_chain(synthetic_quotes(sigma=sigma, T=T2, R=R), R, T2)
    assert vix(c1, c2) == pytest.approx(100 * sigma, rel=3e-3)


@pytest.mark.parametrize("sigma", [0.1, 0.25])
def test_svix_matches_lognormal_variance(sigma):
    T = 30 / 365
    c = build_chain(synthetic_quotes(sigma=sigma, T=T, R=R), R, T)
    assert svix2_T(c) == pytest.approx(np.exp(sigma**2 * T) - 1, rel=3e-3)


def test_svix_interpolated_close_to_analytic():
    sigma = 0.25
    T1, T2 = 20 / 365, 50 / 365
    c1 = build_chain(synthetic_quotes(sigma=sigma, T=T1, R=R), R, T1)
    c2 = build_chain(synthetic_quotes(sigma=sigma, T=T2, R=R), R, T2)
    expected = 100 * np.sqrt((np.exp(sigma**2 * 30 / 365) - 1) / (30 / 365))
    assert svix(c1, c2) == pytest.approx(expected, rel=5e-3)


def test_flat_vol_svix_slightly_above_vix():
    # 對數常態下 SVIX^2 T = e^{σ²T}-1 > σ²T = VIX^2 T，所以平坦波動率時 SVIX 略高於 VIX。
    # （真實市場有負偏態與跳躍，通常 VIX > SVIX，但這不是定理，因此只當資訊旗標。）
    T1, T2 = 20 / 365, 50 / 365
    c1 = build_chain(synthetic_quotes(sigma=0.3, T=T1, R=R), R, T1)
    c2 = build_chain(synthetic_quotes(sigma=0.3, T=T2, R=R), R, T2)
    assert 0 < svix(c1, c2) - vix(c1, c2) < 0.3
