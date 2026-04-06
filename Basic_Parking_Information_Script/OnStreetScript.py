import requests
import csv
import time

CLIENT_ID = "11336002-4513092c-90da-4770"
CLIENT_SECRET = "97e0b9d8-bb5c-41cf-827c-9278e6b5b038"

# 你指定有提供路邊停車資料的 11 個縣市
cities = [
    "Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung", 
    "HsinchuCounty", "ChanghuaCounty", "PingtungCounty", "HualienCounty", "PenghuCounty"
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
    print("✅ 成功取得通行證！準備開始掃描【全台路邊停車格】...\n")
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    all_clean_data = [] 
    top = 1000          

    for city in cities:
        print(f"🚀 開始抓取縣市：【{city}】")
        skip = 0            
        page = 1 
        
        while True:
            # 💡【注意】這裡的網址改成了 OnStreet 跟 ParkingSegment
            url = f"https://tdx.transportdata.tw/api/basic/v1/Parking/OnStreet/ParkingSegment/City/{city}?$top={top}&$skip={skip}&$format=JSON"
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                
                # 💡【注意】抓取的陣列名稱變成了 ParkingSegments
                segment_list = data.get("ParkingSegments", []) 
                
                if len(segment_list) == 0:
                    print(f"🏁 【{city}】的路邊停車資料已全數抓完！\n" + "-"*30)
                    time.sleep(1) 
                    break
                    
                for segment in segment_list:
                    try:
                        # 對應新的 JSON 欄位名稱
                        segment_id = segment.get("ParkingSegmentID", "未知ID")
                        name = segment.get("ParkingSegmentName", {}).get("Zh_tw", "無名稱")
                        lat = segment.get("ParkingSegmentPosition", {}).get("PositionLat", 0)
                        lng = segment.get("ParkingSegmentPosition", {}).get("PositionLon", 0)
                        fare = segment.get("FareDescription", "無費率資訊")
                        description = segment.get("Description", "無位置描述") # 路邊停車通常用 Description 描述在哪條路
                        
                        # 處理充電樁 (HasChargingPoint)
                        ev_flag = segment.get("HasChargingPoint", 0)
                        ev_status = "有" if ev_flag == 1 else "無"

                        all_clean_data.append([city, segment_id, name, lat, lng, fare, ev_status, description])
                    except Exception:
                        continue 
                
                skip += top
                page += 1
                time.sleep(5) 
                
            elif response.status_code == 429:
                print("⚠️ 抓太快啦！觸發 API 頻率限制 (429)，休息 5 秒後自動重試...")
                time.sleep(20)
                continue 
                
            else:
                print(f"❌ 抓取 {city} 發生錯誤，狀態碼：{response.status_code}，跳過此縣市。")
                break

    # 存成路邊停車專用的 CSV 檔案
    filename = "taiwan_onstreet_parking.csv"
    with open(filename, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["縣市", "路段ID", "路段名稱", "緯度", "經度", "費率資訊", "電動車充電樁", "位置描述"]) 
        writer.writerows(all_clean_data) 

    print(f"🎉 任務圓滿結束！")
    print(f"總共收集了 {len(all_clean_data)} 筆全台路邊停車資料，檔案已存為 {filename}")

else:
    print(f"❌ 申請通行證失敗，請檢查你的 ID 和 Secret！")