"""TAIFEX 官方 VIX 每日收盤值（驗證基準）。只提供最近約 3 個月。"""
from __future__ import annotations

import io

import pandas as pd

BASE = "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym}new.txt"


def parse_official(text: str) -> pd.DataFrame:
    """回傳 date, vix_taifex_published（13:45 值）, vix_taifex_last1min。"""
    rows = []
    for line in io.StringIO(text):
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 8 and parts[1] == "13450000":
            rows.append(
                {
                    "date": pd.to_datetime(parts[0], format="%Y%m%d").date(),
                    "vix_taifex_published": float(parts[2]),
                    "vix_taifex_last1min": float(parts[3]) if len(parts) > 3 else float("nan"),
                }
            )
    return pd.DataFrame(rows, columns=["date", "vix_taifex_published", "vix_taifex_last1min"])


def fetch_official_month(ym: str) -> pd.DataFrame:
    import requests

    r = requests.get(BASE.format(ym=ym), timeout=30, allow_redirects=False)
    if r.status_code != 200:
        return parse_official("")
    return parse_official(r.content.decode("cp950", errors="replace"))
