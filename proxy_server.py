# main.py (优化后)
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.websockets import WebSocketState
from websockets.client import WebSocketClientProtocol
import requests


# --------------------------
# 配置管理 (集中管理所有配置)
# --------------------------
class AppSettings(BaseSettings):
    # 服务端配置
    host: str = "0.0.0.0"
    port: int = 8100
    websocket_path: str = "/ws"
    ping_interval: int = 20  # 心跳间隔（秒）
    max_message_size: int = 1024 * 1024  # 1MB

    # 上游WS服务配置
    upstream_ws_host: str = "192.168.1.4"
    upstream_ws_port: int = 8000
    upstream_ws_path: str = "/ws"
    upstream_use_ssl: bool = False

    # 身份认证配置
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
# WebSocket 客户端管理
# --------------------------
class UpstreamWSClient:
    def __init__(self):
        self.conn: Optional[WebSocketClientProtocol] = None
        self.headers = {
            "Authorization": f"Bearer {settings.auth_token}",
            "Device-Id": settings.device_id,
            "Client-Id": settings.client_id
        }
        self.ws_uri = (
            f"{'wss' if settings.upstream_use_ssl else 'ws'}://"
            f"{settings.upstream_ws_host}:{settings.upstream_ws_port}"
            f"{settings.upstream_ws_path}"
        )
        # self.ws_uri = "wss://api.tenclass.net/xiaozhi/v1/"

    @asynccontextmanager
    async def connect(self):
        """上下文管理WebSocket连接"""
        try:
            self.conn = await websockets.connect(
                self.ws_uri,
                additional_headers=self.headers,
                ping_interval=None,
                close_timeout=10.0
            )
            await self._send_hello()
            yield self
        finally:
            if self.conn and not self.conn.closed:
                await self.conn.close()

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
        hello_msg = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "massage": b''
        }
        await self.send(json.dumps(hello_msg))

    async def send(self, message: str):
        """安全发送消息"""
        if not self.conn or self.conn.closed:
            raise RuntimeError("Connection not established")
        await self.conn.send(message)

    async def recv(self) -> str:
        """安全接收消息"""
        if not self.conn or self.conn.closed:
            raise RuntimeError("Connection not established")
        return await self.conn.recv()

    async def send_bytes(self, data: bytes):
        """发送字节数据"""
        if not self.conn or self.conn.closed:
            raise RuntimeError("Connection not established")
        await self.conn.send(data)

    async def recv_bytes(self) -> bytes:
        """接收字节数据"""
        if not self.conn or self.conn.closed:
            raise RuntimeError("Connection not established")
        return await self.conn.recv()


# --------------------------
# 连接管理器 (优化广播逻辑)
# --------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self.ws_client = UpstreamWSClient()

    async def connect_client(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"New client connected: {websocket.client}")

    def disconnect_client(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected: {websocket.client}")

    async def proxy_message(self, UpperClient: UpstreamWSClient, message: str|bytes):
        """消息代理处理"""
        if isinstance(message, bytes):
            await UpperClient.conn.send_bytes(message)
        else:
            raise ValueError("Unsupported message type")

        try:
            # 根据消息类型接收响应
            if isinstance(message, str):
                response = await UpperClient.recv()
            elif isinstance(message, bytes):
                response = await UpperClient.recv_bytes()
            else:
                raise ValueError("Unsupported message type")

            await self._broadcast_safe(response)
        except Exception as e:
            logger.error(f"Message handling failed: {str(e)}")

    async def _broadcast_safe(self, message: str):
        """安全广播消息"""
        if not self.active_connections:
            return

        tasks = [
            ws.send_text(message)
            for ws in self.active_connections
            if ws.application_state == WebSocketState.CONNECTED
        ]

        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Broadcast error: {str(e)}")


# --------------------------
# FastAPI 生命周期管理
# --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化操作
    logger.info("Starting WebSocket gateway...")
    yield
    # 清理操作
    logger.info("Shutting down WebSocket gateway...")


app = FastAPI(lifespan=lifespan)
manager = ConnectionManager()


# --------------------------
# WebSocket 路由端点 (优化错误处理)
# --------------------------
@app.websocket(settings.websocket_path)
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect_client(websocket)
    try:
        async with manager.ws_client.connect() as client:
            await client.conn.send(json.dumps({
                "type": "listen",
                "message": "接收音频数据",
                "mode": True,
                "state": "start",
            }))
            while True:
                try:
                    message = await asyncio.wait_for(websocket.receive_bytes(),timeout=30)
                    logger.debug(f"Received message: {message[:200]}...")
                    # 消息处理管道
                    await manager.proxy_message(client, message)
                except TimeoutError as e:
                    await client.conn.send(json.dumps({
                        "type": "listen",
                        "message": "结束接受数据",
                        "mode": True,
                        "state": "stop",
                    }))
    except WebSocketDisconnect as e:
        logger.info(f"Client disconnected: code={e.code}, reason={e.reason}")
        manager.disconnect_client(websocket)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        manager.disconnect_client(websocket)
        await websocket.close(code=1011)


# --------------------------
# 辅助路由
# --------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "connections": len(manager.active_connections),
        "upstream_status": "connected" if manager.ws_client.conn else "disconnected"
    }


@app.post("/chat/save")
async def save_chat(data: dict):
    """保存聊天记录"""
    # 建议将URL移至配置
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