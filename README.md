<div align="center">

# 🪰 Stonkfly

### 果蠅大腦驅動的加密貨幣交易模擬系統

**166,700 個真實果蠅神經元 · 2,560 萬突觸連接 · 纏論學習 · 即時監控**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

</div>

---

## 📖 專案簡介

Stonkfly 是一個以**真實果蠅全腦連接組（MaleCNS v1.0）**為基礎的神經模擬交易系統。系統將加密貨幣市場數據編碼為視覺影像，刺激果蠅的視網膜神經元，透過 166,700 個神經元的即時運算產生買賣決策，並以**纏論技術分析**作為學習目標，讓果蠅在模擬環境中學習交易。

### 核心概念

```
市場數據 → 視網膜編碼(320×180 RGB) → 果蠅大腦(166,700神經元) → 神經解碼 → 買賣決策
     ↑                                                                          ↓
     └────────────── 獎勵/懲罰(多巴胺) ←────────── 盈虧回饋 ←───────────────────┘
```

---

## ✨ 功能特色

### 🧠 神經模擬
- **166,700 個真實果蠅神經元**，依 MaleCNS v1.0 連接組建構
- **2,560 萬突觸連接**，即時電化學傳遞模擬
- **3,335 個視網膜輸入神經元**，R1-R6 感光細胞層
- **多巴胺獎勵系統**：PAM11 獎勵細胞 + PPL101 厭惡細胞
- **432Hz 振盪刺激**：對 Kenyon 細胞施加療癒頻率
- **突觸可塑性**：候選記憶規則改變 KC-MBON 連接強度

### 📊 纏論學習系統
- **理論學習器**：6 大核心概念（分型、筆、線段、中樞、背馳、買賣點）
- **實戰學習器**：6 項交易技能（突破回踩、背馳買賣、中樞震盪等）
- **知識持久化**：學習成果跨啟動保留
- **學習進度顯示**：理論/實戰/勝率/買點/賣點熟練度

### 📈 交易策略（果蠅+纏論並行決策）
- **並行決策模式**：果蠅和纏論任一方有訊號就交易，不需要另一方觀望
- **買入條件**：(果蠅說BUY **或** 纏論說BUY) + 無持倉 → 買入
- **賣出條件**：(果蠅說SELL **或** 纏論說SELL) + 有持倉 → 賣出
- **雙方共識**：果蠅和纏論都說買/賣 → 標註[果蠅+纏論]
- **交易理由標註決策者**：[果蠅+纏論]、[果蠅自由]、[纏論參考]、[觀察]
- **止盈已取消**：賣出時間點由趨勢、纏論訊號和果蠅自然決策共同判斷
- **止損保護**：-3%自動賣出（僅防禦）
- **每次買入1顆BTC**：市價單，1%緩衝確保完整成交
- **初始資金1000萬USDT**：0手續費模擬
- **冷卻60秒**：每筆交易後冷卻，避免頻繁交易
- **市場教訓機制**：虧損刺激 PPL101 厭惡神經元，獲利刺激 PAM11 獎勵神經元，突觸隨之調整

### 🖥️ 即時監控介面
- **3D 神經元可視化**：突觸連線 + 放電脈衝動畫 + 熱力圖
- **K 線圖**：TradingView Lightweight Charts，支援 1m/5m/15m/30m/1h/4h/8h/1d
- **纏論標記**：筆線（紅綠）、中樞（紫色填滿）、分型箭頭、買賣點
- **深度圖**：幣安真實 Order Book，買賣單即時更新
- **神經活動監測**：做多/做空狀態、獎勵/厭惡刺激、KC 放電
- **交易紀錄**：即時成交明細，含買賣理由（粗體顯示）
- **自動切換 K 線時間框**：每 15 秒循環切換
- **交易音效**：成交時播放提示音

### 🛡️ 穩定性機制
- **看門狗（Watchdog）**：同時監控監控伺服器和模擬進程，當機自動重啟
- **停滯偵測**：每30秒檢查latest.json，超過6分鐘未更新自動強制殺掉進程並重啟
- **大腦睡眠機制**：每 25 步強制睡眠整理，保留帳戶狀態（持倉、現金、交易紀錄）
- **記憶體管理**：每步驟強制垃圾回收，防止效能衰減
- **崩潰恢復**：從大腦檢查點恢復，學習成果與交易紀錄保留
- **24 小時不停機**：無限循環執行，crash 自動重啟

---

## 🏗️ 系統架構

