# main.py (优化后)
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

import websockets
from websockets.client import WebSocketURI
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.websockets import WebSocketState
from websockets.client import ClientProtocol
import requests
import traceback


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
        self.conn: Optional[ClientProtocol] = None
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
            if self.conn and self.conn.state != self.conn.state.CLOSED:
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
        await self.send(json.dumps(hello_msg))

    async def send(self, message: str):
        """安全发送消息"""
        if not self.conn or self.conn.state == self.conn.state.CLOSED:
            raise RuntimeError("Connection not established")
        await self.conn.send(message)

    async def recv(self) -> str:
        """安全接收消息"""
        if not self.conn or self.conn.state == self.conn.state.CLOSED:
            raise RuntimeError("Connection not established")
        return await self.conn.recv()

    async def send_bytes(self, data: bytes):
        """发送字节数据"""
        if not self.conn or self.conn.state == self.conn.state.CLOSED:
            raise RuntimeError("Connection not established")
        await self.conn.send(data)

    async def recv_bytes(self) -> bytes:
        """接收字节数据"""
        if not self.conn or self.conn.state == self.conn.state.CLOSED:
            raise RuntimeError("Connection not established")
        return await self.conn.recv()

    async def close(self):
        if self.conn and not self.conn.closed:
            await self.conn.close()
            logger.info("Upstream connection closed")



# --------------------------
# 连接管理器 (优化广播逻辑)
# --------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()


    def disconnect_client(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected: {websocket.client}")

    async def proxy_message(self, UpperClient: UpstreamWSClient, message: str | bytes):
        try:
            # 异步发送接收分离
            send_task = asyncio.create_task(
                UpperClient.send_bytes(message) if isinstance(message, bytes)
                else UpperClient.send(message)
            )

            receive_task = asyncio.create_task(UpperClient.recv_bytes())

            done, pending = await asyncio.wait(
                [send_task, receive_task],
                timeout=10,
                return_when=asyncio.FIRST_EXCEPTION
            )

            if receive_task in done:
                await self._broadcast_safe(receive_task.result())

        except Exception as e:
            logger.error(f"Message handling error: {str(e)}")

    async def _broadcast_safe(self, message: str|bytes):
        for ws in list(self.active_connections):  # 使用副本遍历
            try:
                if ws.application_state == WebSocketState.CONNECTED:
                    if isinstance(message, bytes):
                        await ws.send_bytes(message)
                    else:
                        await ws.send_text(message)
            except RuntimeError as e:
                self.active_connections.discard(ws)
                logger.warning(f"Removed dead connection: {ws.client}")


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
async def websocket_endpoint(websocket_c: WebSocket):
    # 确保在任何接收或发送操作之前调用 accept
    await websocket_c.accept()
    manager.active_connections.add(websocket_c)
    logger.info(f"New client connected: {websocket_c.client}")

    client = UpstreamWSClient()
    manager_a = client.connect()

    try:
        await manager_a.__aenter__()
        await client.send(json.dumps({
            "type": "listen",
            "message": "接收音频数据",
            "mode": True,
            "state": "start",
        }))
        while True:
            try:
                # 检查连接状态
                if websocket_c.application_state != WebSocketState.CONNECTED:
                    logger.error("WebSocket is not connected.")
                    break

                message = await asyncio.wait_for(websocket_c.receive_bytes(), timeout=60)
                print("message",message)
                logger.info(f"Received message: {len(message)} bytes...")
                await manager.proxy_message(client, message)
            except TimeoutError as e:
                logger.error(f"Timeout error: {str(e)}")
            except RuntimeError as e:
                logger.error(f"Runtime error: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}")
    except WebSocketDisconnect as e:
        logger.info(f"Client disconnected: code={e.code}, reason={e.reason}")
        if websocket_c.application_state == WebSocketState.CONNECTED:
            await websocket_c.close(code=1011)
        await client.send(json.dumps({
            "type": "listen",
            "message": "结束接受数据",
            "mode": True,
            "state": "stop",
        }))
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
    finally:
        manager.active_connections.discard(websocket_c)
        await manager_a.__aexit__(None, None, None)


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