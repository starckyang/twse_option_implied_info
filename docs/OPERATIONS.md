# 營運說明

## 分支

| 分支 | 內容 |
|---|---|
| `main` | 程式、測試、workflow、文件 |
| `data` | `summary.csv`、`crash.csv`、`meta.json`（orphan，保留歷史，一般 push） |
| `gh-pages` | 報表（M5 才加；orphan，每次 force push） |

## 每日流程（`twvix run`）

1. 下載當日 TXO；沒有「一般」時段列（假日或尚未公布）→ 結束，**不寫入**，exit 0。
2. 計算 VIX、SVIX、崩盤機率；與官方 VIX 比對。官方值尚未公布時照寫，旗標 `official_missing`，之後重跑會覆蓋成完整的一天。
3. 自檢，任一失敗 → **不寫入**、exit 1（job 失敗，GitHub 會通知）：
   - VIX、SVIX 不是正的有限數
   - 近月或次月履約價數 < `min_strikes`
   - K0 > F
   - 崩盤機率對 γ 不單調
   - 與官方 VIX 差距 > `vix_diff_fail`（2.0）
4. upsert 到 `data` 分支（以日期為 key）。資料沒變就不 commit。

差距 > `vix_diff_warn`（0.6）只記 `vix_diff_warn` 旗標。

## 指令

```bash
uv run twvix day 2026-11-09                 # 只印出，不寫入
uv run twvix run --date 2026-11-09 --no-push # 寫到本機 data 分支，不 push
uv run twvix backfill 2026-08-03 2026-11-09 --store   # 回補並寫入 data 分支（最後 push 一次）
uv run twvix backfill 2026-08-03 2026-11-09 --crash   # 回補並輸出到 out/（分析用，不寫 data）
```

## 保活與通知

- 公開 repo 60 天沒有活動時，GitHub 會停用排程 workflow。`data` 分支有每日 commit 不一定算「活動」，
  若發現排程停了，到 Actions 頁面手動重新啟用，或加一個每月的 keepalive commit。
- GitHub 排程可能延遲數分鐘到數十分鐘；workflow 設了三個時間點，且重跑是安全的。
- job 失敗會寄信給 repo 擁有者（預設行為）。

## 尚待實測（需要 GitHub repo）

- Actions runner 能否下載 TAIFEX（站點有 Cloudflare）。
- 排程時間：TAIFEX 當日一般時段資料實際幾點可抓到。目前 14:30 / 16:30 / 19:30（台北時間）是猜的。
- 若 Actions 被擋，`fetch.py` 是唯一需要改的地方。