```
stonkfly/
├── stonkfly/                    # 核心套件
│   ├── cli.py                   # 主程式入口，模擬迴圈
│   ├── config.py                # 設定檔
│   ├── broker.py                # 券商介面（Paper/Binance/Coinbase）
│   ├── market.py                # 市場數據擷取
│   ├── display.py               # 視網膜影像編碼（320×180）
│   ├── ledger.py                # 帳本與會計
│   ├── reinforcement.py         # 獎勵機制
│   ├── risk.py                  # 風控
│   ├── strategy.py              # 策略引擎（馬丁格爾等）
│   ├── chan_learning.py         # 纏論理論學習器
│   ├── chan_practical.py        # 纏論實戰學習器
│   ├── czsc_chart.py            # 纏論結構提取
│   ├── czsc_skills.py           # 纏論技能庫
│   ├── trade_reason.py          # 交易理由生成器
│   ├── advanced_learning.py     # 進階學習系統
│   └── neural/                  # 神經網路核心
│       ├── brain.py             # 大腦模擬器
│       ├── controller.py        # 神經控制器
│       ├── visual.py            # 視覺輸入
│       ├── kernel.cpp           # C++ 運算核心
│       └── ...
├── monitor_pro.py               # 監控伺服器（Flask）
├── monitor_pro.html             # 監控介面（賽博龐克風格）
├── monitor_watchdog.py          # 看門狗
├── run_continuous.py            # 24小時連續執行器
├── data/                        # 神經連接數據（需 prepare）
├── runs/paper/                  # 模擬輸出
│   ├── brain-*.npz              # 大腦檢查點
│   ├── events.jsonl             # 交易紀錄
│   ├── ledger.sqlite            # 帳本
│   ├── chan_knowledge.json      # 纏論理論學習進度
│   └── chan_practical.json      # 纏論實戰學習進度
└── docs/                        # 文件
```

---

## 🚀 安裝與設定

### 環境需求
- Python 3.11+
- C++17 編譯器（Windows: MinGW/MSYS2, Linux: GCC, macOS: Clang）
- 16GB RAM 建議
- 網路連線（幣安 API）

### 安裝步驟

```bash
# 1. 複製專案
git clone https://github.com/fr303388/stonkfly.git
cd stonkfly

# 2. 建立虛擬環境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 3. 安裝依賴
pip install -e '.[test]'

# 4. 下載神經連接數據（約 1.5GB）
python -m stonkfly prepare

# 5. 設定環境變數
cp .env.example .env
# 編輯 .env 填入幣安 API 金鑰（選擇性，paper 模式不需要）
```

### Windows 編譯器設定

安裝 MinGW-w64（UCRT64）：
```bash
# 使用 MSYS2 UCRT64 終端
pacman -Syu
pacman -S --needed mingw-w64-ucrt-x86_64-gcc
```

---

## 🎮 使用方式

### 基本模擬（Paper Trading）

```bash
python -m stonkfly run \
  --fast \
  --steps 10000 \
  --products BTC-USDT \
  --exchange binance \
  --neural-ms 2000 \
  --hz432 \
  --strategy martingale \
  --chan-auto
```

### 24 小時連續執行

```bash
python run_continuous.py
```

> **果蠅+纏論並行決策模式**：使用 `--chan-auto` 啟用，果蠅和纏論任一方有訊號就交易。每次買入1顆BTC，冷卻60秒，止盈已取消（由果蠅和纏論判斷賣出時機），-3%止損保護。

### 啟動監控介面

```bash
python monitor_pro.py
# 瀏覽器開啟 http://127.0.0.1:8767
```

### 啟動看門狗

```bash
python monitor_watchdog.py
```

### 命令列參數

| 參數 | 說明 | 預設 |
|------|------|------|
| `--products` | 交易對（BTC-USDT, ETH-USDT, BNB-USDT） | BTC-USDT |
| `--exchange` | 交易所（binance, coinbase, paper） | paper |
| `--neural-ms` | 每次神經模擬時長（ms） | 2000 |
| `--cooldown` | 每步冷卻秒數 | 20 |
| `--hz432` | 啟用 432Hz 振盪刺激 | 關閉 |
| `--strategy` | 策略（martingale, none） | none |
| `--steps` | 執行步數 | 100 |
| `--fast` | 快速模式（跳過部分驗證） | 關閉 |
| `--take-profit` | 止盈百分比（0=停用） | 0 |
| `--chan-auto` | 純纏論自動交易 + 果蠅共同決策 | 關閉 |
| `--live` | 真實交易（需 API 金鑰） | 關閉 |

---

## 🖥️ 監控介面說明

### 版面配置
```
┌─────────────────────────────────────────────────────────┐
│  帳戶概覽：總盈虧、未實現、持倉、現金、模擬計時          │
├──────────────┬──────────────┬──────────────────────────┤
│  3D 神經元   │  感光細胞輸入 │  神經活動監測            │
│  +熱力圖     │  (K線預覽)    │  做多/做空、獎勵、學習    │
├──────────────┴──────────────┴──────────────────────────┤
│  K 線圖（纏論標記 + 買賣點）  │  深度圖（Order Book）    │
├─────────────────────────────────────────────────────────┤
│  交易紀錄（即時成交明細 + 買賣理由）                      │
└─────────────────────────────────────────────────────────┘
```

