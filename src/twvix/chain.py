"""單一到期日的履約價整理：遠期價 F、K0、價外選擇、截斷、ΔK。純函式，不碰網路。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Chain:
    F: float
    K0: float
    strikes: np.ndarray  # 納入計算的履約價（升冪）
    Q: np.ndarray  # 對應的價外（K0 為 call/put 平均）中價
    dK: np.ndarray
    T: float
    R: float

    @property
    def n(self) -> int:
        return len(self.strikes)


def _valid(bid: float, ask: float) -> bool:
    return bool(np.isfinite(bid) and np.isfinite(ask) and bid > 0 and ask >= bid)


def build_chain(q: pd.DataFrame, R: float, T: float) -> Chain:
    """q 需有欄位 strike, cp('C'/'P'), bid, ask（單一到期日）。

    價格用買賣中價。截斷：由 K0 往外，連續兩個序列買價無效即停止，更外側全部排除。
    """
    q = q.copy()
    q["mid"] = (q["bid"] + q["ask"]) / 2
    q["ok"] = [_valid(b, a) for b, a in zip(q["bid"], q["ask"])]
    mid = q.pivot(index="strike", columns="cp", values="mid").sort_index()
    ok = q.pivot(index="strike", columns="cp", values="ok").reindex(mid.index).fillna(False).astype(bool)
    for cp in ("C", "P"):
        if cp not in mid:
            raise ValueError("chain lacks calls or puts")

    # 遠期價：|C-P| 最小的履約價（call、put 都需有報價；允許買價缺失的中價不可用）
    both = mid[["C", "P"]].dropna()
    if both.empty:
        raise ValueError("no strike with both call and put quotes")
    kstar = (both["C"] - both["P"]).abs().idxmin()
    F = float(kstar + np.exp(R * T) * (both.loc[kstar, "C"] - both.loc[kstar, "P"]))

    strikes_all = mid.index.to_numpy(dtype=float)
    below = strikes_all[strikes_all <= F]
    if below.size == 0:
        raise ValueError("F below all strikes")
    K0 = float(below.max())
    if not (np.isfinite(mid.loc[K0, "C"]) and np.isfinite(mid.loc[K0, "P"])):
        raise ValueError("K0 lacks call or put quote")

    sel: dict[float, float] = {K0: float((mid.loc[K0, "C"] + mid.loc[K0, "P"]) / 2)}
    for cp, side in (("P", -1), ("C", 1)):
        cand = strikes_all[strikes_all < K0][::-1] if side < 0 else strikes_all[strikes_all > K0]
        miss = 0
        for k in cand:
            if ok.loc[k, cp]:
                miss = 0
                sel[float(k)] = float(mid.loc[k, cp])
            else:
                miss += 1
                if miss >= 2:
                    break
    K = np.array(sorted(sel))
    Q = np.array([sel[k] for k in K])
    if len(K) < 3:
        raise ValueError("too few strikes")
    dK = np.empty_like(K)
    dK[0] = K[1] - K[0]
    dK[-1] = K[-1] - K[-2]
    dK[1:-1] = (K[2:] - K[:-2]) / 2
    return Chain(F=F, K0=K0, strikes=K, Q=Q, dK=dK, T=T, R=R)
