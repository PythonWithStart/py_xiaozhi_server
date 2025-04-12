import asyncio
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from websockets.exceptions import ConnectionClosed
import requests


# --------------------------
# 配置管理
# --------------------------
class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8100
    websocket_path: str = "/ws"
    ping_interval: int = 20  # 心跳间隔（秒）
    max_message_size: int = 1024 * 1024  # 1MB

    model_config = SettingsConfigDict(env_prefix="APP_")


settings = Settings()
app = FastAPI()

# --------------------------
# 日志配置
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("WebSocketServer")


# --------------------------
# WebSocket 核心逻辑
# --------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New connection: {websocket.client}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Connection closed: {websocket.client}")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Broadcast failed: {str(e)}")


manager = ConnectionManager()


print(settings.websocket_path)
@app.websocket(settings.websocket_path)
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            logger.debug(f"Received message: {message[:50]}...")

            # 业务逻辑处理
            response = f"ECHO: {message}"

            # todo 需要链接到服务器..
            # 广播消息
            await manager.broadcast(response)

        data = {"deviceId":123,"messageList":[]}
        await end_send(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"Client {websocket.client} left")
    except ConnectionClosed:
        logger.info("Connection closed normally")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        manager.disconnect(websocket)


# --------------------------
# 健康检查端点
# --------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "connections": len(manager.active_connections)
    }


@app.get("/config")
async def get_config():
    return 	{
	  "code": 200,
	  "message": "OK",
	  "data": {
			"id": 123,
			"configId": 123,
			"roleTemplate": "角色模板",
			"roleVoice": "角色音色",
			"roleIntroduction": "角色介绍",
			"memoryCore": "记忆体",
			"llmModel": "大语言模型",
			"asrModel": "语音转文本模型",
			"vadModel": "语音活动检测模型",
			"ttsModel": "语音生成模型"
		  },
   }



async def end_send(data:dict):
    return requests.post("http://localhost:8000/api/chat/saveChatList",data)




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        ws_ping_interval=settings.ping_interval,
        ws_max_size=settings.max_message_size
    )