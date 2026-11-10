"""回補：按月下載（單次區間不可超過一個月）、本機快取、逐日計算。"""
from __future__ import annotations

import calendar
import datetime as dt
import time
from pathlib import Path

import pandas as pd

from .fetch import download_raw, monthly_regular, parse_csv
from .official import fetch_official_month
from .pipeline import compute_day

CACHE = Path(".cache")  # 僅本機暫存，已 gitignore；不是正式資料儲存


def month_ranges(start: dt.date, end: dt.date):
    cur = start.replace(day=1)
    while cur <= end:
        last = cur.replace(day=calendar.monthrange(cur.year, cur.month)[1])
        yield max(cur, start), min(last, end)
        cur = last + dt.timedelta(days=1)


def load_month(a: dt.date, b: dt.date, sleep: float = 1.0) -> pd.DataFrame:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"txo_{a:%Y%m%d}_{b:%Y%m%d}.csv"
    if f.exists():
        text = f.read_text(encoding="utf-8")
    else:
        text = download_raw(a, b)
        f.write_text(text, encoding="utf-8")
        time.sleep(sleep)
    return monthly_regular(parse_csv(text))


def backfill(start: dt.date, end: dt.date, cfg: dict, with_crash: bool = False) -> pd.DataFrame:
    rows, crash, errors = [], [], []
    for a, b in month_ranges(start, end):
        df = load_month(a, b)
        for day, g in df.groupby("date"):
            try:
                r = compute_day(g.reset_index(drop=True), day, cfg, with_crash=with_crash)
                if with_crash:
                    r, cr = r
                    crash += [{"date": day.isoformat(), **x} for x in cr]
                rows.append(r)
            except Exception as e:  # 單日失敗不中斷回補，記錄下來
                errors.append({"date": day.isoformat(), "error": repr(e)})
    out = pd.DataFrame(rows)
    out.attrs["errors"] = errors
    out.attrs["crash"] = pd.DataFrame(crash)
    return out


def compare_official(out: pd.DataFrame) -> pd.DataFrame:
    months = sorted({d[:7].replace("-", "") for d in out["date"]})
    off = pd.concat([fetch_official_month(m) for m in months], ignore_index=True)
    off["date"] = off["date"].map(lambda d: d.isoformat())
    m = out.merge(off, on="date", how="left")
    m["vix_diff"] = m["vix"] - m["vix_taifex_published"]
    m["vix_diff_pct"] = m["vix_diff"] / m["vix_taifex_published"] * 100
    return m
