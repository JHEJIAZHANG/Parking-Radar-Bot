"""
全台即時停車場雷達 - LINE Bot
"""

import os
import logging
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, FlexMessage, FlexContainer,
    QuickReply, QuickReplyItem, LocationAction
)
from datetime import datetime, timezone, timedelta
from linebot.v3.webhooks import MessageEvent, LocationMessageContent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

from parking_finder import init_database, find_nearest_parking

# ── 環境設定 ──
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

app = FastAPI(title="停車雷達", version="3.0")
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_database()
logger.info("資料庫已載入")


# ════════════════════════════════════════════════════════════
#  Flex Message
# ════════════════════════════════════════════════════════════

# 系統色（不用 emoji，改用文字 + 色彩表達）
IOS_BLUE   = "#007AFF"
IOS_GREEN  = "#34C759"
IOS_ORANGE = "#FF9500"
IOS_RED    = "#FF3B30"
IOS_GRAY   = "#8E8E93"
IOS_GRAY2  = "#AEAEB2"
IOS_GRAY5  = "#E5E5EA"
IOS_GRAY6  = "#F2F2F7"
IOS_BLACK  = "#1C1C1E"
IOS_BLACK2 = "#3A3A3C"


def _type_label(t):
    """停車場類型的簡潔標籤"""
    return {
        "市區路外": "路外",
        "市區路邊": "路邊",
        "觀光景點": "觀光",
        "軌道車站": "車站",
        "國道休息站": "國道",
        "航空站": "機場",
    }.get(t, t)


def _type_color(t):
    """類型的主題色"""
    return {
        "市區路外": IOS_BLUE,
        "市區路邊": IOS_RED,
        "觀光景點": IOS_GREEN,
        "軌道車站": IOS_ORANGE,
        "國道休息站": "#5AC8FA",
        "航空站": "#AF52DE",
    }.get(t, IOS_GRAY)


def _avail_section(lot):
    """車位狀態區塊 — 完美融入 Ticket 款式的純淨文字與進度條"""
    total = lot.get("total_spaces")
    avail = lot.get("available_spaces")
    status = lot.get("service_status")

    if status == 2:
        return {
            "type": "box", "layout": "vertical",
            "margin": "md",
            "contents": [
                {"type": "text", "text": "暫停服務", "size": "sm",
                 "color": IOS_GRAY, "weight": "bold", "align": "start"},
            ],
        }

    if avail is not None and avail >= 0:
        # 顏色與標籤判斷 (依據剩餘比例)
        if avail <= 0:
            c, tag = IOS_RED, "已滿"
        elif total and total > 0 and (avail / total) <= 0.15:
            c, tag = IOS_ORANGE, "席位變少"
        else:
            c, tag = IOS_BLUE, "有空位"

        num_text = str(avail)
        sub_text = f" / {total}" if total and total > 0 else " 格"

        # Receipt 型內容：無底色，乾淨俐落
        inner = [
            {
                "type": "box", "layout": "horizontal", 
                "alignItems": "flex-end",
                "contents": [
                    {"type": "text", "text": tag, "size": "md",
                     "color": c, "weight": "bold", "flex": 0},
                    {"type": "filler"},
                    {"type": "text", "text": num_text, "size": "3xl",
                     "color": c, "weight": "bold", "align": "end", "flex": 0},
                    {"type": "text", "text": sub_text, "size": "sm",
                     "color": IOS_GRAY2, "weight": "bold", "align": "end", "flex": 0, "margin": "sm", "gravity": "bottom"},
                ],
            },
        ]

        # 進度條
        if total and total > 0:
            pct = 0
            if avail > 0:
                pct = max(2, min(100, round((avail / total) * 100)))
                
            inner.append({
                "type": "box", "layout": "vertical", "margin": "md",
                "height": "4px", "cornerRadius": "md",
                "backgroundColor": IOS_GRAY5,
                "contents": [{
                    "type": "box", "layout": "vertical",
                    "height": "4px", "cornerRadius": "md",
                    "width": f"{pct}%",
                    "backgroundColor": c,
                    "contents": [{"type": "filler"}],
                }],
            })

        return {
            "type": "box", "layout": "vertical",
            "margin": "md",
            "contents": inner,
        }

    # 無資料
    return {
        "type": "box", "layout": "vertical",
        "margin": "md",
        "contents": [
            {"type": "text", "text": "即時資料未提供", "size": "sm",
             "color": IOS_GRAY2, "align": "start"},
        ],
    }


