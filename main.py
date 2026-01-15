import os
import json
import asyncio
import base64
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")

# 1. 提供 WMS 模擬畫面
@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 2. WebSocket 處理核心 (AP 邏輯)
@app.websocket("/ws")
async def websocket_endpoint(client_ws: WebSocket):
    await client_ws.accept()
    print("✅ WMS 前端已連線")

    # 設定連接 Azure 的 Header
    headers = {
        "api-key": AZURE_API_KEY,
        "OpenAI-Beta": "realtime=v1"
    }

    try:
        # 連接 Azure OpenAI Realtime API
        async with websockets.connect(AZURE_ENDPOINT, additional_headers=headers) as azure_ws:
            print("✅ 已連線至 Azure OpenAI")

            # --- 初始化：設定 System Prompt (業務邏輯注入) ---
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text"],  # 我們只需要文字回應，節省成本並符合需求
                    "instructions": """
                    你是一位專業的銀行理專助手。
                    你的任務是傾聽理專與客戶的對話，並即時提供「簡短、精準的話術建議」。
                    請忽略閒聊，專注於分析客戶的潛在需求（如基金、保險、定存）。
                    回應格式請直接給出建議理專說的話，不用解釋原因。
                    """,
                    "input_audio_format": "pcm16", # Azure 預設格式
                    "turn_detection": {
                        "type": "server_vad" # 開啟伺服器端語音偵測
                    }
                }
            }
            await azure_ws.send(json.dumps(session_update))

            # --- 定義雙向轉發函式 ---
            
            # A. 接收前端音訊 -> 轉發給 Azure
            async def receive_from_client():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        message = json.loads(data)
                        
                        # 如果是音訊資料
                        if "audio" in message:
                            # 包裝成 Azure 看得懂的 Event
                            audio_event = {
                                "type": "input_audio_buffer.append",
                                "audio": message["audio"] # 這裡是 Base64
                            }
                            await azure_ws.send(json.dumps(audio_event))
                except Exception as e:
                    print(f"Client 連線中斷: {e}")

            # B. 接收 Azure 回應 -> 轉發給前端 (只取文字)
            async def receive_from_azure():
                try:
                    async for msg in azure_ws:
                        event = json.loads(msg)
                        
                        # 這是文字生成的片段 (Streaming Text)
                        if event["type"] == "response.text.delta":
                            await client_ws.send_json({
                                "type": "text_delta",
                                "content": event["delta"]
                            })
                        
                        # 這是完整的回答結束
                        elif event["type"] == "response.done":
                            await client_ws.send_json({"type": "done"})
                            
                        # 如果有錯誤
                        elif event["type"] == "error":
                            print(f"Azure Error: {event}")
                            
                except Exception as e:
                    print(f"Azure 連線中斷: {e}")

            # 平行執行兩個任務
            await asyncio.gather(receive_from_client(), receive_from_azure())

    except Exception as e:
        print(f"系統錯誤: {e}")
        await client_ws.close()