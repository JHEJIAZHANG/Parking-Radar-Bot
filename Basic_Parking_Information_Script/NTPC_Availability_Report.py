import pandas as pd
import requests

# 1. 讀取新北市路外停車場靜態資料
STATIC_CSV_PATH = '/Users/jhejia/Desktop/Parking Information/Basic_Parking_Information_Script/taiwan_newtaipei_offstreet.csv'

try:
    df_static = pd.read_csv(STATIC_CSV_PATH)
except Exception as e:
    print(f"Error reading CSV: {e}")
    exit(1)

print(f"📊 靜態資料總計: {len(df_static)} 筆")

# 2. 爬取新北市政府即時車位 API
API_URL = "https://data.ntpc.gov.tw/api/datasets/e09b35a5-a738-48cc-b0f5-570b67ad9c78/json?size=2000"

all_data = []
page = 0
print("🌐 正在爬取即時車位資料...")
while True:
    url = f"{API_URL}&page={page}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if not data:
            break
        all_data.extend(data)
        if len(data) < 1000:
            break
        page += 1
    except Exception as e:
        print(f"Error fetching API: {e}")
        break

print(f"✅ 從 API 取得 {len(all_data)} 筆即時車位資料")

df_api = pd.DataFrame(all_data)

if not df_api.empty and 'ID' in df_api.columns:
    # 處理 AVAILABLECAR 欄位
    df_api['AVAILABLECAR'] = pd.to_numeric(df_api['AVAILABLECAR'], errors='coerce')
    
    # 確保 ID 皆為字串型態以利比對
    df_static['停車場ID'] = df_static['停車場ID'].astype(str).str.strip().str.zfill(6)
    df_api['ID'] = df_api['ID'].astype(str).str.strip()
    
    # 3. 合併資料表 (Left Join)
    df_merged = pd.merge(df_static, df_api[['ID', 'AVAILABLECAR']], left_on='停車場ID', right_on='ID', how='left')
    
    # 整理欄位
    display_cols = ['停車場ID', '停車場名稱', '地址', 'AVAILABLECAR']
    df_merged = df_merged[display_cols].copy()
    
    # 重新命名與清理
    df_merged.rename(columns={'AVAILABLECAR': '即時剩餘車位'}, inplace=True)
    df_merged.drop_duplicates(subset=['停車場ID'], inplace=True)
    df_merged['即時剩餘車位'] = df_merged['即時剩餘車位'].fillna(-1).astype(int)
    
    # 視覺排版優化
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    pd.set_option('display.unicode.ambiguous_as_wide', True)
    pd.set_option('display.unicode.east_asian_width', True)
    
    # 過濾出有車位資料的，並展示前 15 筆
    print("\n========== 新北市停車場即時剩餘車位總表 (範例 15 筆) ==========")
    df_show = df_merged[df_merged['即時剩餘車位'] >= 0].sort_values(by='即時剩餘車位', ascending=False)
    print(df_show.head(15).to_string(index=False))
    
    # 分析有多少間車位滿了 / 有空位的
    full_count = len(df_show[df_show['即時剩餘車位'] == 0])
    avail_count = len(df_show[df_show['即時剩餘車位'] > 0])
    print(f"\n📈 統計結果: 有空位停車場 {avail_count} 間, 已客滿停車場 {full_count} 間.")
    
    # 4. 存檔
    out_path = '/Users/jhejia/Desktop/Parking Information/Basic_Parking_Information_Script/NTPC_Availability_Report.csv'
    df_merged.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"💾 完整對照表已儲存至: {out_path}\n")
else:
    print("❌ API 資料解析失敗！")
