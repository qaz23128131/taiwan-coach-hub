# 台中教練媒合平台 (MVP) - Taichung Coach Hub

這是一個專為台中地區開發的教練媒合平台 MVP，採用 **Freemium** 商業模式。

## 🚀 快速啟動

1. **安裝依賴** (如果您尚未安裝)：
   ```bash
   pip3 install -r requirements.txt
   ```

2. **啟動伺服器**：
   ```bash
   python3 main.py
   ```
   伺服器啟動後，請訪問：`http://localhost:8000`

## 👤 測試帳號

*   **管理員 (Admin)**: `admin@taichung.com` / `admin123`
*   **示範教練 (Coach)**: `fitness_chen@example.com` / `password123`
*   **示範教練 (Elite)**: `ski_girl@example.com` / `password123`

## ✨ 核心功能
- **地區搜尋**：以台中各行政區為主的教練過濾。
- **運動項目**：健身、潛水、滑雪三大主題入口。
- **Elite 模式**：首頁置頂推薦、尊榮金色邊框。
- **需求發送 (Leads)**：學員可直接留言給教練，系統自動記錄數據。
- **教練後台**：查看最近詢問、修改自身檔案。
- **管理員面板**：一鍵審核教練資歷，賦予「已驗證」標章。

## 🛠 技術細節
- **Backend**: FastAPI (Python 3.10+)
- **Database**: SQLite (SQLAlchemy 2.0)
- **Frontend**: Jinja2 + Tailwind CSS (手機優先、高度客製化)
- **Auth**: JWT + HttpOnly Cookie 認證系統

---
*由 無合全球代理 (Wuhe Global Agent) 陪伴式開發。*
*做工程很累，但比起 debug，還是工程比較療癒一點哈哈。*
