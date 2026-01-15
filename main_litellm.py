import os
import json
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

import ssl

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# 載入環境變數
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 讀取 LiteLLM 的設定
LITELLM_ENDPOINT = os.getenv("LITELLM_ENDPOINT")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY")

# --- 模擬護欄邏輯 (Guardrail) ---
async def check_content_safety(text: str) -> bool:
    """
    這裡是你未來的護欄邏輯。
    目前先設定為總是通過，但你可以加上關鍵字過濾或呼叫另一個 API。
    """
    # 範例：如果出現 "比特幣"，視為違規
    if "比特幣" in text:
        print(f"⚠️ 護欄攔截敏感詞: {text}")
        return False
    return True
# ------------------------------

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(client_ws: WebSocket):
    await client_ws.accept()
    print("✅ WMS 前端已連線")

    # 設定連接 LiteLLM 的 Header
    # 注意：這裡是用 Bearer Token，因為是對 LiteLLM 認證
    headers = {
        "Authorization": f"Bearer {LITELLM_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }

    try:
        print(f"🔗 正在連線至 LiteLLM Proxy: {LITELLM_ENDPOINT} ...")
        
        # 連接 LiteLLM Proxy (它會幫我們轉接到 Azure)
        # 使用 additional_headers 參數 (相容 websockets v14+)
        # async with websockets.connect(LITELLM_ENDPOINT, additional_headers=headers) as upstream_ws:
        # 改回 extra_headers 以配合 websockets 13.1
        async with websockets.connect(LITELLM_ENDPOINT, additional_headers=headers, ssl=ssl_context) as upstream_ws:
            print("✅ 已連線至 LiteLLM Proxy (Tunnel Established)")

            # --- 初始化：設定 System Prompt ---
            # 這是告訴模型它的角色 (理專助手)
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text"], 
                    "instructions": """
                    你是一位專業的銀行理專助手。
                    請根據客戶的語音內容，即時提供簡短、專業的建議話術。
                    只回傳建議的文字，不要回傳語音。
                    """,
                    "input_audio_format": "pcm16",
                    "turn_detection": {
                        "type": "server_vad"
                    }
                }
            }
            await upstream_ws.send(json.dumps(session_update))

            # --- 定義雙向轉發函式 ---
            
            # A. 接收前端 (WMS) -> 轉發給 LiteLLM
            async def receive_from_client():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        message = json.loads(data)
                        
                        if "audio" in message:
                            # 轉發音訊 Event
                            audio_event = {
                                "type": "input_audio_buffer.append",
                                "audio": message["audio"]
                            }
                            await upstream_ws.send(json.dumps(audio_event))
                except Exception as e:
                    print(f"Client 連線中斷: {e}")

            # B. 接收 LiteLLM (來自 Azure) -> 經過護欄 -> 轉發給前端
            async def receive_from_upstream():
                buffer = ""
                try:
                    async for msg in upstream_ws:
                        event = json.loads(msg)
                        
                        # 處理錯誤訊息
                        if event["type"] == "error":
                            print(f"❌ Upstream Error: {event}")
                            continue

                        # 處理文字串流
                        if event["type"] == "response.text.delta":
                            content = event["delta"]
                            buffer += content
                            
                            # 簡易流式輸出 (如果要更嚴格的護欄，可以存滿一句再發)
                            # 這裡示範即時檢查 (主要針對關鍵字)
                            if await check_content_safety(content):
                                await client_ws.send_json({
                                    "type": "text_delta",
                                    "content": content
                                })
                            else:
                                # 違規內容用 *** 取代
                                await client_ws.send_json({
                                    "type": "text_delta",
                                    "content": "***"
                                })

                        elif event["type"] == "response.done":
                            await client_ws.send_json({"type": "done"})
                            buffer = ""
                            
                except Exception as e:
                    print(f"Upstream 連線中斷: {e}")

            # 平行執行
            await asyncio.gather(receive_from_client(), receive_from_upstream())

    except Exception as e:
        print(f"系統錯誤 (無法連接 LiteLLM): {e}")
        await client_ws.close()