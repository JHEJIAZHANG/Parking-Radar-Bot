"""
全台即時停車場雷達 - 核心引擎 v2.0
====================================================
功能：
1. 將 6 份 CSV 統一整合進 SQLite 資料庫 (階段二)
2. 使用 Bounding Box + Haversine 公式進行兩階段空間搜尋 (階段二)
3. 支援 Fallback 擴展搜尋 (500m → 1km → 2km → 3km) (階段二)
4. ★ 即時串接 TDX API 查詢剩餘車位 (階段三)
5. ★ Token 自動管理 + 快取機制 (階段三)

架構師：哲嘉
開發工程師：Gemini
"""

import os
import math
import time
import sqlite3
import requests
import pandas as pd
from typing import Optional
from dotenv import load_dotenv

# 載入 .env 環境變數
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ============================================================
# 常數定義
# ============================================================
EARTH_RADIUS_KM = 6371.0  # 地球平均半徑 (公里)
DEFAULT_TOP_N = 5          # 預設回傳停車場數量
FALLBACK_RADII_KM = [0.5, 1.0, 2.0, 3.0]  # 搜尋半徑遞增策略 (公里)
CACHE_TTL_SECONDS = 60     # 即時車位快取存活時間 (秒)

# 檔案路徑設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_DIR = os.path.join(BASE_DIR, "Basic_Parking_Information_Script")
DB_PATH = os.path.join(BASE_DIR, "parking.db")

# TDX API 設定
TDX_AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TDX_BASE_URL = "https://tdx.transportdata.tw/api/basic"

# 7 大板塊 CSV 檔案與其對應的「類型標籤」和「欄位映射」
CSV_CONFIGS = [
    {
        "filename": "taiwan_all_parking_pro.csv",
        "type_label": "市區路外",
        "col_map": {
            "id": "停車場ID",
            "name": "停車場名稱",
            "lat": "緯度",
            "lng": "經度",
            "region": "縣市",
            "rate_info": "費率資訊",
            "ev_charging": "電動車充電樁",
            "address": "地址",
        },
    },
    {
        "filename": "taiwan_newtaipei_offstreet.csv",
        "type_label": "市區路外",
        "col_map": {
            "id": "停車場ID",
            "name": "停車場名稱",
            "lat": "緯度",
            "lng": "經度",
            "region": "縣市",
            "rate_info": "費率資訊",
            "ev_charging": "電動車充電樁",
            "address": "地址",
        },
    },
    {
        "filename": "taiwan_onstreet_parking.csv",
        "type_label": "市區路邊",
        "col_map": {
            "id": "路段ID",
            "name": "路段名稱",
            "lat": "緯度",
            "lng": "經度",
            "region": "縣市",
            "rate_info": "費率資訊",
            "ev_charging": "電動車充電樁",
            "address": "位置描述",
        },
    },
    {
        "filename": "taiwan_tourism_parking.csv",
        "type_label": "觀光景點",
        "col_map": {
            "id": "停車場ID",
            "name": "停車場名稱",
            "lat": "緯度",
            "lng": "經度",
            "region": "縣市",
            "rate_info": "費率資訊",
            "ev_charging": "電動車充電樁",
            "address": "地址",
        },
    },
    {
        "filename": "taiwan_rail_parking.csv",
        "type_label": "軌道車站",
        "col_map": {
            "id": "停車場ID",
            "name": "停車場名稱",
            "lat": "緯度",
            "lng": "經度",
            "region": "軌道業者",
            "rate_info": "費率資訊",
            "ev_charging": "電動車充電樁",
            "address": "地址",
        },
    },
    {
        "filename": "taiwan_freeway_parking.csv",
        "type_label": "國道休息站",
        "col_map": {
            "id": "停車場ID",
            "name": "停車場名稱",
            "lat": "緯度",
            "lng": "經度",
            "region": "縣市/國道",
            "rate_info": "費率資訊",
            "ev_charging": "電動車充電樁",
            "address": "地址",
        },
    },
    {
        "filename": "taiwan_airport_parking.csv",
        "type_label": "航空站",
        "col_map": {
            "id": "停車場ID",
            "name": "停車場名稱",
            "lat": "緯度",
            "lng": "經度",
            "region": "航空單位",
            "rate_info": "費率資訊",
            "ev_charging": "電動車充電樁",
            "address": "地址",
        },
    },
]


