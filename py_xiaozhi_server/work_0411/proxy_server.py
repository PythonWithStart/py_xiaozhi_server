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
            print(f"{time.localtime()}UpperClient.recv()")
            response = await asyncio.wait_for(UpperClient.recv(), timeout=0.5)
            await self._broadcast_safe(response)
        except TimeoutError:
            response = b''
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
            print(f"{time.localtime()} _broadcast_safe1")
            if len(tasks) > 0:
                print(f"{time.localtime()} _broadcast_safe2")
                await asyncio.gather(*tasks)
                print(f"{time.localtime()} _broadcast_safe3")
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