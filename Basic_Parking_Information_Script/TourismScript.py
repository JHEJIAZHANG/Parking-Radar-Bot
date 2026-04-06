import requests
import csv
import time

CLIENT_ID = "11336002-4513092c-90da-4770"
CLIENT_SECRET = "97e0b9d8-bb5c-41cf-827c-9278e6b5b038"

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
    print("✅ 成功取得通行證！準備開始掃描【全台觀光景點停車場】...\n")
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    all_clean_data = [] 
    top = 1000          
    skip = 0            
    page = 1 
    
    # 這裡只需要一個迴圈一直翻頁就好！
    while True:
        url = f"https://tdx.transportdata.tw/api/basic/v1/Parking/OffStreet/CarPark/Tourism?$top={top}&$skip={skip}&$format=JSON"
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            park_list = data.get("CarParks", []) 
            
            if len(park_list) == 0:
                print(f"🏁 全台觀光景點停車場已全數抓完！\n")
                break
                
            for park in park_list:
                try:
                    park_id = park.get("CarParkID", "未知ID")
                    name = park.get("CarParkName", {}).get("Zh_tw", "無名稱")
                    lat = park.get("CarParkPosition", {}).get("PositionLat", 0)
                    lng = park.get("CarParkPosition", {}).get("PositionLon", 0)
                    fare = park.get("FareDescription", "無費率資訊")
                    address = park.get("Address", "無地址資訊")
                    
                    # 觀光 API 裡面其實有附上 City 欄位，我們把它抓出來用
                    city = park.get("City", "未知縣市") 
                    
                    ev_flag = park.get("EVRechargingAvailable", 0)
                    ev_status = "有" if ev_flag == 1 else "無"

                    all_clean_data.append([city, park_id, name, lat, lng, fare, ev_status, address])
                except Exception:
                    continue 
            
            skip += top
            page += 1
            time.sleep(1) 
            
        elif response.status_code == 429:
            print("⚠️ 觸發 API 頻率限制 (429)，休息 5 秒後自動重試...")
            time.sleep(5)
            continue 
            
        else:
            print(f"❌ 發生錯誤，狀態碼：{response.status_code}")
            break

    # 存成觀光景點專用的 CSV 檔案
    filename = "taiwan_tourism_parking.csv"
    with open(filename, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["縣市", "停車場ID", "停車場名稱", "緯度", "經度", "費率資訊", "電動車充電樁", "地址"]) 
        writer.writerows(all_clean_data) 

    print(f"🎉 任務圓滿結束！")
    print(f"總共收集了 {len(all_clean_data)} 筆全台觀光景點停車資料，檔案已存為 {filename}")

else:
    print(f"❌ 申請通行證失敗，請檢查你的 ID 和 Secret！")