### 步驟流程（1-6 無限循環）
1. **市場數據**：RSI + 纏論分析，15分K線
2. **視網膜編碼**：120根K線 → 320×180感光影像
3. **神經模擬**：166,700神經元運算
4. **神經解碼決策**：DNp20 左右解碼 + DNpe017 閘門控制
5. **風控與執行**：下單、冷卻 60 秒（果蠅自由決策模式）
6. **獎勵與學習**：盈虧回饋多巴胺，冷卻期學習纏論

---

## 📊 纏論學習系統

### 理論學習（6 概念）
| 概念 | 說明 |
|------|------|
| 分型 | 頂分型、底分型辨識 |
| 筆 | 相鄰頂底連線，向上/向下 |
| 線段 | 至少三筆組成，方向確認 |
| 中樞 | 三線段重疊區域，震盪範圍 |
| 背馳 | 動力衰減判斷，趨勢反轉 |
| 買賣點 | 一買/二買/三買，一賣/二賣/三賣 |

### 實戰技能（6 技能）
- 突破回踩入場
- 背馳買賣點
- 中樞震盪操作
- 趨勢跟蹤
- 止損止盈管理
- 多時間框確認

### 學習機制
- 每次冷卻期（80秒）自動學習纏論知識
- 理論學習曲線：累計時間 → 知識熟練度
- 實戰練習：用真實市場數據驗證技能
- 學習成果影響交易信心和決策權重

---

## 🔌 API 參考

監控伺服器（預設 `http://127.0.0.1:8767`）

| 端點 | 說明 |
|------|------|
| `GET /` | 監控介面 HTML |
| `GET /api/state` | 完整狀態（大腦、事件、帳戶） |
| `GET /api/brain3d` | 3D 神經元數據（位置、放電強度） |
| `GET /api/binance?interval=1m` | 幣安 K 線（200根） |
| `GET /api/czsc?interval=1m` | 纏論結構分析 |
| `GET /api/depth` | 訂單簿深度 |
| `GET /api/token` | 即時價格 + 24h 統計 |
| `GET /api/input.png` | 視網膜輸入影像 |
| `GET /api/advanced` | 進階學習狀態 |
| `GET /trade_sound.mp3` | 交易音效 |

---

## ⚙️ 設定檔（.env）

```env
# 幣安 API（真實交易需要，paper 模式不需要）
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

# Coinbase API（選擇性）
COINBASE_API_KEY=
COINBASE_API_SECRET=

# 模擬設定
INITIAL_CASH=10000000  # 1000萬USDT
NEURAL_MS=2000
COOLDOWN_SECONDS=80
```

---

## 🛠️ 進階功能

### 真實交易準備
1. 在幣安開啟 API 權限（現貨交易）
2. 將 API 金鑰填入 `.env`
3. 使用 `--live` 參數啟動
4. 建議先用小額資金測試

### 大腦睡眠機制
- 每25步強制睡眠或神經模擬超過80秒自動觸發
- 看門狗偵測到6分鐘停滯也會強制重啟
- 儲存大腦檢查點 → 記憶體清理 → 優雅結束（exit 42）
- run_continuous.py 偵測後保留帳戶狀態重啟
- 睡眠次數記錄在 `watchdog_stats.json`

### 自訂策略
繼承 `stonkfly/strategy.py` 的 `BaseStrategy`，實作 `should_buy()` 和 `should_sell()` 方法，在 cli.py 中掛載。

---

## ❓ 常見問題

**Q: 為什麼 K 線圖沒有顯示？**
A: 確認幣安 API 可連線，檢查瀏覽器 Console 是否有 JS 錯誤，Ctrl+Shift+R 強制刷新。

**Q: 神經模擬越來越慢？**
A: 系統已內建記憶體回收和睡眠機制，若仍變慢可檢查 RAM 使用量，或重啟 run_continuous.py。

**Q: 交易紀錄的盈虧和總盈虧不同？**
A: 交易紀錄顯示單筆已實現盈虧，總盈虧=已實現+未實現（目前持倉的浮動盈虧）。

**Q: 果蠅真的在「思考」嗎？**
A: 是真實的神經元電位模擬，166,700 個神經元依離子通道模型運算，不是動畫。但「思考」是人類的比喻，實際上是神經網路的動態響應。

**Q: 可以賺錢嗎？**
A: 這是研究專案，獲利能力未經驗證。神經網路的學習效果有限，主要用於探索生物神經在決策任務上的表現。

---

## 📚 參考文獻

- [MaleCNS v1.0 Connectome](https://codex.flywire.ai/app/male_cns)
- [Drosophila Mushroom Body Circuit](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6058482/)
- [纏論（纏中說禪）](https://chanlun.com/)

---

## 📄 授權

MIT License - 詳見 [LICENSE](LICENSE)

## 🤝 貢獻

歡送 Issue 和 Pull Request！

---

<div align="center">

**用果蠅大腦交易，因為反正你也猜不贏市場 🪰**

</div>
