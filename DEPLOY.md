# 部署指南 · Deployment Guide
### 金融狀況 / 風險體制監測 · Financial Conditions & Risk-Regime Monitor

**給管理/維運同事的傻瓜式步驟。** 跟其他儀表板一樣的流程:
**GitHub(放程式+資料+自動更新) → Vercel(代管網址) → Squarespace(嵌入網頁)。**

完成後,網頁會自動每天更新,不需要再手動上傳資料。整個流程約 15–20 分鐘。

> 你會用到 3 個帳號:**GitHub**、**Vercel**、**Squarespace**(都和其他儀表板用同一組)。
> 需要的檔案:本壓縮包內的全部檔案 **＋ 另外單獨提供的 `index.html`**(因為它較大,單獨給你)。

---

## 你拿到的檔案清單

壓縮包解開後:
```
fetch_fred.py                          ← 抓 FRED 資料的程式(自動跑,不用手動執行)
data.json                              ← 初始資料(網頁先有東西可看,之後自動覆蓋)
README.md                              ← 技術說明(給工程參考,部署不需要)
DEPLOY.md                              ← 本檔
.github/workflows/update-fred-data.yml ← 自動更新排程
```
**另外單獨提供:** `index.html` ← 主網頁(整個儀表板)。**請把它和上面檔案放在一起。**

---

## 第 1 步 — 建立 GitHub Repo 並上傳檔案

1. 到 GitHub,點右上 **＋ → New repository**。
2. Repository name 填:`financial-conditions-monitor`(或 `risk-regime-monitor`)。
3. 選 **Private**(私人),不用勾 README,按 **Create repository**。
4. 上傳檔案(兩種方法擇一):

   **方法 A — 網頁拖拉(最簡單):**
   - 在新 repo 頁面點 **uploading an existing file**。
   - 把 `index.html`、`fetch_fred.py`、`data.json`、`README.md`、`DEPLOY.md` **全部拖進去**。
   - ⚠️ `.github/workflows/update-fred-data.yml` 這個有資料夾路徑,網頁拖拉有時會掉路徑。請在上傳框上方的檔名欄手動輸入 `.github/workflows/update-fred-data.yml`(含斜線),再貼上內容。
   - 按 **Commit changes**。

   **方法 B — 用 Git 指令(若你慣用):**
   ```bash
   git init && git add . && git commit -m "init dashboard"
   git branch -M main
   git remote add origin https://github.com/<你的組織>/financial-conditions-monitor.git
   git push -u origin main
   ```

5. 上傳後,repo 檔案結構應該長這樣(注意 `.github/workflows/` 路徑要在):
   ```
   index.html
   fetch_fred.py
   data.json
   README.md
   DEPLOY.md
   .github/workflows/update-fred-data.yml
   ```

---

## 第 2 步 — 設定 FRED 金鑰(讓資料自動更新)

> 這一步讓排程能抓到完整歷史資料(回補到 2018)。沿用其他儀表板那把 FRED 金鑰即可。

