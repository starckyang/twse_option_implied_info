"""由 data 分支的結果產生單一靜態 index.html（資料以 JSON 內嵌，圖表用 Chart.js CDN）。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

TEMPLATE = Path(__file__).with_name("report_template.html")
SUMMARY_FIELDS = [
    "date", "vix", "svix", "vix_taifex_published", "vix_diff", "near_expiry", "next_expiry", "quality_flags",
]


def _clean(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    if isinstance(v, (np.floating, np.integer)):
        return None if not np.isfinite(float(v)) else float(v)
    return None if pd.isna(v) else v


def build_payload(summary: pd.DataFrame, crash: pd.DataFrame, meta: dict) -> dict:
    s = summary.sort_values("date")
    rows = [{k: _clean(r[k]) for k in SUMMARY_FIELDS} for _, r in s.iterrows()]
    for r in rows:
        r["quality_flags"] = r["quality_flags"] or ""
    # 只內嵌 30 天機率：{date: {threshold: {gamma: prob}}}，key 皆為字串
    c = crash[crash["horizon"] == "30d"]
    out: dict = {}
    for r in c.itertuples():
        th, g = f"{float(r.threshold):g}", f"{int(r.gamma)}"
        out.setdefault(r.date, {}).setdefault(th, {})[g] = float(r.prob)
    return {"summary": rows, "crash": out, "meta": meta}


def build_html(summary: pd.DataFrame, crash: pd.DataFrame, meta: dict) -> str:
    payload = json.dumps(build_payload(summary, crash, meta), ensure_ascii=False, allow_nan=False)
    payload = payload.replace("</", "<\\/")  # 避免 </script> 提前結束
    return TEMPLATE.read_text(encoding="utf-8").replace("__PAYLOAD__", payload)
