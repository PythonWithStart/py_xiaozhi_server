import json
import time
import hashlib
import logging
import asyncio
from typing import Any, Optional, Set, Dict, Tuple
import websockets
from websockets import connect
from websockets.server import WebSocketServer
from websockets.client import WebSocketClientProtocol
from websockets.typing import Data
from fastapi import WebSocket
from starlette.websockets import WebSocketState
from .setting import settings
from websockets.protocol import State

# --------------------------
# 日志配置（保持不变）
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WSGateway")

# --------------------------
# 连接管理器优化（适配新版协议）
# --------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.client_map: Dict[str, WebSocket] = {}  # 类型注解优化

    async def connect_client(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"New client connected: {websocket.client}")

    def disconnect_client(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected: {websocket.client}")

    async def proxy_message(self, upper_client: WebSocketClientProtocol, message: Data):
        """适配新版 Data 类型注解"""
        try:
            if isinstance(message, bytes):
                await upper_client.send_bytes(message)
                logger.debug("Sent binary message to upstream")
            else:
                await upper_client.send_current_json(message.decode('utf-8'))
                logger.debug("Sent text message to upstream")

            # 使用新版协议的超时处理方式
            try:
                response = await asyncio.wait_for(upper_client.recv(), timeout=0.5)
                await self._broadcast_safe(response)
            except asyncio.TimeoutError:
                response = b'sent'
                await self._broadcast_safe(response)
                
        except websockets.ConnectionClosed as e:
            logger.warning(f"Connection closed during proxy: {e.reason}")
        except Exception as e:
            logger.error(f"Message handling failed: {str(e)}", exc_info=True)

    async def _broadcast_safe(self, message: Data):
        """适配新版 Data 类型"""
        if not self.active_connections:
            return

        tasks = []
        for ws in self.active_connections:
            if ws.application_state != WebSocketState.CONNECTED:
                continue

            try:
                if isinstance(message, bytes):
                    tasks.append(ws.send_bytes(message))
                elif isinstance(message, str):
                    try:
                        json.loads(message)  # 验证是否为JSON
                        tasks.append(ws.send_json(message))
                    except json.JSONDecodeError:
                        tasks.append(ws.send_text(message))
            except RuntimeError as e:
                logger.warning(f"Skipping closed connection: {e}")

        if tasks:
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                logger.error(f"Broadcast error: {str(e)}", exc_info=True)

# --------------------------
# WebSocket 客户端管理（适配15.x版本）
# --------------------------
class UpstreamWSClient:
    _instance: Optional["UpstreamWSClient"] = None
    _instance_lock = asyncio.Lock()
    _connection_lock = asyncio.Lock()
    _session_map: Dict[str, Tuple["UpstreamWSClient", float]] = {}  # 类型注解优化

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
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.initial_hello_sent = False
        self.current_status = None
        self.next_link = False
        self.session_id: Optional[str] = None
        self.expire_time: Optional[float] = None

    @classmethod
    def _generate_session_id(cls, headers: dict) -> str:
        key_fields = ['Authorization', 'Device-Id', 'Client-Id']
        key_values = [headers.get(field, '') for field in key_fields]
        return hashlib.md5(''.join(key_values).encode()).hexdigest()

    @classmethod
    async def get_instance(cls, status=None, headers=None) -> "UpstreamWSClient":
        if not headers:
            raise ValueError("headers参数不能为空")

        session_id = cls._generate_session_id(headers)

        async with cls._instance_lock:
            current_time = time.time()
            # 清理过期会话
            cls._session_map = {
                sid: data 
                for sid, data in cls._session_map.items()
                if data[1] > current_time
            }

            if session_id in cls._session_map:
                instance, expire = cls._session_map[session_id]
                instance.current_status = status
                return instance

            # 创建新实例
            instance = cls()
            instance.session_id = session_id
            instance.current_status = status
            instance.expire_time = current_time + 3600
            instance.headers.update(headers)

            try:
                await instance._ensure_connection()
                cls._session_map[session_id] = (instance, instance.expire_time)
            except Exception as e:
                logger.error(f"创建实例失败: {e}", exc_info=True)
                raise RuntimeError(f"创建WebSocket客户端实例失败: {e}")

            return instance

    async def _force_disconnect(self):
        if self.conn and not self.conn.closed:
            try:
                await self.conn.close()
                self.next_link = True
            except Exception as e:
                logger.debug(f"关闭连接错误: {e}")
            finally:
                self.connected = False
                self.initial_hello_sent = False
                self.conn = None

            if self.session_id in self._session_map:
                del self._session_map[self.session_id]

    async def _ensure_connection(self) -> None:
        if self.connected and self.conn and not self.conn.closed:
            return

        async with self._connection_lock:
            if self.connected and self.conn and not self.conn.closed:
                return

            for attempt in range(self.max_reconnect_attempts):
                try:
                    # 使用新版connect参数
                    self.conn = await connect(
                        self.ws_uri,
                        ping_interval=30,
                        close_timeout=10.0,
                        # extra_headers=self.headers,  # 关键修改点：使用extra_headers
                        additional_headers=self.headers,
                        open_timeout=10.0,          # 新增推荐参数
                        max_size=2**20               # 控制最大消息大小
                    )
                    
                    self.connected = True
                    if not self.initial_hello_sent and self.current_status and not self.next_link:
                        await self._send_hello()
                        self.initial_hello_sent = True
                        self.current_status = None
                        self.next_link = True
                    self.reconnect_attempts = 0
                    logger.info(f"连接成功: {self.ws_uri}")
                    return

                except (websockets.ConnectionClosed, asyncio.TimeoutError) as e:
                    logger.warning(f"连接尝试 {attempt+1} 失败: {str(e)}")
                    await asyncio.sleep(min(2 ** attempt, 30))
                except Exception as e:
                    logger.error(f"意外连接错误: {str(e)}", exc_info=True)
                    await asyncio.sleep(min(2 ** attempt, 30))

            self.connected = False
            raise RuntimeError(f"连接失败，已达最大尝试次数 {self.max_reconnect_attempts}")

    async def _send_hello(self):
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
        await self.conn.send(json.dumps(hello_msg))  # 使用直接发送方式
        logger.info(f"已发送初始化握手消息")


    async def send_current_json(self,data: str):
        if not self.conn or self.conn.state is State.CLOSED:
            await self._ensure_connection()
        await self.conn.send(data)

    async def send_bytes(self, data: bytes) -> None:
        if not self.conn or self.conn.state is State.CLOSED:
            await self._ensure_connection()
        await self.conn.send(data)

    async def recv(self) -> Data:  # 使用新版Data类型
        if not self.conn or self.conn.state is State.CLOSED:
            await self._ensure_connection()
        return await self.conn.recv()

    async def close(self) -> None:
        if self.conn and not self.conn.state is State.CONNECTING:
            await self.conn.close()
        self.connected = False
        self.initial_hello_sent = False

    async def __aenter__(self):
        await self._ensure_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()