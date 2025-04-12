import json
import time
import hashlib
import logging
import asyncio
import websockets
from typing import Any
from typing import Optional
from fastapi import WebSocket
from utils.setting import settings
from starlette.websockets import WebSocketState
from websockets.client import WebSocketClientProtocol

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
# 连接管理器 (优化广播逻辑)
# --------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self.client_map = {}  # 存储session_id到client的映射

    async def connect_client(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"New client connected: {websocket.client}")

    def disconnect_client(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected: {websocket.client}")

    async def proxy_message(self, UpperClient: Any, message: Any):
        """消息代理处理"""
        if isinstance(message, bytes):
            print("send_bytes", message)
            await UpperClient.send_bytes(message)
        else:
            raise ValueError("Unsupported message type")

        try:
            print(f"{time.strftime('%Y-%H-%D',time.localtime())} UpperClient.recv()")
            response = await asyncio.wait_for(UpperClient.recv(), timeout=0.5)
            await self._broadcast_safe(response)
        except TimeoutError:
            response = b'sent'
            await self._broadcast_safe(response)
        except Exception as e:
            logger.error(f"Message handling failed: {str(e)}")

    async def _broadcast_safe(self, message: Any):
        """安全广播消息"""
        if not self.active_connections:
            return

        print("message", type(message), message)
        tasks = []

        if isinstance(message, str):
            try:
                data = json.loads(message)
                if isinstance(data, dict):
                    # 如果是JSON消息，直接广播
                    tasks = [
                        ws.send_json(data)
                        for ws in self.active_connections
                        if ws.application_state == WebSocketState.CONNECTED
                    ]
            except json.JSONDecodeError:
                # 如果不是JSON，作为文本发送
                tasks = [
                    ws.send_text(message)
                    for ws in self.active_connections
                    if ws.application_state == WebSocketState.CONNECTED
                ]
        elif isinstance(message, bytes):
            # 二进制数据直接发送
            tasks = [
                ws.send_bytes(message)
                for ws in self.active_connections
                if ws.application_state == WebSocketState.CONNECTED
            ]

        try:
            print(f"{time.strftime('%Y-%H-%D',time.localtime())} _broadcast_safe1")
            if len(tasks) > 0:
                print(f"{time.strftime('%Y-%H-%D',time.localtime())} _broadcast_safe2")
                await asyncio.gather(*tasks)
                print(f"{time.strftime('%Y-%H-%D',time.localtime())} _broadcast_safe3")
        except Exception as e:
            logger.error(f"Broadcast error: {str(e)}")


# --------------------------
# WebSocket 客户端管理
# --------------------------
class UpstreamWSClient:
    _instance: Optional["UpstreamWSClient"] = None
    _instance_lock = asyncio.Lock()  # 单例创建锁
    _connection_lock = asyncio.Lock()  # 连接操作锁
    _session_map = {}  # 存储会话信息 {session_id: (client_instance, expire_time)}

    def __init__(self):
        """初始化WebSocket客户端"""
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
        self.session_id = None
        self.expire_time = None

    @classmethod
    def _generate_session_id(cls, headers: dict) -> str:
        """根据headers生成session_id"""
        # 使用特定的header字段生成session_id
        key_fields = ['Authorization', 'Device-Id', 'Client-Id']
        key_values = [headers.get(field, '') for field in key_fields]
        key_string = ''.join(key_values)
        return hashlib.md5(key_string.encode()).hexdigest()

    @classmethod
    async def get_instance(cls, status=None, headers=None) -> "UpstreamWSClient":
        """获取全局唯一实例（带会话管理）"""
        if not headers:
            raise ValueError("headers参数不能为空")

        session_id = cls._generate_session_id(headers)

        async with cls._instance_lock:
            # 清理过期会话
            current_time = time.time()
            expired_sessions = [
                sid for sid, (_, expire) in cls._session_map.items()
                if expire < current_time
            ]
            for sid in expired_sessions:
                del cls._session_map[sid]

            # 如果session_id存在且未过期，复用会话
            if session_id in cls._session_map:
                instance, expire = cls._session_map[session_id]
                if expire > current_time:
                    instance.current_status = status
                    return instance

            # 创建新实例
            instance = cls()
            instance.session_id = session_id
            instance.current_status = status
            instance.expire_time = current_time + 3600  # 1小时过期
            instance.headers.update(headers)  # 更新headers

            try:
                await instance._ensure_connection()
                cls._session_map[session_id] = (instance, instance.expire_time)
            except Exception as e:
                raise RuntimeError(f"创建WebSocket客户端实例失败: {e}")

            return instance

    async def _force_disconnect(self):
        """强制断开当前连接"""
        if self.conn and not self.conn.closed:
            try:
                self.conn.transport.close()
                self.next_link = True
            except Exception as e:
                logger.debug(f"强制关闭连接时发生错误: {e}")

            self.connected = False
            self.initial_hello_sent = False
            self.conn = None

            # 从会话映射中移除
            if self.session_id and self.session_id in self._session_map:
                del self._session_map[self.session_id]

    async def _ensure_connection(self) -> None:
        """确保连接已建立"""
        if self.connected and self.conn and not self.conn.closed:
            return

        async with self._connection_lock:
            if self.connected and self.conn and not self.conn.closed:
                return

            while self.reconnect_attempts < self.max_reconnect_attempts:
                try:
                    self.conn = await websockets.connect(
                        self.ws_uri,
                        ping_interval=30,
                        close_timeout=10.0,
                        # work headers 处理
                        extra_headers=self.headers,
                        # home header处理
                        # additional_headers = self.headers,
                    )
                    self.connected = True
                    # 发送初始化握手消息
                    if not self.initial_hello_sent and self.current_status is not None and not self.next_link:
                        await self._send_hello()
                        self.initial_hello_sent = True
                        self.current_status = None
                        self.next_link = True
                    self.reconnect_attempts = 0
                    logger.info(f"WebSocket连接成功: {self.ws_uri}")
                    return

                except Exception as e:
                    self.reconnect_attempts += 1
                    if self.reconnect_attempts >= self.max_reconnect_attempts:
                        self.connected = False
                        raise RuntimeError(
                            f"WebSocket连接失败，已达最大重试次数({self.max_reconnect_attempts}): {e}"
                        )

                    # 指数退避重试
                    delay = min(2 ** self.reconnect_attempts, 30)
                    await asyncio.sleep(delay)

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
        logger.info(f"发送初始化握手消息: {hello_msg}")

    async def send(self, message: str) -> None:
        """安全发送文本消息"""
        await self._ensure_connection()
        await self.conn.send(message)

    async def recv(self) -> str:
        """安全接收文本消息"""
        await self._ensure_connection()
        return await self.conn.recv()

    async def send_bytes(self, data: bytes) -> None:
        """安全发送二进制数据"""
        await self._ensure_connection()
        await self.conn.send(data)

    async def recv_bytes(self) -> bytes:
        """安全接收二进制数据"""
        await self._ensure_connection()
        return await self.conn.recv()

    async def close(self) -> None:
        """关闭连接"""
        if self.conn and not self.conn.closed:
            await self.conn.close()
        self.connected = False
        self.initial_hello_sent = False  # 重置状态以便下次连接

    async def __aenter__(self):
        """支持异步上下文管理器"""
        await self._ensure_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时自动关闭连接"""
        await self.close()