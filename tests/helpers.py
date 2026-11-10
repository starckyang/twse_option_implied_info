import numpy as np
import pandas as pd
from scipy.stats import norm


def black76(F, K, T, sigma, R, cp):
    d1 = (np.log(F / K) + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    df = np.exp(-R * T)
    return df * (F * norm.cdf(d1) - K * norm.cdf(d2)) if cp == "C" else df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def synthetic_quotes(F=100.0, T=30 / 365, sigma=0.2, R=0.015, lo=0.2, hi=3.0, step=0.1):
    rows = []
    for K in np.arange(F * lo, F * hi, step):
        for cp in ("C", "P"):
            p = black76(F, K, T, sigma, R, cp)
            rows.append({"strike": float(K), "cp": cp, "bid": p, "ask": p})
    return pd.DataFrame(rows)