def _info_row(label, value):
    """資訊列"""
    return {
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "margin": "md",
        "contents": [
            {"type": "text", "text": label, "size": "xs",
             "color": IOS_GRAY, "flex": 0, "gravity": "top", "weight": "bold"},
            {"type": "text", "text": value, "size": "xs",
             "color": IOS_BLACK2, "wrap": True, "maxLines": 2},
        ],
    }


def build_parking_bubble(lot, idx):
    """Ticket 票根風格停車場卡片"""
    import urllib.parse
    
    ev = " ⚡" if lot.get("ev_charging") and lot["ev_charging"] != "無" else ""
    color = _type_color(lot["type"])
    dist = f'{lot["distance_m"]}m' if lot["distance_m"] < 1000 else f'{lot["distance_km"]}km'
    label = _type_label(lot["type"])

    rate = lot.get("rate_info") or "未提供"
    if len(rate) > 50:
        rate = rate[:47] + "..."
    addr = lot.get("address") or "未提供"
    if len(addr) > 35:
        addr = addr[:32] + "..."

    if lot.get("address") and lot.get("address") not in ["未提供", "無", ""]:
        search_query = f"{lot['name']} {lot['address']}"
        encoded_query = urllib.parse.quote(search_query)
        navigation_url = f"https://www.google.com/maps/dir/?api=1&destination={encoded_query}"
    else:
        navigation_url = f"https://www.google.com/maps/dir/?api=1&destination={lot['lat']},{lot['lng']}"

    return {
        "type": "bubble", "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": color,
            "paddingAll": "20px", "paddingBottom": "24px",
            "contents": [
                {
                    "type": "box", "layout": "horizontal", "alignItems": "center",
                    "contents": [
                        {"type": "text", "text": label, "size": "sm", "color": "#FFFFFF", "weight": "bold"},
                        {"type": "filler"},
                        {"type": "text", "text": dist, "size": "sm", "color": "#FFFFFF", "weight": "bold", "align": "end"},
                    ]
                },
                {
                    "type": "text", "text": f"{lot['name']}{ev}", "size": "xl", "color": "#FFFFFF", "weight": "bold",
                    "wrap": True, "margin": "lg"
                }
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "paddingAll": "20px", "spacing": "sm",
            "backgroundColor": "#FFFFFF",
            "contents": [
                _avail_section(lot),
                {"type": "separator", "color": IOS_GRAY5, "margin": "lg"},
                _info_row("費率", rate),
                {"type": "separator", "color": IOS_GRAY5, "margin": "md"},
                _info_row("地址", addr),
                {"type": "separator", "color": IOS_GRAY5, "margin": "md"},
                _info_row("時間", datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")),
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "paddingStart": "20px", "paddingEnd": "20px",
            "paddingTop": "0px", "paddingBottom": "20px",
            "contents": [{
                "type": "button",
                "style": "secondary", "color": IOS_GRAY6,
                "height": "sm",
                "action": {
                    "type": "uri",
                    "label": "導航到此處",
                    "uri": navigation_url,
                },
            }],
        },
    }


def build_flex_carousel(result):
    """搜尋結果輪播"""
    r = result["search_radius_km"]
    total = result["total_candidates"]
    shown = len(result["results"])

    summary = {
        "type": "bubble", "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": IOS_BLACK2,
            "paddingAll": "20px", "paddingBottom": "24px",
            "contents": [
                {"type": "text", "text": "停車雷達", "size": "xl", 
                 "color": "#FFFFFF", "weight": "bold", "align": "center"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "paddingAll": "20px", "spacing": "sm",
            "backgroundColor": "#FFFFFF",
            "justifyContent": "center",
            "contents": [
                {
                    "type": "box", "layout": "vertical",
                    "margin": "md", "spacing": "sm",
                    "contents": [
                        _info_row("搜尋半徑", f"{r} km"),
                        _info_row("找到", f"{total} 間停車場"),
                        _info_row("目前檢視", f"最近 {shown} 間"),
                    ]
                },
                {"type": "text", "text": "← 向左滑動查看 →", "size": "xs",
                 "color": IOS_GRAY, "align": "center", "margin": "xl"},
            ],
        },
    }

    bubbles = [build_parking_bubble(lot, i) for i, lot in enumerate(result["results"], 1)]
    return {"type": "carousel", "contents": [summary] + bubbles}


def build_no_result_flex():
    """找不到結果"""
    return {
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical",
            "paddingAll": "32px", "spacing": "lg",
            "justifyContent": "center", "alignItems": "center",
            "contents": [
                {"type": "text", "text": "無停車場資料", "size": "lg",
                 "weight": "bold", "color": IOS_BLACK, "align": "center"},
                {
                    "type": "box", "layout": "vertical",
                    "backgroundColor": "#F9F9F9", "cornerRadius": "lg",
                    "paddingAll": "16px", "margin": "xl",
                    "contents": [
                        {"type": "text", "text": "3 公里內沒有找到停車場",
                         "size": "sm", "color": IOS_GRAY, "align": "center"},
                        {"type": "text", "text": "請嘗試移動到其他位置",
                         "size": "sm", "color": IOS_BLUE, "align": "center",
                         "margin": "md"},
                    ],
                },
            ],
        },
    }


# ════════════════════════════════════════════════════════════
#  Webhook
# ════════════════════════════════════════════════════════════

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"


@handler.add(MessageEvent, message=LocationMessageContent)
def handle_location(event):
    lat = event.message.latitude
    lng = event.message.longitude
    logger.info(f"位置: ({lat}, {lng})")

    try:
        result = find_nearest_parking(
            user_lat=lat, user_lng=lng,
            top_n=10, include_availability=True,
        )

        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)
            if result["success"]:
                flex = build_flex_carousel(result)
                api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[FlexMessage(
                        alt_text=f"找到 {result['total_candidates']} 間停車場",
                        contents=FlexContainer.from_dict(flex),
                    )],
                ))
            else:
                api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[FlexMessage(
                        alt_text="附近找不到停車場",
                        contents=FlexContainer.from_dict(build_no_result_flex()),
                    )],
                ))
    except Exception as e:
        logger.error(f"處理位置訊息錯誤: {e}")
        logger.error(traceback.format_exc())
        # 嘗試回覆錯誤訊息
        try:
            with ApiClient(configuration) as api_client:
                api = MessagingApi(api_client)
                api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="搜尋中遇到問題，請稍後再試一次")],
                ))
        except Exception:
            pass


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    welcome_flex = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "30px",
            "backgroundColor": "#FFFFFF",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "alignItems": "center",
                    "margin": "xl",
                    "contents": [
                        {"type": "text", "text": "📍", "size": "4xl"}
                    ]
                },
                {
                    "type": "text",
                    "text": "即時停車雷達",
                    "size": "xl",
                    "weight": "bold",
                    "color": IOS_BLACK,
                    "align": "center",
                    "margin": "lg"
                },
                {
                    "type": "text",
                    "text": "請點擊下方按鈕，或透過「＋」傳送位置資訊，我會幫您找到附近的停車場與即時車位！",
                    "size": "sm",
                    "color": IOS_GRAY,
                    "wrap": True,
                    "align": "center"
                },
                {
                    "type": "separator",
                    "color": IOS_GRAY5,
                    "margin": "xl"
                },
                {
                    "type": "text",
                    "text": "【免責聲明】\n本服務車位資料源自政府開放資料平台(TDX/NTPC)，即時數量僅供參考，實際狀況與費率請以各停車場現場公告為準。",
                    "size": "xs",
                    "color": IOS_GRAY2,
                    "wrap": True,
                    "align": "start",
                    "margin": "lg"
                }
            ]
        }
    }
    
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[FlexMessage(
                alt_text="請傳送位置給我",
                contents=FlexContainer.from_dict(welcome_flex),
                quick_reply=QuickReply(items=[
                    QuickReplyItem(
                        action=LocationAction(label="📍 傳送目前位置")
                    )
                ])
            )]
        ))


@app.get("/")
async def health():
    return {"status": "ok", "version": "3.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Bot 啟動 port={port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
