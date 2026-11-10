"""VIX（CBOE 方法）與 30 天內插。"""
from __future__ import annotations

import numpy as np

from .chain import Chain

N365 = 525600  # 分鐘
N30 = 30 * 1440


def sigma2(c: Chain) -> float:
    """單一到期日的 σ²（年化變異數）。"""
    s = np.sum(c.dK / c.strikes**2 * np.exp(c.R * c.T) * c.Q)
    return float(2 / c.T * s - (c.F / c.K0 - 1) ** 2 / c.T)


def weights30(T1: float, T2: float) -> tuple[float, float]:
    """30 天內插的線性權重 (w1, w2)，w1 + w2 = 1。機率等不需縮放的量直接用這組權重。"""
    N1, N2 = T1 * N365, T2 * N365
    return (N2 - N30) / (N2 - N1), (N30 - N1) / (N2 - N1)


def interp30(T1: float, w1: float, T2: float, w2: float) -> float:
    """把兩個到期日的「總變異」w_i（VIX 為 T·σ²，SVIX 為 SVIX²·T）內插到 30 天，回傳年化變異數。"""
    N1, N2 = T1 * N365, T2 * N365
    mix = w1 * (N2 - N30) / (N2 - N1) + w2 * (N30 - N1) / (N2 - N1)
    return float(mix * N365 / N30)


def vix(c1: Chain, c2: Chain) -> float:
    var = interp30(c1.T, c1.T * sigma2(c1), c2.T, c2.T * sigma2(c2))
    return 100 * float(np.sqrt(var))
