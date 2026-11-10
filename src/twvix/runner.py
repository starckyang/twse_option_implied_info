"""每日流程：下載 → 計算 → 自檢 → upsert 到 data 分支。"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pandas as pd

from .official import fetch_official_month
from .pipeline import ToleranceError, check_against_official, compute_day
from .store import METHOD_VERSION, build_meta, read_data_branch, write_data_branch

TAIPEI = dt.timezone(dt.timedelta(hours=8))


class SelfCheckError(RuntimeError):
    pass


def today_taipei() -> dt.date:
    return dt.datetime.now(TAIPEI).date()


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


def evaluate_day(df: pd.DataFrame, day: dt.date, cfg: dict, official: float | None) -> tuple[dict, list[dict]]:
    """算一天：計算 → 與官方比對 → 自檢。回傳 (summary dict, crash 長表列)。
    失敗時丟 ToleranceError / SelfCheckError / ValueError。doit 與每日流程共用這一個函式。"""
    summary, crash_rows = compute_day(df, day, cfg, with_crash=True)
    summary = check_against_official(summary, official, cfg)
    summary["method_version"] = METHOD_VERSION
    self_check(summary, cfg)
    return summary, [{"date": day.isoformat(), **r} for r in crash_rows]


def _month_ranges(start: dt.date, end: dt.date):
    import calendar

    cur = start.replace(day=1)
    while cur <= end:
        last = cur.replace(day=calendar.monthrange(cur.year, cur.month)[1])
        yield max(cur, start), min(last, end)
        cur = last + dt.timedelta(days=1)


def _default_fetch(a: dt.date, b: dt.date) -> pd.DataFrame:
    from .fetch import download_raw, monthly_regular, parse_csv

    return monthly_regular(parse_csv(download_raw(a, b)))


def _default_official(a: dt.date, b: dt.date) -> dict:
    off = fetch_official_month(a.strftime("%Y%m"))
    return {d: v for d, v in zip(off["date"], off["vix_taifex_published"])}


def update_latest(cfg: dict, repo: Path, *, push: bool = True, today: dt.date | None = None,
                  lookback_days: int = 14, full: bool = False, fetch=_default_fetch, official=_default_official) -> dict:
    """檢查 data 分支有沒有漏，有就補上（含今天），一次 push。

    要補的日子：
      1. data 分支沒有、但 TAIFEX 有「一般」時段資料的交易日（漏掉的、或今天）
      2. data 分支上旗標為 official_missing、而官方 VIX 現在已公布的日子
    掃描範圍：data 分支最後一天往前 lookback_days 天（含最早的 official_missing 日）到今天；
    分支是空的或 full=True 時，從 config 的 backfill_start 開始。
    回傳 {'written': [...], 'failed': {date: 原因}, 'status': 'written'|'unchanged'|'nothing_to_do'}。
    """
    repo = Path(repo)
    today = today or today_taipei()
    s_old, _ = read_data_branch(repo)
    have = {dt.date.fromisoformat(d) for d in s_old["date"]}
    flags = s_old["quality_flags"].fillna("") if len(s_old) else pd.Series(dtype=str)
    pending = {dt.date.fromisoformat(d) for d in s_old.loc[flags.str.contains("official_missing"), "date"]} if len(s_old) else set()

    first = dt.date.fromisoformat(str(cfg["backfill_start"]))
    if full or not have:
        start = first
    else:
        start = max(first, min([max(have) - dt.timedelta(days=lookback_days)] + sorted(pending)))
    if start > today:
        return {"written": [], "failed": {}, "status": "nothing_to_do"}

    sums, crashes, written, failed = [], [], [], {}
    for a, b in _month_ranges(start, today):
        df = fetch(a, b)
        if df.empty:
            continue
        off = official(a, b)
        for day, g in df.groupby("date"):
            if day in have and day not in pending:
                continue
            o = off.get(day)
            if day in pending and o is None:
                continue  # 官方還沒公布，沒東西可補
            try:
                summ, cr = evaluate_day(g.reset_index(drop=True), day, cfg, o)
            except (ToleranceError, SelfCheckError, ValueError) as e:
                failed[day.isoformat()] = f"{type(e).__name__}: {e}"
                continue
            sums.append(summ)
            crashes += cr
            written.append(day.isoformat())
    if not sums:
        return {"written": [], "failed": failed, "status": "nothing_to_do"}
    meta = build_meta(cfg, dt.datetime.now(TAIPEI).isoformat(timespec="seconds"), max(written))
    changed = write_data_branch(repo, pd.DataFrame(sums), pd.DataFrame(crashes), meta, push=push)
    return {"written": written, "failed": failed, "status": "written" if changed else "unchanged"}
