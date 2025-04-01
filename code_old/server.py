# server.py
import asyncio
import logging
from typing import Any

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic_settings import BaseSettings, SettingsConfigDict
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError


# --------------------------
# 配置管理 (支持环境变量覆盖)
# --------------------------
class Settings(BaseSettings):
    ota_version_url: str = "https://api.tenclass.net/xiaozhi/ota/"
    websocket_url: str = "wss://api.tenclass.net/xiaozhi/v1/"
    websocket_token: str = "test-token"

    model_config = SettingsConfigDict(env_prefix="NETWORK_")  # 替换旧版 Config 类


settings = Settings()
app = FastAPI()

# --------------------------
# 日志配置
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("WebSocketProxy")


# --------------------------
# WebSocket 转发核心逻辑
# --------------------------
@app.websocket("/ws")
async def websocket_proxy(client_ws: WebSocket):
    await client_ws.accept()
    logger.info("Client connected from %s", client_ws.client)

    target_ws = None
    try:
        # 连接到目标 WebSocket 服务
        target_url = f"{settings.websocket_url}?token={settings.websocket_token}"
        target_ws = await websockets.connect(target_url, ping_interval=20)
        logger.info("Connected to target server: %s", target_url)

        # 创建双向转发任务
        client_to_target = asyncio.create_task(
            forward_client_to_target(client_ws, target_ws)
        )
        target_to_client = asyncio.create_task(
            forward_target_to_client(target_ws, client_ws)
        )

        # 等待任意任务完成
        await asyncio.gather(client_to_target, target_to_client)

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("Connection error: %s", str(e), exc_info=True)
    finally:
        # 确保关闭连接
        if target_ws and not target_ws.closed:
            await target_ws.close()
        await client_ws.close()
        logger.info("Connection fully closed")


async def forward_client_to_target(client_ws: WebSocket, target_ws: Any):
    """从客户端转发消息到目标服务"""
    try:
        while True:
            message = await client_ws.receive_text()
            logger.debug("Client -> Target: %s", message[:100])
            await target_ws.send(message)
    except (WebSocketDisconnect, ConnectionClosedOK, ConnectionClosedError):
        logger.debug("Client->Target forwarding stopped")
    except Exception as e:
        logger.error("Forwarding error (client->target): %s", str(e))


async def forward_target_to_client(target_ws: Any, client_ws: WebSocket):
    """从目标服务转发消息到客户端"""
    try:
        while True:
            message = await target_ws.recv()
            logger.debug("Target -> Client: %s", message[:100])
            await client_ws.send_text(message)
    except (ConnectionClosedOK, ConnectionClosedError):
        logger.debug("Target->Client forwarding stopped")
    except Exception as e:
        logger.error("Forwarding error (target->client): %s", str(e))


# --------------------------
# 健康检查端点
# --------------------------
@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)