"""dodo.py 的各個步驟。每個函式只讀明確的輸入檔、只寫明確的輸出檔，可獨立重跑。

目錄約定（皆已 gitignore）：
  _data/raw/txo_YYYYMM.csv         原始下載（utf-8，未經處理）
  _data/official/vix_YYYYMM.csv    TAIFEX 官方每日 VIX
  _output/months/summary_YYYYMM.csv, crash_YYYYMM.csv, errors_YYYYMM.csv
  _output/summary.csv, crash.csv, errors.csv, diff_stats.json   （合併後）
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from .fetch import download_raw, monthly_regular, parse_csv
from .official import fetch_official_month
from .pipeline import ToleranceError, load_config
from .runner import SelfCheckError, evaluate_day
from .store import CRASH_COLS, SUMMARY_COLS, build_meta, git, read_data_branch, write_data_branch

DATA, OUT = Path("_data"), Path("_output")


def months(start: dt.date, end: dt.date) -> list[str]:
    out, cur = [], start.replace(day=1)
    while cur <= end:
        out.append(cur.strftime("%Y%m"))
        cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def month_bounds(ym: str, start: dt.date, end: dt.date) -> tuple[dt.date, dt.date]:
    first = dt.date(int(ym[:4]), int(ym[4:]), 1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return max(first, start), min(last, end)


def fetch_raw(ym: str, start: str, end: str, target: str) -> None:
    a, b = month_bounds(ym, dt.date.fromisoformat(start), dt.date.fromisoformat(end))
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text(download_raw(a, b), encoding="utf-8")


def fetch_official(ym: str, target: str) -> None:
    df = fetch_official_month(ym)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target, index=False)


def compute_month(raw: str, official: str, config: str, out_summary: str, out_crash: str, out_errors: str) -> None:
    """一個月份：逐日計算、與官方比對、自檢。失敗的日子記到 errors，不中斷。"""
    cfg = load_config(config)
    df = monthly_regular(parse_csv(Path(raw).read_text(encoding="utf-8")))
    off = pd.read_csv(official, dtype={"date": str}) if Path(official).stat().st_size else pd.DataFrame()
    off_map = dict(zip(off.get("date", []), off.get("vix_taifex_published", []))) if len(off) else {}
    summ, crash, errs = [], [], []
    for day, g in df.groupby("date"):
        try:
            s, c = evaluate_day(g.reset_index(drop=True), day, cfg, off_map.get(day.isoformat()))
            summ.append(s)
            crash += c
        except (ToleranceError, SelfCheckError, ValueError) as e:
            errs.append({"date": day.isoformat(), "error": f"{type(e).__name__}: {e}"})
    for path in (out_summary, out_crash, out_errors):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summ, columns=SUMMARY_COLS).to_csv(out_summary, index=False)
    pd.DataFrame(crash, columns=CRASH_COLS).to_csv(out_crash, index=False)
    pd.DataFrame(errs, columns=["date", "error"]).to_csv(out_errors, index=False)


def combine(month_dir: str, out_dir: str) -> None:
    md, od = Path(month_dir), Path(out_dir)
    od.mkdir(parents=True, exist_ok=True)

    def cat(prefix, cols):
        files = sorted(md.glob(f"{prefix}_*.csv"))
        parts = [pd.read_csv(f, dtype={"date": str}) for f in files if f.stat().st_size > 1]
        parts = [p for p in parts if len(p)]
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
        return df.sort_values("date", kind="stable").reset_index(drop=True)

    s, c, e = cat("summary", SUMMARY_COLS), cat("crash", CRASH_COLS), cat("errors", ["date", "error"])
    s.to_csv(od / "summary.csv", index=False)
    c.to_csv(od / "crash.csv", index=False)
    e.to_csv(od / "errors.csv", index=False)
    d = s["vix_diff"].dropna().astype(float)
    stats = {
        "days": int(len(s)), "days_with_official": int(len(d)), "error_days": int(len(e)),
        "diff_mean": float(d.mean()) if len(d) else None, "diff_sd": float(d.std()) if len(d) > 1 else None,
        "diff_mae": float(d.abs().mean()) if len(d) else None, "diff_max_abs": float(d.abs().max()) if len(d) else None,
    }
    (od / "diff_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")


def publish(summary: str, crash: str, config: str, repo: str, push: bool) -> None:
    cfg = load_config(config)
    s = pd.read_csv(summary, dtype={"date": str})
    c = pd.read_csv(crash, dtype={"date": str})
    meta = build_meta(cfg, dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"), s["date"].max())
    changed = write_data_branch(Path(repo), s, c, meta, push=push)
    print("data branch:", "updated" if changed else "unchanged")


def check_complete(raw_dir: str, repo: str) -> None:
    """檢查：原始資料裡有「一般」時段資料的交易日，data 分支是否都有。有缺就列出並以非 0 結束。"""
    expected = set()
    for f in sorted(Path(raw_dir).glob("txo_*.csv")):
        df = monthly_regular(parse_csv(f.read_text(encoding="utf-8")))
        expected |= {d.isoformat() for d in df["date"].unique()}
    s, _ = read_data_branch(Path(repo))
    missing = sorted(expected - set(s["date"]))
    print(f"預期 {len(expected)} 個交易日，data 分支有 {len(expected & set(s['date']))} 個")
    if missing:
        raise SystemExit(f"data 分支缺 {len(missing)} 天：{', '.join(missing)}\n→ 執行 `uv run doit update_latest` 補上")


def build_report(out: str, repo: str) -> None:
    """讀 data 分支（遠端為準）產生 index.html。"""
    import json as _json

    from .report import build_html

    s, c = read_data_branch(Path(repo))
    if s.empty:
        raise SystemExit("data 分支沒有資料，無法產生報表")
    meta_raw = git(Path(repo), "show", "origin/data:meta.json", check=False).stdout or "{}"
    html = build_html(s, c, _json.loads(meta_raw))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(html, encoding="utf-8")
    print(f"report: {out} ({len(s)} days)")


def publish_pages_step(html: str, repo: str, push: bool) -> None:
    from .store import publish_pages

    changed = publish_pages(Path(repo), Path(html).read_text(encoding="utf-8"), push=push)
    print("gh-pages:", "updated" if changed else "unchanged")
