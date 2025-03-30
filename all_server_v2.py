# main.py (最终优化版)
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.websockets import WebSocketState
import requests


# --------------------------
# 配置管理
# --------------------------
class AppSettings(BaseSettings):
    # 服务端配置
    host: str = "0.0.0.0"
    port: int = 8100
    websocket_path: str = "/ws"
    ping_interval: int = 20
    max_message_size: int = 1024 * 1024

    # 上游服务配置
    upstream_ws_host: str = "192.168.1.4"
    upstream_ws_port: int = 8000
    upstream_ws_path: str = "/ws"
    upstream_use_ssl: bool = False

    # 认证配置
    device_id: str = "f8:e4:e3:ad:36:34"
    client_id: str = "acb42140-a2d1-40e7-944f-591ac3edfad4"
    auth_token: str = "test-token"

    # 音频配置
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_frame_duration: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")


settings = AppSettings()

# --------------------------
# 日志配置
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WSGateway")


# --------------------------
# WebSocket 客户端管理（线程安全版）
# --------------------------
class UpstreamWSClient:
    def __init__(self):
        self._conn: Optional[websockets.WebSocketClientProtocol] = None
        self.headers = [
            ("Authorization", f"Bearer {settings.auth_token}"),
            ("Device-Id", settings.device_id),
            ("Client-Id", settings.client_id)
        ]
        self.ws_uri = (
            f"{'wss' if settings.upstream_use_ssl else 'ws'}://"
            f"{settings.upstream_ws_host}:{settings.upstream_ws_port}"
            f"{settings.upstream_ws_path}"
        )
        # self.ws_uri = "wss://api.tenclass.net/xiaozhi/v1/"

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed

    @asynccontextmanager
    async def connect(self):
        """安全连接上下文管理"""
        try:
            self._conn = await websockets.connect(
                self.ws_uri,
                additional_headers=self.headers,
                ping_interval=20,
                close_timeout=10.0
            )
            await self._send_hello()
            yield self
        except Exception as e:
            logger.error(f"连接失败: {str(e)}")
            raise
        finally:
            if self.is_connected:
                await self._conn.close()
            self._conn = None

    async def _send_hello(self):
        """发送初始化握手消息"""
        hello_msg = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": settings.audio_sample_rate,
                "channels": settings.audio_channels,
                "frame_duration": settings.audio_frame_duration,
            }
        }
        start_data = await self.send(json.dumps(hello_msg))
        print("start_data",start_data)

    async def send(self, message: str):
        """线程安全发送"""
        if not self.is_connected:
            raise RuntimeError("连接未就绪")
        await self._conn.send(message)

    async def recv(self) -> str:
        """线程安全接收"""
        if not self.is_connected:
            raise RuntimeError("连接未就绪")
        return await self._conn.recv()


# --------------------------
# 连接管理器（支持并行连接）
# --------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect_client(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"新客户端连接: {websocket.client}")

    def disconnect_client(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"客户端断开: {websocket.client}")

    async def proxy_message(self, websocket: WebSocket, message: str):
        """消息代理（每个请求独立连接）"""
        try:
            async with UpstreamWSClient().connect() as client:
                # 转发消息
                await client.send(message)

                # 获取响应
                response = await client.recv()
                await self._broadcast_safe(response)

        except Exception as e:
            logger.error(f"消息处理失败: {str(e)}")
            await websocket.send_json({
                "error": "上游服务异常",
                "detail": str(e)
            })

    async def _broadcast_safe(self, message: str):
        """安全广播"""
        active_connections = [
            ws for ws in self.active_connections
            if ws.application_state == WebSocketState.CONNECTED
        ]
        if not active_connections:
            return

        tasks = [ws.send_text(message) for ws in active_connections]
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"广播异常: {str(e)}")


# --------------------------
# FastAPI 应用
# --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("WS网关启动...")
    yield
    logger.info("WS网关关闭...")


app = FastAPI(lifespan=lifespan)
manager = ConnectionManager()


# --------------------------
# WebSocket 路由
# --------------------------
@app.websocket(settings.websocket_path)
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect_client(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            logger.debug(f"收到消息: {message[:200]}...")
            await manager.proxy_message(websocket, message)

    except WebSocketDisconnect as e:
        logger.info(f"客户端断开: code={e.code}")
        manager.disconnect_client(websocket)
    except Exception as e:
        logger.error(f"未处理异常: {str(e)}")
        manager.disconnect_client(websocket)
        await websocket.close(code=1011)


# --------------------------
# 辅助路由
# --------------------------
@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/chat/save")
async def save_chat(data: dict):
    response = requests.post(
        "http://localhost:8000/api/chat/saveChatList",
        json=data
    )
    response.raise_for_status()
    return response.json()


# --------------------------
# 运行入口
# --------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        ws_ping_interval=settings.ping_interval,
        ws_max_size=settings.max_message_size
    )