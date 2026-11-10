"""隱含波動率（Black-76）與 SVI 平滑。純函式。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq, least_squares
from scipy.stats import norm


def black76(F, K, T, sigma, R, cp):
    sigma = np.maximum(sigma, 1e-8)
    sd = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sd**2) / sd
    d2 = d1 - sd
    df = np.exp(-R * T)
    if cp == "C":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def vega(F, K, T, sigma, R):
    sd = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sd**2) / sd
    return np.exp(-R * T) * F * norm.pdf(d1) * np.sqrt(T)


def implied_vol(price, F, K, T, R, cp):
    """Black-76 隱含波動率；價格不在無套利範圍內則回傳 NaN。"""
    df = np.exp(-R * T)
    intrinsic = df * max((F - K) if cp == "C" else (K - F), 0.0)
    upper = df * (F if cp == "C" else K)
    if not (intrinsic < price < upper):
        return np.nan
    f = lambda s: black76(F, K, T, s, R, cp) - price
    try:
        return brentq(f, 1e-4, 5.0, xtol=1e-10)
    except ValueError:
        return np.nan


@dataclass
class SVI:
    a: float
    b: float
    rho: float
    m: float
    s: float

    def total_var(self, k):
        k = np.asarray(k, dtype=float)
        return self.a + self.b * (self.rho * (k - self.m) + np.sqrt((k - self.m) ** 2 + self.s**2))

    def vol(self, k, T):
        return np.sqrt(np.maximum(self.total_var(k), 1e-12) / T)


# 參數 (a, b, rho, m, s) 界限。b<=0.6 => 翼斜率 b(1±ρ)<=0.9 < 2（Lee 矩界限）；ρ 上限 0.5 避免右翼過度凸。
SVI_LO = (-1.0, 1e-6, -0.95, -0.6, 1e-2)
SVI_HI = (1.0, 0.6, 0.5, 0.6, 1.0)


def fit_svi(k: np.ndarray, iv: np.ndarray, T: float, w: np.ndarray | None = None) -> tuple[SVI, float]:
    """對 log-moneyness k 與隱含波動率 iv 擬合 SVI，回傳 (SVI, 加權 RMSE of vol)。"""
    tv = iv**2 * T
    w = np.ones_like(k) if w is None else w / np.mean(w)
    sw = np.sqrt(w)

    def res(p):
        a, b, rho, m, s = p
        return sw * (np.sqrt(np.maximum(SVI(*p).total_var(k), 1e-12) / T) - iv)

    atm = float(np.min(tv))
    best = None
    for rho0 in (-0.5, 0.0, -0.8):
        for s0 in (0.05, 0.15):
            x0 = [atm * 0.8, 0.1, rho0, 0.0, s0]
            lo, hi = list(SVI_LO), list(SVI_HI)
            try:
                r = least_squares(res, x0, bounds=(lo, hi), xtol=1e-12, ftol=1e-12, max_nfev=2000)
            except Exception:
                continue
            if best is None or r.cost < best.cost:
                best = r
    if best is None:
        raise ValueError("SVI fit failed")
    p = SVI(*best.x)
    rmse = float(np.sqrt(np.mean(res(best.x) ** 2)))
    return p, rmse
