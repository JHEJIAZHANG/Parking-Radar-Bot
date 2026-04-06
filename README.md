# 🚗 全台即時停車雷達 (Parking Radar Bot)

這是一個以 **Python** 開發的智慧型 LINE Bot，旨在幫助使用者快速尋找全台灣（含路外、路邊、觀光景點、國道休息站及航空站）的附近停車場，並提供**即時的剩餘車位資訊**。使用者只需在 LINE 中傳送自己的位置，就能立即收到美觀的 iOS 票根風格 (Ticket Style) 停車資訊卡片。

## 🌟 亮點功能 (Features)

- **📍 適地性搜尋 (LBS)**：使用者透過 LINE 傳送位置資訊，系統依照距離遠近，自動列出 3 公里內的前 10 間停車場。
- **🟢 即時車位顯示**：串聯交通部 TDX 系統，提供最新、最準確的即時車位資料與佔用率進度條。
- **🛡️ 雙軌容錯備援 (Fallback 機制)**：針對新北市的停車場，採用「TDX 優先，新北市開放資料墊底」的雙引擎拉取機制，確保即時資料不漏接。
- **🧠 智慧去重演算法 (Deduplication)**：內建 Haversine 經緯度計算與字串相似度比對（Sequence Matcher），若發現地方政府（如新北市）與中央機構（如台鐵、高鐵）對同一車場發生重複建檔，會強制收斂並優先保留中央 TDX 軌道車站的原始高品質資料。
- **📱 極致視覺體驗 (iOS Ticket UI)**：純手工打造的 LINE Flex Message，不依賴傳統難以排版的格式，採用無邊框、精簡色塊的「現代票根」美學設計，自動附上導航捷徑與資料獲取時間戳記。
- **🗺️ 一鍵精準導航**：解決單純座標定位的導航誤差，優先針對停車場「實體地址」呼叫 Google Maps 進行精準路徑規劃。

## 🛠️ 技術架構 (Tech Stack)

- **語言**: Python 3.9+
- **框架**: FastAPI / Uvicorn
- **資料庫**: SQLite (輕量級空間快取)
- **通訊介面**: LINE Messaging API (line-bot-sdk v3)
- **資料來源**: 
  - 交通部 TDX (Transport Data eXchange)
  - 新北市政府公共停車場資訊 API (NTPC Open Data)

## 🚀 快速上手 (Getting Started)

### 1. 取得專案
```bash
git clone https://github.com/JHEJIAZHANG/Parking-Radar-Bot.git
cd Parking-Radar-Bot
```

### 2. 安裝依賴套件
```bash
pip install -r requirements.txt
```
*(如果沒有 `requirements.txt`，請準備：`fastapi`, `uvicorn`, `line-bot-sdk`, `requests`, `pandas`, `python-dotenv`, `pyngrok`)*

### 3. 設定環境變數
在專案根目錄下建立一個 `.env` 檔案，並填寫以下憑證：
```env
# LINE Messaging API
LINE_CHANNEL_SECRET=你的_LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN=你的_LINE_CHANNEL_ACCESS_TOKEN

# 交通部 TDX API (若無可留空，但會限制查詢頻率)
TDX_CLIENT_ID=你的_TDX_CLIENT_ID
TDX_CLIENT_SECRET=你的_TDX_CLIENT_SECRET
```

### 4. 初始化資料庫
專案中包含了預先爬取好的全台各縣市停車場靜態 CSV 資料，首次執行伺服器時，系統將自動調用 `init_database()` 建立 `parking.db` 索引。

### 5. 啟動伺服器
```bash
python3 line_bot.py
```
機器人將預設監聽在 `http://0.0.0.0:8000`。請搭配使用 `ngrok` 等工具將本地 Port 穿透至外部 HTTPS 網域，並將該網址設定回 LINE Developer Console 的 Webhook URL。

## 📁 專案結構 (Folder Structure)

| 檔案/目錄 | 說明 |
| ----------- | ----------- |
| `line_bot.py` | 主程式入口、LINE Webhook 處理、Flex Message 視覺構建 |
| `parking_finder.py` | 核心引擎：包含資料庫初始化、空間搜尋演算法、TDX/NTPC 即時串接 |
| `Basic_Parking_Information_Script/` | 放置各種用於抓取與驗證全台靜態停車場資料的資料處理解析腳本與 CSV |
| `.env` | (不可上傳) 敏感金鑰及設定 |
| `parking.db` | (不可上傳) 自動生成的 SQLite 空間緩存資料庫 |

## ⚠️ 免責聲明 (Disclaimer)
本服務車位資料源自政府開放資料平台(TDX/NTPC)，即時數量僅供參考，實際狀況與費率請以各停車場現場公告為準。 

## 🤝 授權與貢獻
歡迎提交 Issue 或 Pull Request，任何讓推薦演算法更精準、或讓介面更優美的想法都非常棒！
