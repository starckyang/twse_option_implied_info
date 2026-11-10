"""SVIX（遠期價正規化版本）。

SVIX_i^2 * T_i = 2 * Rf / F^2 * sum(Q * dK)，Rf = exp(R*T)，Q 為今天的價外選擇權價格。
與 Martin 以現貨正規化的版本，在有股利時略有差異。
"""
from __future__ import annotations

import numpy as np

from .chain import Chain
from .vix import interp30


def svix2_T(c: Chain) -> float:
    return float(2 * np.exp(c.R * c.T) / c.F**2 * np.sum(c.Q * c.dK))


def svix(c1: Chain, c2: Chain) -> float:
    var = interp30(c1.T, svix2_T(c1), c2.T, svix2_T(c2))
    return 100 * float(np.sqrt(var))