# ============================================================
# 1. SQLite 資料庫建置
# ============================================================
def init_database(force_rebuild: bool = False) -> str:
    """
    將 6 份 CSV 整合匯入 SQLite 資料庫。
    
    Args:
        force_rebuild: 若為 True，會刪除既有資料庫並重建。
    
    Returns:
        str: 建置結果摘要訊息。
    """
    if os.path.exists(DB_PATH) and not force_rebuild:
        return f"✅ 資料庫已存在: {DB_PATH}，跳過重建。(傳入 force_rebuild=True 可強制重建)"

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 建立統一的停車場資料表 (不設 PK，因部分 CSV 有重複 ID)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parking_lots (
            rowid_pk    INTEGER PRIMARY KEY AUTOINCREMENT,
            id          TEXT,
            name        TEXT NOT NULL,
            lat         REAL NOT NULL,
            lng         REAL NOT NULL,
            type        TEXT NOT NULL,
            region      TEXT,
            rate_info   TEXT,
            ev_charging TEXT,
            address     TEXT
        )
    """)

    total_imported = 0
    stats = []

    for cfg in CSV_CONFIGS:
        filepath = os.path.join(CSV_DIR, cfg["filename"])
        if not os.path.exists(filepath):
            stats.append(f"  ⚠️ 找不到: {cfg['filename']}")
            continue

        df = pd.read_csv(filepath, dtype=str)
        cm = cfg["col_map"]

        # 統一欄位名稱
        rename_map = {}
        for unified_name, original_col in cm.items():
            if original_col in df.columns:
                rename_map[original_col] = unified_name

        df = df.rename(columns=rename_map)

        # 只保留我們需要的欄位
        keep_cols = [c for c in ["id", "name", "lat", "lng", "region", "rate_info", "ev_charging", "address"] if c in df.columns]
        df = df[keep_cols].copy()

        # 加入類型標籤
        df["type"] = cfg["type_label"]

        # 轉換經緯度為浮點數，過濾無效座標
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
        before_filter = len(df)
        df = df.dropna(subset=["lat", "lng"])
        df = df[(df["lat"] != 0) & (df["lng"] != 0)]
        # 台灣合理範圍：緯度 21.5°~26.5°, 經度 119°~123°
        df = df[(df["lat"] >= 21.5) & (df["lat"] <= 26.5)]
        df = df[(df["lng"] >= 119.0) & (df["lng"] <= 123.0)]
        after_filter = len(df)
        dropped = before_filter - after_filter

        # 寫入 SQLite
        df.to_sql("parking_lots", conn, if_exists="append", index=False)
        total_imported += after_filter
        stats.append(
            f"  ✅ {cfg['type_label']:6s} | {cfg['filename']:35s} | "
            f"匯入 {after_filter:5d} 筆 | 過濾 {dropped:3d} 筆無效座標"
        )

    # 建立索引以加速查詢
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_lat ON parking_lots (lat)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_lng ON parking_lots (lng)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_type ON parking_lots (type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_lat_lng ON parking_lots (lat, lng)")

    conn.commit()
    conn.close()

    report = (
        f"🏗️ 資料庫建置完成: {DB_PATH}\n"
        f"📊 總匯入停車場數: {total_imported} 筆\n"
        f"\n詳細統計:\n" + "\n".join(stats)
    )
    return report


# ============================================================
# 2. Haversine 距離計算
# ============================================================
def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    計算兩個經緯度座標之間的直線距離 (公里)。
    使用 Haversine 公式，精度對於短距離搜尋相當足夠。
    """
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple:
    """
    計算 Bounding Box（粗篩矩形框）。
    用於先快速排除明顯不在範圍內的停車場，減少精算次數。
    """
    delta_lat = radius_km / 111.0
    delta_lng = radius_km / (111.0 * math.cos(math.radians(lat)))
    return (
        lat - delta_lat,
        lat + delta_lat,
        lng - delta_lng,
        lng + delta_lng,
    )


