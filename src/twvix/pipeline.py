"""把一天的月選資料算成 VIX / SVIX。"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import yaml

from .calendar import select_expiries
from .chain import build_chain
from .crash import crash_probs, fit_smile, quality
from .svix import svix
from .vix import N365, vix, weights30

CALC_TIME = dt.time(13, 30)  # 以收盤（一般時段結束）為計算時點
SETTLE_TIME = dt.time(13, 30)  # 到期日結算時點


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["holidays"] = {dt.date.fromisoformat(str(d)) for d in cfg.get("holidays", [])}
    return cfg


def minutes_to_expiry(trade_date: dt.date, expiry: dt.date) -> float:
    a = dt.datetime.combine(trade_date, CALC_TIME)
    b = dt.datetime.combine(expiry, SETTLE_TIME)
    return (b - a).total_seconds() / 60


def compute_crash(c1, c2, cfg: dict) -> tuple[list[dict], list[str]]:
    """回傳 (crash 長表列, 品質旗標)。horizon: near / next / 30d。"""
    ths, gms = cfg.get("crash_thresholds", [0.9, 0.8]), cfg.get("gammas", [0, 1, 2, 4])
    flags, probs = [], {}
    for lab, c in (("near", c1), ("next", c2)):
        sm = fit_smile(c)
        probs[lab] = crash_probs(sm, ths, gms)
        flags += [f"{f}_{lab}" for f in quality(sm)["flags"]]
        flags += [
            f"threshold_{th:.2f}_extrapolated_{lab}"
            for th in ths
            if not (sm.kmin <= np.log(th) <= sm.kmax)
        ]
    w1, w2 = weights30(c1.T, c2.T)
    probs["30d"] = {k: w1 * probs["near"][k] + w2 * probs["next"][k] for k in probs["near"]}
    rows = [
        {"horizon": h, "threshold": th, "gamma": g, "prob": p}
        for h, d in probs.items()
        for (th, g), p in d.items()
    ]
    # 同一門檻下，崩盤機率應隨 γ 增加而遞減
    for h, d in probs.items():
        for th in ths:
            seq = [d[(th, g)] for g in sorted(gms)]
            if any(b > a + 1e-12 for a, b in zip(seq, seq[1:])):
                flags.append(f"gamma_not_monotone_{h}")
                break
    return rows, flags


def compute_day(df: pd.DataFrame, trade_date: dt.date, cfg: dict, with_crash: bool = False):
    """with_crash=False 回傳 summary dict；True 回傳 (summary dict, crash 長表列)。"""
    """df：fetch.monthly_regular 的輸出（單日）。"""
    R = cfg["risk_free_rate"]
    basis = cfg.get("price_basis", "bid_ask_mid")
    if basis == "settle":
        # 結算價基準：bid=ask=結算價；結算價 <= settle_min_valid（最小跳動單位附近）視為無效
        s = df["settle"].where(df["settle"] > cfg.get("settle_min_valid", 0.1))
        df = df.assign(bid=s, ask=s)
    elif basis != "bid_ask_mid":
        raise ValueError(f"unknown price_basis: {basis}")
    near_e, next_e = select_expiries(trade_date, df["expiry"].unique(), cfg.get("holidays"))
    chains = []
    for e in (near_e, next_e):
        T = minutes_to_expiry(trade_date, e) / N365
        chains.append(build_chain(df[df["expiry"] == e], R, T))
    c1, c2 = chains
    flags = [f"few_strikes_{lab}" for lab, c in (("near", c1), ("next", c2)) if c.n < cfg.get("min_strikes", 5)]
    v, s = vix(c1, c2), svix(c1, c2)
    if s > v:
        flags.append("svix_gt_vix")  # 僅資訊旗標，並非定理
    crash_rows = []
    if with_crash:
        crash_rows, cflags = compute_crash(c1, c2, cfg)
        flags += cflags
    summary = {
        "date": trade_date.isoformat(),
        "vix": v,
        "svix": s,
        "near_expiry": near_e.isoformat(),
        "next_expiry": next_e.isoformat(),
        "T_near": c1.T,
        "T_next": c2.T,
        "F_near": c1.F,
        "F_next": c2.F,
        "K0_near": c1.K0,
        "K0_next": c2.K0,
        "n_strikes_near": c1.n,
        "n_strikes_next": c2.n,
        "rate_used": R,
        "price_basis": basis,
        "quality_flags": ";".join(flags),
    }
    return (summary, crash_rows) if with_crash else summary


class ToleranceError(RuntimeError):
    pass


def check_against_official(result: dict, official: float | None, cfg: dict) -> dict:
    """與官方公布 VIX 比對：寫入 vix_taifex_published、vix_diff，超過 warn 加旗標，超過 fail 丟例外。
    official 為 None（尚未公布）時只加旗標 official_missing。"""
    flags = [f for f in result["quality_flags"].split(";") if f]
    if official is None:
        flags.append("official_missing")
        result.update(vix_taifex_published=None, vix_diff=None)
    else:
        diff = result["vix"] - official
        result.update(vix_taifex_published=official, vix_diff=diff)
        if abs(diff) > cfg["vix_diff_fail"]:
            raise ToleranceError(f"{result['date']}: |diff|={abs(diff):.3f} > {cfg['vix_diff_fail']}")
        if abs(diff) > cfg["vix_diff_warn"]:
            flags.append("vix_diff_warn")
    result["quality_flags"] = ";".join(flags)
    return result
