"""崩盤機率：風險中性 Q（Breeden-Litzenberger）與真實 P（冪次效用，γ）。

q(s) 為風險中性密度；真實密度 p(s) ∝ q(s) s^γ。γ=0 即 P=Q。
所有機率都以遠期 moneyness 定義：K/F。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .chain import Chain
from .smile import SVI, black76, fit_svi, implied_vol, vega

GRID_LO, GRID_HI, GRID_N = 0.3, 2.0, 6000  # s/F 網格範圍與點數


@dataclass
class Smile:
    svi: SVI
    F: float
    T: float
    R: float
    rmse: float
    n_points: int
    kmin: float  # 有資料的 log-moneyness 範圍；範圍外為外插，機率會被標旗
    kmax: float


def fit_smile(c: Chain, min_points: int = 8) -> Smile:
    """由 Chain 的價外價格擬合 SVI。K0 那點是 call/put 平均，略過。"""
    F, T, R = c.F, c.T, c.R
    ks, ivs, ws = [], [], []
    for K, q in zip(c.strikes, c.Q):
        if K == c.K0:
            continue
        cp = "P" if K < c.K0 else "C"
        iv = implied_vol(q, F, K, T, R, cp)
        if np.isfinite(iv):
            ks.append(np.log(K / F))
            ivs.append(iv)
            ws.append(vega(F, K, T, iv, R))
    if len(ks) < min_points:
        raise ValueError("too few implied vols for smile")
    svi, rmse = fit_svi(np.array(ks), np.array(ivs), T, np.array(ws))
    return Smile(svi, F, T, R, rmse, len(ks), float(min(ks)), float(max(ks)))


def _put_price(sm: Smile, K: np.ndarray) -> np.ndarray:
    # 資料範圍外用 SVI 翼部外插（平坦外插在斜率陡的邊界會產生負密度，已試過並放棄）
    iv = sm.svi.vol(np.log(K / sm.F), sm.T)
    return black76(sm.F, K, sm.T, iv, sm.R, "P")


def density(sm: Smile):
    """回傳 (s, q, Qcdf)：s 網格、風險中性密度、累積機率 Q(S<s)。"""
    s = np.linspace(GRID_LO, GRID_HI, GRID_N) * sm.F
    P = _put_price(sm, s)
    dP = np.gradient(P, s)
    d2P = np.gradient(dP, s)
    Rf = np.exp(sm.R * sm.T)
    return s, Rf * d2P, Rf * dP, dP


def crash_probs(sm: Smile, thresholds, gammas) -> dict:
    """回傳 {(threshold, gamma): prob}。

    p(s) ∝ q(s) s^γ，在 [0.3F, 2F] 網格上積分。網格外的尾部質量（由 Rf·∂P/∂K 得到）
    當成網格邊界上的點質量一起納入，因此 γ=0 時嚴格等於風險中性機率 Q。
    （左尾質量放在 0.3F，會略微高估 γ>0 時的左尾權重，但通常 < 1%，且偏保守。）
    """
    s, q, Qcdf, _ = density(sm)
    # 單調重排：把累積分布限制在 [0,1] 且不遞減，使密度保證非負（SVI 外插偶爾會有微小違反）
    Qcdf = np.clip(np.maximum.accumulate(Qcdf), 0.0, 1.0)
    dq = np.diff(Qcdf)  # 每格的機率質量
    smid = (s[1:] + s[:-1]) / 2
    F = sm.F
    atom_lo = float(Qcdf[0])
    atom_hi = 1.0 - float(Qcdf[-1])
    out = {}
    for g in gammas:
        wlo, whi = (s[0] / F) ** g, (s[-1] / F) ** g
        cum = atom_lo * wlo + np.concatenate([[0.0], np.cumsum(dq * (smid / F) ** g)])
        total = cum[-1] + atom_hi * whi
        for th in thresholds:
            out[(th, g)] = float(np.interp(th * F, s, cum) / total)
    return out


def quality(sm: Smile) -> dict:
    """無套利檢查：0 <= ∂P/∂K <= 1/Rf，且密度 >= 0。回傳指標與旗標。"""
    s, q, _, dP = density(sm)
    Rf = np.exp(sm.R * sm.T)
    inner = slice(5, -5)  # 去掉網格邊界的差分誤差
    flags = []
    if dP[inner].min() < -5e-3 or dP[inner].max() > 1 / Rf + 5e-3:
        flags.append("dPdK_out_of_range")
    mass = float(np.trapezoid(q[inner], s[inner]))
    neg = float(np.trapezoid(np.minimum(q[inner], 0), s[inner]))
    if neg < -1e-2:  # SVI 外插的負密度質量超過 1%（機率計算已做單調重排，微小者無影響）
        flags.append("negative_density")
    if abs(mass - 1) > 0.02:
        flags.append("density_mass_off")
    if sm.rmse > 0.03:
        flags.append("smile_fit_poor")
    return {"mass": mass, "neg_mass": neg, "flags": flags}