# ============================================================
# 3. ★ TDX API 認證管理 (階段三新增)
# ============================================================
class TDXAuth:
    """
    TDX API Token 管理器。
    自動獲取 Access Token，並在過期前 5 分鐘自動刷新。
    """

    def __init__(self):
        self._token = None
        self._token_expires_at = 0  # Unix timestamp
        self._client_id = os.getenv("TDX_CLIENT_ID", "")
        self._client_secret = os.getenv("TDX_CLIENT_SECRET", "")

        if not self._client_id or not self._client_secret:
            print("⚠️ 警告: 未設定 TDX_CLIENT_ID / TDX_CLIENT_SECRET (.env 檔案)")

    def get_headers(self) -> dict:
        """取得帶有 Bearer Token 的 HTTP headers。若 Token 過期會自動刷新。"""
        now = time.time()
        # 提前 5 分鐘刷新
        if self._token is None or now >= (self._token_expires_at - 300):
            self._refresh_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _refresh_token(self):
        """向 TDX 申請新的 Access Token。"""
        try:
            resp = requests.post(
                TDX_AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            # TDX Token 效期通常為 1 天 (86400 秒)
            expires_in = data.get("expires_in", 86400)
            self._token_expires_at = time.time() + expires_in
            print(f"🔑 TDX Token 已刷新 (有效期: {expires_in}s)")
        except Exception as e:
            print(f"❌ TDX Token 取得失敗: {e}")
            self._token = None

    @property
    def is_ready(self) -> bool:
        """檢查是否有有效的 credentials。"""
        return bool(self._client_id and self._client_secret)


# 全域 TDX 認證實例
_tdx_auth = TDXAuth()


# ============================================================
# 4. ★ 即時車位快取系統 (階段三新增)
# ============================================================
class AvailabilityCache:
    """
    記憶體快取，60 秒 TTL。
    key = (parking_type, region)，value = { id: availability_info }
    """

    def __init__(self, ttl: int = CACHE_TTL_SECONDS):
        self._cache = {}  # { key: (timestamp, data) }
        self._ttl = ttl

    def get(self, key: tuple) -> Optional[dict]:
        """取得快取資料，若過期則回傳 None。"""
        if key in self._cache:
            cached_time, data = self._cache[key]
            if time.time() - cached_time < self._ttl:
                return data
            else:
                del self._cache[key]
        return None

    def set(self, key: tuple, data: dict):
        """寫入快取。"""
        self._cache[key] = (time.time(), data)

    def stats(self) -> str:
        """快取統計。"""
        valid = sum(1 for _, (t, _) in self._cache.items() if time.time() - t < self._ttl)
        return f"快取: {valid}/{len(self._cache)} 有效"


# 全域快取實例
_avail_cache = AvailabilityCache()


# ============================================================
# 5. ★ TDX 即時車位 API 查詢 (階段三新增)
# ============================================================

# 每種停車場類型對應的 API 端點和解析方式
API_ENDPOINTS = {
    "市區路外": {
        "url_template": "/v1/Parking/OffStreet/ParkingAvailability/City/{region}",
        "param_key": "region",       # 用 region 值當路徑參數
        "data_key": "ParkingAvailabilities",
        "id_key": "CarParkID",
    },
    "市區路邊": {
        "url_template": "/v1/Parking/OnStreet/ParkingSegmentAvailability/City/{region}",
        "param_key": "region",
        "data_key": "CurbParkingSegmentAvailabilities",
        "id_key": "ParkingSegmentID",
    },
    "觀光景點": {
        "url_template": "/v1/Parking/OffStreet/ParkingAvailability/Tourism",
        "param_key": None,           # 不需路徑參數
        "data_key": "ParkingAvailabilities",
        "id_key": "CarParkID",
    },
    "軌道車站": {
        "url_template": "/v1/Parking/OffStreet/ParkingAvailability/Rail/Station/{region}",
        "param_key": "region",
        "data_key": "ParkingAvailabilities",
        "id_key": "CarParkID",
    },
    "國道休息站": {
        "url_template": "/v1/Parking/OffStreet/ParkingAvailability/Road/Freeway/ServiceArea",
        "param_key": None,
        "data_key": "ParkingAvailabilities",
        "id_key": "CarParkID",
    },
    "航空站": {
        "url_template": "/v1/Parking/OffStreet/ParkingAvailability/Air/Airport/{region}",
        "param_key": "region",
        "data_key": "ParkingAvailabilities",
        "id_key": "CarParkID",
    },
}

# ★ 新北市專用即時車位 API
NEWTAIPEI_AVAILABILITY_URL = "https://data.ntpc.gov.tw/api/datasets/e09b35a5-a738-48cc-b0f5-570b67ad9c78/json?size=2000"

def _fetch_newtaipei_availability() -> dict:
    """從新北市開放資料平台取得即時車位。"""
    try:
        all_data = {}
        page = 0
        while True:
            url = f"{NEWTAIPEI_AVAILABILITY_URL}&page={page}"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for item in data:
                pid = item.get("ID", "")
                avail = int(item.get("AVAILABLECAR", -9))
                if avail == -9:
                    avail = -1  # 無資料
                all_data[pid] = {
                    "total": -1,      # 新北即時 API 不提供總車位
                    "available": avail,
                    "service_status": 1 if avail >= 0 else 0,
                }
            if len(data) < 1000:
                break
            page += 1
        print(f"  ✅ 新北即時車位: {len(all_data)} 筆")
        return all_data
    except Exception as e:
        print(f"  ❌ 新北即時車位錯誤: {e}")
        return {}


def _fetch_availability_from_api(parking_type: str, region: str) -> dict:
    """
    從 TDX API 取得某類型 + 區域的即時車位資料。
    
    Args:
        parking_type: 停車場類型 (e.g., "市區路外")
        region: 地區代碼 (e.g., "Taipei", "TRA")
    
    Returns:
        dict: { parking_id: { "total": int, "available": int, "status": int } }
    """
    endpoint = API_ENDPOINTS.get(parking_type)
    if not endpoint:
        return {}

    # 組裝 URL
    url_path = endpoint["url_template"]
    if endpoint["param_key"]:
        url_path = url_path.replace("{region}", region)
    
    url = f"{TDX_BASE_URL}{url_path}"
    params = {"$format": "JSON"}

    try:
        headers = _tdx_auth.get_headers()
        resp = requests.get(url, headers=headers, params=params, timeout=15)

        if resp.status_code == 429:
            print(f"  ⚠️ API 頻率限制 (429)，跳過即時查詢: {parking_type}/{region}")
            return {}

        resp.raise_for_status()
        data = resp.json()

        # 解析回傳資料
        avail_list = data.get(endpoint["data_key"], [])
        id_key = endpoint["id_key"]

        result = {}
        for item in avail_list:
            pid = item.get(id_key, "")
            total = item.get("TotalSpaces", -1)
            available = item.get("AvailableSpaces", -1)
            service_status = item.get("ServiceStatus", -1)

            result[pid] = {
                "total": total,
                "available": available,
                "service_status": service_status,
            }

        return result

    except requests.exceptions.Timeout:
        print(f"  ⏱️ API 逾時: {parking_type}/{region}")
        return {}
    except Exception as e:
        print(f"  ❌ API 錯誤 ({parking_type}/{region}): {e}")
        return {}


def fetch_availability_for_results(results: list) -> dict:
    """
    針對搜尋結果中的停車場，批次查詢即時車位。
    使用快取避免重複呼叫。
    
    Args:
        results: find_nearest_parking 回傳的 results list
    
    Returns:
        dict: { parking_id: { "total", "available", "service_status" } }
    """
    # 分析搜尋結果需要查哪些 API
    # key = (type, region)，去重
    queries_needed = set()

    for lot in results:
        parking_type = lot["type"]
        region = lot["region"]

        if parking_type in API_ENDPOINTS:
            endpoint = API_ENDPOINTS[parking_type]
            if endpoint["param_key"]:
                queries_needed.add((parking_type, region))
            else:
                queries_needed.add((parking_type, "__ALL__"))

    # 合併所有查詢結果
    all_availability = {}

    # TDX API 查詢
    if not _tdx_auth.is_ready and queries_needed:
        print("  ⚠️ TDX API 未設定，跳過 TDX 即時車位查詢")
    else:
        for query_key in queries_needed:
            parking_type, region = query_key

            cached = _avail_cache.get(query_key)
            if cached is not None:
                all_availability.update(cached)
                print(f"  📦 快取命中: {parking_type}/{region}")
                continue

            actual_region = "" if region == "__ALL__" else region
            print(f"  🌐 查詢即時車位: {parking_type}/{actual_region or '全部'}...")
            avail_data = _fetch_availability_from_api(parking_type, actual_region)

            if avail_data:
                _avail_cache.set(query_key, avail_data)
                all_availability.update(avail_data)
                print(f"  ✅ 取得 {len(avail_data)} 筆即時資料")

    # ★ 新北市路外停車場：如果 TDX 沒有對應資料，使用 NTPC API 當作 Fallback
    need_ntpc_fallback = any(
        lot["type"] == "市區路外" and lot["region"] == "NewTaipei" and lot["id"] not in all_availability
        for lot in results
    )

    if need_ntpc_fallback:
        cache_key = ("新北路外", "__NTPC_FALLBACK__")
        cached = _avail_cache.get(cache_key)
        ntpc_data = None
        if cached is not None:
            ntpc_data = cached
            print(f"  📦 快取命中: 新北市路外 (Fallback)")
        else:
            print(f"  🌐 查詢新北市即時車位 (NTPC API Fallback)...")
            ntpc_data = _fetch_newtaipei_availability()
            if ntpc_data:
                _avail_cache.set(cache_key, ntpc_data)
        
        if ntpc_data:
            fallback_count = 0
            for pid, pdata in ntpc_data.items():
                if pid not in all_availability:
                    all_availability[pid] = pdata
                    fallback_count += 1
            if fallback_count > 0:
                print(f"  ✅ 成功從 NTPC Fallback 補足 {fallback_count} 筆車位資料")

    return all_availability


# ============================================================
# 6. 核心搜尋函式 (階段三升級)
# ============================================================
def find_nearest_parking(
    user_lat: float,
    user_lng: float,
    top_n: int = DEFAULT_TOP_N,
    parking_type: Optional[str] = None,
    include_availability: bool = False,
    db_path: str = DB_PATH,
) -> dict:
    """
    核心搜尋：在指定座標附近找到最近的停車場。
    
    搜尋策略：
    1. 先用 Bounding Box 從 SQLite 粗篩候選停車場
    2. 再用 Haversine 精算距離
    3. 若找不到結果，自動擴大搜尋半徑 (Fallback)
    4. ★ (v2.0) 可選擇串接即時車位資料
    
    Args:
        user_lat:             使用者緯度
        user_lng:             使用者經度
        top_n:                回傳最近 N 筆結果
        parking_type:         停車場類型篩選，None=全部
        include_availability: ★ 是否查詢即時剩餘車位
        db_path:              SQLite 資料庫路徑
    
    Returns:
        dict: {
            "success": bool,
            "search_radius_km": float,
            "total_candidates": int,
            "results": list[dict],
            "message": str,
        }
    """
    if not os.path.exists(db_path):
        return {
            "success": False,
            "search_radius_km": 0,
            "total_candidates": 0,
            "results": [],
            "message": "❌ 資料庫尚未建立，請先執行 init_database()",
        }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    for radius_km in FALLBACK_RADII_KM:
        min_lat, max_lat, min_lng, max_lng = bounding_box(user_lat, user_lng, radius_km)

        query = """
            SELECT id, name, lat, lng, type, region, rate_info, ev_charging, address
            FROM parking_lots
            WHERE lat BETWEEN ? AND ?
              AND lng BETWEEN ? AND ?
        """
        params = [min_lat, max_lat, min_lng, max_lng]

        if parking_type:
            query += " AND type = ?"
            params.append(parking_type)

        candidates = conn.execute(query, params).fetchall()

        if not candidates:
            continue

        # 精篩：Haversine 距離與進階去重 (Deduplication)
        # 因為台鐵資料庫 (TRA) 跟新北資料庫 (NewTaipei) 會有重複的車站停車場 (如: 板橋車站地下停車場)
        results = []
        for row in candidates:
            dist_km = haversine(user_lat, user_lng, row["lat"], row["lng"])
            if dist_km <= radius_km:
                new_lot = {
                    "id": row["id"],
                    "name": row["name"],
                    "lat": row["lat"],
                    "lng": row["lng"],
                    "distance_m": round(dist_km * 1000),
                    "distance_km": round(dist_km, 2),
                    "type": row["type"],
                    "region": row["region"],
                    "rate_info": row["rate_info"],
                    "ev_charging": row["ev_charging"],
                    "address": row["address"],
                    "total_spaces": None,
                    "available_spaces": None,
                    "service_status": None,
                }
                
                # ── 去重邏輯：如果 150m 內已經有名字高相似度 (或互相包含) 的停車場，視為同一個 ──
                import difflib
                is_dup = False
                for existing in results:
                    dist_between = haversine(existing["lat"], existing["lng"], new_lot["lat"], new_lot["lng"]) * 1000
                    if dist_between < 150:
                        # 計算名稱相似度或互相包含
                        n1, n2 = new_lot["name"], existing["name"]
                        sim = difflib.SequenceMatcher(None, n1, n2).ratio()
                        if sim > 0.6 or n1 in n2 or n2 in n1:
                            is_dup = True
                            # 依照使用者需求：優先保留 TDX 的原生來源 (例如軌道車站 TRA/THSR)，若有重複則覆蓋新北市資料
                            if existing["region"] == "NewTaipei" and new_lot["region"] != "NewTaipei":
                                # 取代舊的
                                existing.update(new_lot)
                            break
                
                if not is_dup:
                    results.append(new_lot)

        if results:
            results.sort(key=lambda x: x["distance_m"])
            top_results = results[:top_n]

            conn.close()

            # ★ 階段三：查詢即時車位
            if include_availability:
                availability = fetch_availability_for_results(top_results)
                for lot in top_results:
                    avail_info = availability.get(lot["id"])
                    if avail_info:
                        lot["total_spaces"] = avail_info["total"]
                        lot["available_spaces"] = avail_info["available"]
                        lot["service_status"] = avail_info["service_status"]

            return {
                "success": True,
                "search_radius_km": radius_km,
                "total_candidates": len(results),
                "results": top_results,
                "message": (
                    f"📍 在 {radius_km}km 內找到 {len(results)} 間停車場，"
                    f"顯示最近 {len(top_results)} 間"
                ),
            }

    conn.close()
    return {
        "success": False,
        "search_radius_km": FALLBACK_RADII_KM[-1],
        "total_candidates": 0,
        "results": [],
        "message": f"😢 在 {FALLBACK_RADII_KM[-1]}km 範圍內找不到停車場",
    }


# ============================================================
# 7. 結果格式化輸出 (階段三升級)
# ============================================================
def _format_availability(lot: dict) -> str:
    """格式化單一停車場的即時車位資訊。"""
    total = lot.get("total_spaces")
    available = lot.get("available_spaces")
    status = lot.get("service_status")

    # 沒有即時資料
    if total is None and available is None:
        return "   🔘 即時車位: 未提供"

    # 服務狀態判斷 (0=未知, 1=正常, 2=暫停)
    if status == 2:
        return "   ⚫ 即時車位: 暫停服務"

    # 有效資料
    if available is not None and total is not None and total > 0:
        occupancy_pct = round((total - available) / total * 100)
        free_pct = 100 - occupancy_pct

        if available <= 0:
            indicator = "🔴"
            label = "已滿"
        elif free_pct <= 15:
            indicator = "🟡"
            label = f"{available} / {total} (即將滿)"
        else:
            indicator = "🟢"
            label = f"{available} / {total} ({free_pct}% 空)"

        return f"   {indicator} 即時空位: {label}"

    elif available is not None and available >= 0:
        # 只有 available，沒有 total
        if available <= 0:
            return "   🔴 即時空位: 已滿"
        else:
            return f"   🟢 即時空位: {available} 格"

    return "   🔘 即時車位: 資料異常"


def format_results(result: dict) -> str:
    """
    將搜尋結果格式化為人類可讀文字，方便 CLI 測試和 LINE Bot 訊息組裝。
    """
    lines = [result["message"], ""]

    if not result["success"]:
        lines.append("建議擴大搜尋範圍或移動到其他位置再試一次。")
        return "\n".join(lines)

    lines.append(f"🔍 搜尋半徑: {result['search_radius_km']}km | 候選數: {result['total_candidates']}")
    lines.append("=" * 50)

    for i, lot in enumerate(result["results"], 1):
        ev_badge = "⚡" if lot["ev_charging"] and lot["ev_charging"] != "無" else ""

        # 基本資訊
        block = (
            f"\n🅿️ #{i} {lot['name']} {ev_badge}\n"
            f"   📏 距離: {lot['distance_m']}m ({lot['distance_km']}km)\n"
        )

        # ★ 即時車位資訊 (階段三)
        if lot.get("total_spaces") is not None or lot.get("available_spaces") is not None:
            block += _format_availability(lot) + "\n"

        # 其他資訊
        block += (
            f"   🏷️ 類型: {lot['type']}\n"
            f"   📍 地區: {lot['region']}\n"
            f"   💰 費率: {lot['rate_info'] or '未提供'}\n"
            f"   📮 地址: {lot['address'] or '未提供'}"
        )

        lines.append(block)

    return "\n".join(lines)


# ============================================================
# 8. 資料庫統計
# ============================================================
def get_db_stats(db_path: str = DB_PATH) -> str:
    """取得資料庫統計資訊。"""
    if not os.path.exists(db_path):
        return "❌ 資料庫不存在"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    total = cursor.execute("SELECT COUNT(*) FROM parking_lots").fetchone()[0]
    by_type = cursor.execute(
        "SELECT type, COUNT(*) as cnt FROM parking_lots GROUP BY type ORDER BY cnt DESC"
    ).fetchall()

    lines = [
        f"📊 停車場資料庫統計",
        f"{'=' * 40}",
        f"總筆數: {total}",
        f"\n各類型停車場數量:",
    ]
    for type_name, count in by_type:
        pct = count / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 2)
        lines.append(f"  {type_name:8s} | {count:5d} 筆 | {pct:5.1f}% {bar}")

    conn.close()
    return "\n".join(lines)


