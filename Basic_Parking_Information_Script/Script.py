import requests
import csv
import time  

# ==========================================
# 1. 請填寫你從 TDX 申請到的 API 金鑰
# ==========================================
CLIENT_ID = "11336002-4513092c-90da-4770"
CLIENT_SECRET = "97e0b9d8-bb5c-41cf-827c-9278e6b5b038"

# 1. 建立城市陣列 (你剛剛貼的所有縣市)
cities = [
    "Taipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung", "Keelung", 
    "Hsinchu", "HsinchuCounty", "MiaoliCounty", "ChanghuaCounty", 
    "NantouCounty", "YunlinCounty", "ChiayiCounty", "Chiayi", 
    "PingtungCounty", "YilanCounty", "HualienCounty", "TaitungCounty", 
    "KinmenCounty", "PenghuCounty", "LienchiangCounty"
]

print("🔑 正在向 TDX 申請通行證...")
auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
auth_data = {
    "grant_type": "client_credentials",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET
}

auth_response = requests.post(auth_url, data=auth_data)

if auth_response.status_code == 200:
    access_token = auth_response.json().get("access_token")
    print("✅ 成功取得通行證！準備開始【全台大掃描】...\n")
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    all_clean_data = [] # 這個大箱子現在要裝全台灣的資料了
    top = 1000          

    # 2. 外層迴圈：開始一個一個城市去抓
    for city in cities:
        print(f"🚀 開始抓取縣市：【{city}】")
        skip = 0            
        page = 1 
        
        # 內層迴圈：處理該城市的「分頁」
        while True:
            url = f"https://tdx.transportdata.tw/api/basic/v1/Parking/OffStreet/CarPark/City/{city}?$top={top}&$skip={skip}&$format=JSON"
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                park_list = data.get("CarParks", data) 
                
                # 如果該縣市這頁沒資料了，就換下一個縣市 (break 跳出內層迴圈)
                if len(park_list) == 0:
                    print(f"🏁 【{city}】的資料已全數抓完！\n" + "-"*30)
                    break
                    
                for park in park_list:
                    try:
                        park_id = park.get("CarParkID", "未知ID")
                        name = park.get("CarParkName", {}).get("Zh_tw", "無名稱")
                        lat = park.get("CarParkPosition", {}).get("PositionLat", 0)
                        lng = park.get("CarParkPosition", {}).get("PositionLon", 0)
                        fare = park.get("FareDescription", "無費率資訊")
                        address = park.get("Address", "無地址資訊")
                        
                        ev_flag = park.get("EVRechargingAvailable", 0)
                        ev_status = "有" if ev_flag == 1 else "無"

                        # 💡 【重要】把 city 變數也一起存進去，這樣才知道是哪個縣市的
                        all_clean_data.append([city, park_id, name, lat, lng, fare, ev_status, address])
                    except Exception:
                        continue 
                
                skip += top
                page += 1
                time.sleep(25) # 💡【新增】換縣市的時候也強制休息 1 秒
            elif response.status_code == 429:
                # 💡【新增】防護機制：遇到 429 頻率限制，就深呼吸休息 5 秒，然後「不要增加 skip」，迴圈會自動重試同一個網址！
                print("⚠️ 抓太快啦！觸發 API 頻率限制 (429)，休息 5 秒後自動重試...")
                time.sleep(25)
                continue
                
            else:
                # 遇到錯誤只會跳過這個縣市，不會整個程式當掉
                print(f"⚠️ 抓取 {city} 發生錯誤，狀態碼：{response.status_code}，跳過此縣市。")
                break

    # 3. 所有城市都跑完後，一口氣存成一個全台大檔案
    filename = "taiwan_all_parking_pro.csv"
    with open(filename, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        # 標題多了一個「縣市」
        writer.writerow(["縣市", "停車場ID", "停車場名稱", "緯度", "經度", "費率資訊", "電動車充電樁", "地址"]) 
        writer.writerows(all_clean_data) 

    print(f"🎉 太神啦！任務圓滿結束！")
    print(f"總共收集了 {len(all_clean_data)} 筆全台停車場資料，檔案已存為 {filename}")

else:
    print(f"❌ 申請通行證失敗，請檢查你的 ID 和 Secret！")