"""由 data 分支的結果產生多頁靜態網站（資料放在 assets/data.js，圖表用 Chart.js CDN）。

頁面：index（最新結果）、vix、svix、crash（走勢圖）、methodology（方法說明）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SITE = Path(__file__).with_name("site")
SUMMARY_FIELDS = [
    "date", "vix", "svix", "vix_taifex_published", "vix_diff", "near_expiry", "next_expiry", "quality_flags",
]
PAGES = [("index", "最新結果"), ("vix", "VIX"), ("svix", "SVIX"), ("crash", "崩盤機率"), ("methodology", "方法說明")]
GAMMA = (
    "<b>γ 是什麼？</b>γ 代表風險趨避的程度。γ 越大，投資人越把壞情況看得越糟，"
    "選擇權價格裡有一部分就是這種「怕」；把它扣掉之後，實際上會大跌的機率反而越低。"
    "γ=0 不做任何調整（風險中性 Q）；γ=1、2、4 是越來越趨避。γ 是假設，不是觀察值。"
)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating, np.integer)):
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


def _nav(active: str) -> str:
    links = "".join(
        f'<a href="{n}.html"{" aria-current=\"page\"" if n == active else ""}>{label}</a>' for n, label in PAGES
    )
    return f'<nav aria-label="頁面">{links}</nav>'


FOOTER = (
    "<footer>資料更新時間：<span id=\"updated\"></span>　資料來源：臺灣期貨交易所　"
    "本站為研究用途，<strong>非投資建議</strong>。</footer>"
)


def build_site(summary: pd.DataFrame, crash: pd.DataFrame, meta: dict) -> dict[str, str]:
    """回傳 {相對路徑: 內容}。"""
    payload = json.dumps(build_payload(summary, crash, meta), ensure_ascii=False, allow_nan=False)
    payload = payload.replace("</", "<\\/")
    files = {
        "assets/data.js": f"window.TW = {payload};\n",
        "assets/style.css": (SITE / "assets" / "style.css").read_text(encoding="utf-8"),
        "assets/common.js": (SITE / "assets" / "common.js").read_text(encoding="utf-8"),
    }
    for name, _ in PAGES:
        html = (SITE / f"{name}.html").read_text(encoding="utf-8")
        files[f"{name}.html"] = html.replace("__NAV__", _nav(name)).replace("__FOOTER__", FOOTER).replace("__GAMMA__", GAMMA)
    return files