# ============================================================
# 9. 互動式 CLI 測試介面 (階段三升級)
# ============================================================
def interactive_test():
    """互動式測試介面：輸入座標查詢附近停車場 + 即時車位。"""

    print("=" * 60)
    print("🚗 全台即時停車場雷達 - 空間搜尋引擎 v2.0")
    print("   ★ 新功能：即時剩餘車位查詢")
    print("=" * 60)

    # 建置資料庫
    print("\n📦 初始化資料庫...")
    report = init_database()
    print(report)

    # 顯示統計
    print(f"\n{get_db_stats()}")

    # TDX 狀態
    if _tdx_auth.is_ready:
        print("\n🔑 TDX API: ✅ 金鑰已設定")
    else:
        print("\n🔑 TDX API: ❌ 未設定 (即時車位功能停用)")

    # 預設測試座標
    test_cases = [
        ("台北車站", 25.0478, 121.5170),
        ("台中火車站", 24.1368, 120.6849),
        ("高雄車站", 22.6394, 120.3025),
        ("花蓮車站", 23.9934, 121.6012),
        ("墾丁大街", 21.9458, 120.7872),
    ]

    print("\n" + "=" * 60)
    print("📍 預設測試座標：")
    for i, (name, lat, lng) in enumerate(test_cases, 1):
        print(f"  {i}. {name} ({lat}, {lng})")
    print(f"  0. 自行輸入座標")
    print("  q. 結束程式")
    print("=" * 60)

    while True:
        choice = input("\n請選擇測試點 (0-5, q=離開): ").strip()

        if choice.lower() == "q":
            print("👋 掰掰！")
            break

        if choice == "0":
            try:
                lat = float(input("  輸入緯度 (lat): "))
                lng = float(input("  輸入經度 (lng): "))
                name = "自訂座標"
            except ValueError:
                print("  ❌ 請輸入有效數字")
                continue
        elif choice in [str(i) for i in range(1, len(test_cases) + 1)]:
            name, lat, lng = test_cases[int(choice) - 1]
        else:
            print("  ❌ 無效選擇")
            continue

        # 詢問是否篩選類型
        type_filter = input("  篩選停車場類型 (Enter=全部, 1=市區路外, 2=市區路邊): ").strip()
        type_map = {"1": "市區路外", "2": "市區路邊"}
        parking_type = type_map.get(type_filter)

        # ★ 詢問是否查即時車位
        live_input = input("  查詢即時剩餘車位？ (Y/n): ").strip().lower()
        include_live = live_input != "n"

        print(f"\n🔍 搜尋 {name} ({lat}, {lng}) 附近停車場...")
        if include_live:
            print("📡 同步查詢即時車位資料...")

        result = find_nearest_parking(
            lat, lng,
            parking_type=parking_type,
            include_availability=include_live,
        )
        print(format_results(result))


# ============================================================
# 主程式進入點
# ============================================================
if __name__ == "__main__":
    interactive_test()
