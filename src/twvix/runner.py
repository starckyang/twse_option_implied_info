"""每日流程：下載 → 計算 → 自檢 → upsert 到 data 分支。"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pandas as pd

from .fetch import fetch_day
from .official import fetch_official_month
from .pipeline import ToleranceError, check_against_official, compute_day
from .store import METHOD_VERSION, build_meta, write_data_branch

TAIPEI = dt.timezone(dt.timedelta(hours=8))


class SelfCheckError(RuntimeError):
    pass


def today_taipei() -> dt.date:
    return dt.datetime.now(TAIPEI).date()


def official_for(day: dt.date) -> float | None:
    off = fetch_official_month(day.strftime("%Y%m"))
    row = off[off["date"] == day]
    return float(row["vix_taifex_published"].iloc[0]) if len(row) else None


def self_check(summary: dict, cfg: dict) -> None:
    """不通過就丟 SelfCheckError（不寫入、job 失敗）。ToleranceError 由 check_against_official 丟出。"""
    for k in ("vix", "svix"):
        v = summary[k]
        if not (isinstance(v, float) and math.isfinite(v) and v > 0):
            raise SelfCheckError(f"{summary['date']}: {k} 不是正的有限數 ({v})")
    for lab in ("near", "next"):
        if summary[f"n_strikes_{lab}"] < cfg.get("min_strikes", 5):
            raise SelfCheckError(f"{summary['date']}: {lab} 履約價數不足 ({summary[f'n_strikes_{lab}']})")
        if summary[f"K0_{lab}"] > summary[f"F_{lab}"]:
            raise SelfCheckError(f"{summary['date']}: {lab} K0 > F")
    bad = [f for f in summary["quality_flags"].split(";") if f.startswith("gamma_not_monotone")]
    if bad:
        raise SelfCheckError(f"{summary['date']}: 崩盤機率對 γ 不單調 ({bad})")


def run_day(day: dt.date, cfg: dict, repo: Path, *, push: bool = True, df: pd.DataFrame | None = None,
            official: float | None | str = "fetch") -> str:
    """回傳狀態：'no_data'（非交易日或一般時段資料未公布，未寫入）、'written'、'unchanged'。"""
    df = fetch_day(day) if df is None else df
    if df.empty:
        return "no_data"
    summary, crash_rows = compute_day(df, day, cfg, with_crash=True)
    off = official_for(day) if official == "fetch" else official
    summary = check_against_official(summary, off, cfg)  # 可能丟 ToleranceError
    summary["method_version"] = METHOD_VERSION
    self_check(summary, cfg)
    s = pd.DataFrame([summary])
    c = pd.DataFrame([{"date": day.isoformat(), **r} for r in crash_rows])
    meta = build_meta(cfg, dt.datetime.now(TAIPEI).isoformat(timespec="seconds"), day.isoformat())
    changed = write_data_branch(repo, s, c, meta, push=push)
    return "written" if changed else "unchanged"
