from __future__ import annotations

import argparse
import datetime as dt
import json

from .fetch import fetch_day
from .pipeline import compute_day, load_config


def main() -> None:
    ap = argparse.ArgumentParser(prog="twvix")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("day", help="計算單日 VIX / SVIX 並印出")
    p.add_argument("date", help="YYYY-MM-DD")
    p.add_argument("--config", default="config.yaml")
    u = sub.add_parser("update-latest", help="檢查 data 分支有沒有漏（含今天），有就補上並 push")
    u.add_argument("--config", default="config.yaml")
    u.add_argument("--repo", default=".")
    u.add_argument("--no-push", action="store_true")
    u.add_argument("--full", action="store_true", help="從 backfill_start 全部掃描（預設只掃最近 14 天）")
    u.add_argument("--lookback", type=int, default=14)
    b = sub.add_parser("backfill", help="回補區間並對照官方 VIX")
    b.add_argument("start")
    b.add_argument("end")
    b.add_argument("--config", default="config.yaml")
    b.add_argument("--out", default="out/backfill.csv")
    b.add_argument("--crash", action="store_true", help="同時計算崩盤機率，輸出到 out 同資料夾的 crash.csv")
    b.add_argument("--basis", choices=["bid_ask_mid", "settle"], help="覆寫 config 的 price_basis")
    a = ap.parse_args()
    if a.cmd == "day":
        d = dt.date.fromisoformat(a.date)
        df = fetch_day(d)
        if df.empty:
            raise SystemExit(f"{d}: 沒有一般時段資料（假日或尚未公布）")
        print(json.dumps(compute_day(df, d, load_config(a.config)), ensure_ascii=False, indent=2))
    elif a.cmd == "update-latest":
        from pathlib import Path

        from .runner import update_latest

        res = update_latest(load_config(a.config), Path(a.repo), push=not a.no_push, full=a.full, lookback_days=a.lookback)
        print(f"{res['status']}: 寫入 {len(res['written'])} 天 {res['written']}")
        for d, why in res["failed"].items():
            print(f"::error::{d} 未寫入：{why}")
        raise SystemExit(1 if res["failed"] else 0)
    elif a.cmd == "backfill":
        from pathlib import Path

        from .backfill import backfill, compare_official

        cfg = load_config(a.config)
        if a.basis:
            cfg["price_basis"] = a.basis
        res = backfill(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), cfg, with_crash=a.crash)
        m = compare_official(res)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        m.to_csv(a.out, index=False)
        if a.crash:
            res.attrs["crash"].to_csv(Path(a.out).parent / "crash.csv", index=False)
        print(f"{len(m)} days -> {a.out}; errors: {res.attrs['errors']}")
        d = m["vix_diff"].dropna()
        print(f"matched {len(d)} | mean {d.mean():+.3f} | sd {d.std():.3f} | mae {d.abs().mean():.3f} | max|diff| {d.abs().max():.3f}")


if __name__ == "__main__":
    main()