1. 在 repo 頁面點 **Settings**(齒輪)。
2. 左側 **Secrets and variables → Actions**。
3. 點 **New repository secret**。
4. **Name** 一字不差填:`FRED_API_KEY`
5. **Secret** 貼上 FRED API 金鑰(和 Macro Monitor 同一把;若不確定,問內部負責人或到 https://fredaccount.stlouisfed.org/apikeys 申請一把)。
6. 按 **Add secret**。

> 先不設也能上線(初始 `data.json` 已能顯示),但信用利差只有約 3 年歷史;設了金鑰、排程一跑就會補滿。

---

## 第 3 步 — 啟用自動更新並先跑一次

1. repo 頁面上方點 **Actions** 分頁。
2. 若看到提示 *"Workflows aren't being run on this forked repository"* 或要你啟用,按 **I understand my workflows, go ahead and enable them**。
3. 左側點 **Update FRED data**,右上 **Run workflow → Run workflow**(綠色按鈕)。
4. 等約 1–2 分鐘,出現綠色勾勾 ✓ 代表成功,`data.json` 已更新成最新資料。
   - 之後它會 **每個工作日台灣早上自動跑**(UTC 22:30),不用再管。

---

## 第 4 步 — 用 Vercel 上線(取得網址)

1. 到 https://vercel.com,用 GitHub 登入。
2. **Add New → Project**。
3. 找到 `financial-conditions-monitor`,按 **Import**。
4. **不要改任何建置設定**(這是純靜態網頁):
   - Framework Preset:**Other**
   - Build Command:**留空**
   - Output Directory:**留空**(預設根目錄)
5. 按 **Deploy**,等約 1 分鐘。
6. 完成後會給一個網址,像 `https://financial-conditions-monitor.vercel.app`。
7. **打開網址測試**:應該看到密碼閘 → 輸入通行碼(同其他儀表板的那組)→ 進入儀表板。
   - ✅ 看到漸層標題、圖表、警示橫幅 = 成功。
   - ❌ 一片空白 = 看本頁最下方「疑難排解」。

> 之後每次排程更新 `data.json` 並 commit,Vercel 會**自動重新部署**,網頁資料自動最新。

---

## 第 5 步 — 嵌入 Squarespace(和其他儀表板一樣)

> 用**頁面層級的 Code Injection**做整頁覆蓋(**不是**用 iframe 或 code block)。

1. Squarespace 後台 → **Pages**,新增一個空白頁(或選現有要放的頁)。
2. 該頁 **齒輪(Settings)→ Advanced → Page Header Code Injection**。
3. 開啟單獨提供的 `index.html`,**全選複製整個檔案內容**。
4. **貼進 Code Injection 框**。
   - ⚠️ 若系統限制貼上純文字,請把 `index.html` **改副檔名為 `.txt`** 後當作文字貼上(和其他儀表板相同做法)。
5. **Save**。
6. 預覽該頁:應出現密碼閘 → 輸入通行碼 → 整頁儀表板。

> 提示:Squarespace 這種整頁覆蓋會蓋掉該頁原本的版型,屬正常。若只想嵌一塊,改用 Vercel 網址放 iframe(但其他儀表板都是整頁覆蓋,建議一致)。

---

## ✅ 上線檢查清單

- [ ] GitHub repo 有全部 6 個檔案,且 `.github/workflows/` 路徑正確
- [ ] `FRED_API_KEY` secret 已設定
- [ ] Actions 手動跑過一次,綠勾 ✓
- [ ] Vercel 網址打得開,輸入通行碼能進儀表板
- [ ] Squarespace 頁面顯示正常
- [ ] 隔天回來看 Actions 有自動跑(代表排程正常)

---

## 疑難排解

| 症狀 | 原因 / 解法 |
|---|---|
| Vercel 網頁**一片空白** | 多半是圖表庫(ECharts)沒載入。確認有網路、稍等重整;網頁已內建備援來源(jsdelivr→unpkg)。 |
| 輸入密碼後**沒反應/說不支援加密** | 密碼閘需要 **HTTPS**。Vercel 與 Squarespace 都是 HTTPS,沒問題;**不要**直接用「開啟本機檔案(file://)」測試。 |
| Actions **紅色 ✗ 失敗** | 點進去看錯誤。最常見是 `FRED_API_KEY` 沒設或貼錯 → 重設第 2 步。Yahoo 偶爾擋雲端 IP 會讓 MOVE/標普暫缺,但程式有備援、不會整個失敗。 |
| 網頁有圖但**資料是舊的** | 確認 Actions 有成功跑且有 commit `data.json`;Vercel 會自動重部署。可在 Actions 手動再 Run 一次。 |
| Squarespace 貼上後**跑版/被截斷** | 確認是貼到 **Page Header Code Injection**(頁面層級),不是 code block;必要時用 `.txt` 方式貼。 |
| 信用利差圖**只有約 3 年** | 代表還沒用金鑰跑過。完成第 2、3 步後,歷史會補回 2018。 |

---

## 之後要維護什麼?

**幾乎不用。** 資料每個工作日自動更新。唯一偶爾要做的:
- 若 Yahoo 連續多日擋住(MOVE/標普缺資料),通常自己會恢復;持續異常再通知工程。
- 若要改密碼、加指標、調權重,屬工程範圍(見 `README.md`)。

有問題就把 **Actions 的錯誤截圖** 丟給工程負責人,最快。
