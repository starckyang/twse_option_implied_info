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
    r = sub.add_parser("run", help="每日流程：計算並 upsert 到 data 分支")
    r.add_argument("--date", help="YYYY-MM-DD，預設為台北時間今天")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--repo", default=".")
    r.add_argument("--no-push", action="store_true")
    b = sub.add_parser("backfill", help="回補區間並對照官方 VIX")
    b.add_argument("start")
    b.add_argument("end")
    b.add_argument("--config", default="config.yaml")
    b.add_argument("--out", default="out/backfill.csv")
    b.add_argument("--store", action="store_true", help="逐日跑完整流程（含自檢）並 upsert 到 data 分支，最後 push 一次")
    b.add_argument("--repo", default=".")
    b.add_argument("--no-push", action="store_true")
    b.add_argument("--crash", action="store_true", help="同時計算崩盤機率，輸出到 out 同資料夾的 crash.csv")
    b.add_argument("--basis", choices=["bid_ask_mid", "settle"], help="覆寫 config 的 price_basis")
    a = ap.parse_args()
    if a.cmd == "day":
        d = dt.date.fromisoformat(a.date)
        df = fetch_day(d)
        if df.empty:
            raise SystemExit(f"{d}: 沒有一般時段資料（假日或尚未公布）")
        print(json.dumps(compute_day(df, d, load_config(a.config)), ensure_ascii=False, indent=2))
    elif a.cmd == "run":
        from pathlib import Path

        from .pipeline import ToleranceError
        from .runner import SelfCheckError, run_day, today_taipei

        day = dt.date.fromisoformat(a.date) if a.date else today_taipei()
        try:
            status = run_day(day, load_config(a.config), Path(a.repo), push=not a.no_push)
        except (ToleranceError, SelfCheckError) as e:
            print(f"::error::自檢失敗，未寫入：{e}")
            raise SystemExit(1)
        print(f"{day}: {status}")
    elif a.cmd == "backfill":
        from pathlib import Path

        from .backfill import backfill, compare_official

        cfg = load_config(a.config)
        if a.store:
            import subprocess
            from pathlib import Path as _P

            from .backfill import load_month, month_ranges
            from .official import fetch_official_month
            from .runner import run_day

            start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
            counts, failed = {}, []
            for lo, hi in month_ranges(start, end):
                off = fetch_official_month(lo.strftime("%Y%m")).set_index("date")["vix_taifex_published"]
                for day, g in load_month(lo, hi).groupby("date"):
                    try:
                        st = run_day(day, cfg, _P(a.repo), push=False, df=g.reset_index(drop=True),
                                     official=float(off[day]) if day in off.index else None)
                        counts[st] = counts.get(st, 0) + 1
                    except Exception as e:
                        failed.append(f"{day}: {e!r}")
            if not a.no_push and counts.get("written"):
                subprocess.run(["git", "-C", a.repo, "push", "origin", "data"], check=True)
            print(counts, "failed:", failed)
            raise SystemExit(1 if failed else 0)
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
