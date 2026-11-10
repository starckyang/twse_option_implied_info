# 營運說明

## 分支

| 分支 | 內容 |
|---|---|
| `main` | 程式、測試、workflow、文件 |
| `data` | `summary.csv`、`crash.csv`、`meta.json`（orphan，保留歷史，一般 push） |
| `gh-pages` | 報表（M5 才加；orphan，每次 force push） |

## 兩條線

共用同一個 `evaluate_day()`（計算 → 與官方 VIX 比對 → 自檢）和同一個 `data` 分支。

**第二條：`update_latest`（排程每天跑這個）**

```bash
uv run doit update_latest                    # 補 data 分支漏的日子（含今天）並 push
TWVIX_NO_PUSH=1 uv run doit update_latest    # 只寫本機
TWVIX_FULL=1 uv run doit update_latest       # 從 backfill_start 全部掃描補漏
```

1. 讀 `data` 分支，掃描「最後一天往前 14 天」（空分支或 `--full` 則從 `backfill_start`）到今天。
2. 要補的日子：`data` 分支沒有、但 TAIFEX 有「一般」時段資料的交易日；或旗標 `official_missing` 而官方 VIX 現在已公布的日子。
3. 假日、週末、今天尚未公布：本來就沒有「一般」時段資料，不算漏，也不算失敗。
4. 逐日 `evaluate_day`，通過的一次 push；有任何一天失敗（自檢或與官方差距 > `vix_diff_fail`）→ 該天不寫入、其他天照寫，最後 exit 1 讓 job 失敗。
5. 沒有變化就不 commit；重跑安全。

自檢（任一不過就不寫入該天）：VIX/SVIX 為正的有限數、近月與次月履約價數 ≥ `min_strikes`、K0 ≤ F、崩盤機率對 γ 單調、與官方 VIX 差距 ≤ `vix_diff_fail`（2.0）。差距 > `vix_diff_warn`（0.6）只記 `vix_diff_warn` 旗標。

**第一條：從頭建（`uv run doit`）**

`test → fetch_raw → fetch_official → compute → combine → check_complete`，細節見下一節。
最後的 `check_complete` 只讀 `data` 分支：原始資料裡有「一般」時段資料的交易日，`data` 分支是否都有。缺了會列出日期並提示跑 `doit update_latest`；補完後再跑就會通過。

## 保活與通知

- 公開 repo 60 天沒有活動時，GitHub 會停用排程 workflow。`data` 分支有每日 commit 不一定算「活動」，
  若發現排程停了，到 Actions 頁面手動重新啟用，或加一個每月的 keepalive commit。
- GitHub 排程可能延遲數分鐘到數十分鐘；workflow 設了三個時間點，且重跑是安全的。
- job 失敗會寄信給 repo 擁有者（預設行為）。

## 尚待實測（需要 GitHub repo）

- Actions runner 能否下載 TAIFEX（站點有 Cloudflare）。
- 排程時間：TAIFEX 當日一般時段資料實際幾點可抓到。目前 18:00（台北時間）是猜的，每天只跑一次。
- 若 Actions 被擋，`fetch.py` 是唯一需要改的地方。

## 用 doit 串流程（`dodo.py`）

每個步驟有明確的輸入檔與輸出檔，doit 以檔案內容（md5）判斷哪些步驟需要重跑，其餘跳過。

```bash
uv run doit list --all        # 看所有任務
uv run doit                   # 預設流程：test → fetch → compute → combine
uv run doit compute:202610    # 只重算 10 月
uv run doit combine           # 只重新合併與統計
uv run doit publish_data      # 寫入並 push data 分支（不在預設流程）
TWVIX_NO_PUSH=1 uv run doit publish_data   # 只寫本機 data 分支
TWVIX_START=2026-10-01 uv run doit         # 覆寫回補區間（預設 config.yaml 的 backfill_start 到今天）
```

| 任務 | 輸入 | 輸出 | 何時重跑 |
|---|---|---|---|
| `fetch_raw:YYYYMM` | 區間與結束日 | `_data/raw/` | 結束日（每天）或區間改變 |
| `fetch_official:YYYYMM` | 結束日 | `_data/official/` | 每天一次 |
| `compute:YYYYMM` | 該月原始檔、官方檔、`config.yaml`、計算程式 | `_output/months/` | 這些輸入的內容有變 |
| `combine` | 各月輸出 | `_output/summary.csv` 等 | 各月輸出的內容有變 |
| `test` | 程式、測試、設定 | `.doit_test_ok` | 這些檔案有變 |

實測行為：不改任何東西 → 全部跳過；刪掉某月輸出 → 只重算該月；改計算程式 → 重跑 test 與所有 compute，但不重新下載。
若重算後輸出內容沒變，下游的 `combine` 也會跳過。

`_data/`、`_output/` 都是本機暫存，不進 git；正式結果只在 `data` 分支。

## 網站（M5）

```bash
uv run doit report                          # 讀 data 分支 → _output/site/（多頁靜態網站）
TWVIX_NO_PUSH=1 uv run doit publish_pages   # 只在本機準備 gh-pages
uv run doit publish_pages                   # 發布到 gh-pages（orphan、單一 commit、force push，不留歷史）
```

頁面：

| 頁面 | 內容 |
|---|---|
| `index.html` | 只放最新結果：數值卡片（點進去看走勢）、30 天崩盤機率表、γ 的白話說明、四個按鈕 |
| `vix.html` | VIX 自算與公布值疊圖、兩者差距；日期範圍篩選、表格檢視 |
| `svix.html` | SVIX 與 VIX、VIX − SVIX |
| `crash.html` | 30 天崩盤機率（Q 與 γ=1,2,4，以線型區分）；可切換門檻 0.90 / 0.80（`?th=0.8`）；提示框列出品質旗標 |
| `methodology.html` | 資料口徑、公式、γ 假設、品質旗標、方法版本 |

資料在 `assets/data.js`，樣式與共用腳本在 `assets/`，各頁共用。圖表用 Chart.js（jsDelivr CDN），不使用瀏覽器儲存。
每日 workflow 在 `update_latest` 之後跑 `doit report publish_pages`；所有檔案與遠端相同時不推送。

第一次需要到 repo 的 Settings → Pages，Source 選 `Deploy from a branch`，Branch 選 `gh-pages` / `/ (root)`。
