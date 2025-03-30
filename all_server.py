import json
import asyncio
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from websockets.exceptions import ConnectionClosed
import requests
from src.constants.constants import AudioConfig
from websockets.client import connect, WebSocketClientProtocol
import time
import datetime
from typing import Optional
import websockets
from datetime import datetime


# --------------------------
# 日志配置（保持不变）
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WSDebug")

# --------------------------
# 配置类（新增HEADERS配置）
# --------------------------
class DebugConfig:
    HOST: str = "192.168.1.4"
    PORT: int = 8000
    PATH: str = "/ws"
    # /xiaozhi/v1/
    USE_SSL: bool = False

    # # 新增Header配置
    # HEADERS: dict = {
    #     "Authorization": "Bearer your_token_here",
    #     "X-Custom-Header": "DebugClient"
    # }

    # 配置连接
    HEADERS: dict = {
        "Authorization": f"Bearer test-token",
        "Protocol-Version": "1",
        #   "CLIENT_ID": "acb42140-a2d1-40e7-944f-591ac3edfad4",
        #   "DEVICE_ID": "f8:e4:e3:ad:36:34",
        "Device-Id": "f8:e4:e3:ad:36:34",  # 获取设备MAC地址
        "Client-Id": "acb42140-a2d1-40e7-944f-591ac3edfad4"
    }

    # 启动消息处理循环
    # asyncio.create_task(self._message_handler())

    # 发送客户端hello消息
    hello_message = {
        "type": "hello",
        "version": 1,
        "transport": "websocket",
        "audio_params": {
            "format": "opus",
            "sample_rate": AudioConfig.SAMPLE_RATE,
            "channels": AudioConfig.CHANNELS,
            "frame_duration": AudioConfig.FRAME_DURATION,
        }
    }

    # await self.send_text(json.dumps(hello_message))
    # 测试参数
    TEST_MESSAGES: list[str] = [
        json.dumps(hello_message),
        "Hello World",
        "Ping",
        "Test with spaces",
        "Large message: " + "A" * 1024,
        ""
    ]
    STRESS_CLIENTS: int = 5
    RECONNECT_RETRIES: int = 3
    TIMEOUT: float = 10.0
    LOG_VERBOSE: bool = True

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


class WebSocketDebugger:
    def __init__(self, config: DebugConfig) -> None:
        self.cfg = config
        self.uri = f"{'wss' if self.cfg.USE_SSL else 'ws'}://{self.cfg.HOST}:{self.cfg.PORT}{self.cfg.PATH}"
        self.first = True
        self.first_test_message()

    async def _connect(self, headers=None) -> WebSocketClientProtocol:
        """建立带Header的WebSocket连接"""
        try:
            return await connect(self.uri,
                                 ping_interval=None,
                                 close_timeout=self.cfg.TIMEOUT,
                                 logger=logger if self.cfg.LOG_VERBOSE else None,
                                 extra_headers=headers  # 新增Header注入
                                 )
        except Exception as e:
            logger.error(f"Connection failed: {e!r}")
            raise

    async def first_test_message(self):
        hello_message = {
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "opus",
                "sample_rate": AudioConfig.SAMPLE_RATE,
                "channels": AudioConfig.CHANNELS,
                "frame_duration": AudioConfig.FRAME_DURATION,
            }
        }
        hello_message_str = json.dumps(hello_message)
        return await self._test_message_cycle(hello_message_str)

    async def _test_message_cycle(self, message: str) -> None:
        """测试完整消息生命周期"""
        ws: Optional[WebSocketClientProtocol] = None
        try:
            # 建立连接
            ws = await self._connect(headers=self.cfg.HEADERS)

            # 发送消息
            send_ts = datetime.now().timestamp()
            await ws.send(message)
            logger.info(f"▶ Sent: {message}")

            # 接收响应
            response = await asyncio.wait_for(ws.recv(), self.cfg.TIMEOUT)
            recv_ts = datetime.now().timestamp()

            # 计算延迟
            latency = (recv_ts - send_ts) * 1000
            logger.info(f"◀ Received ({latency:.2f}ms): {response}")
            return response
        except asyncio.TimeoutError:
            logger.error("⌛ Response timeout")
        except websockets.ConnectionClosed as e:
            logger.error(f"🔌 Connection closed: code={e.code}, reason={e.reason!r}")
        except Exception as e:
            logger.error(f"💥 Unexpected error: {e!r}", exc_info=self.cfg.LOG_VERBOSE)
        finally:
            if ws and not ws.closed:
                await ws.close()

    # 获取数据

    # 其他方法保持不变...
    async def run_item(self,items:dict) -> None:
        """执行完整测试套件"""
        if self.first:
            await self.first_test_message()
        await self._test_message_cycle(json.dumps(items))




# --------------------------
# WebSocket 核心逻辑
# --------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.send_obj =  WebSocketDebugger(DebugConfig())

    async def connect(self, websocket: WebSocket,headers=None):
        await websocket.accept(headers=headers)
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
    await manager.connect(websocket,headers=None)
    try:
        # await manager.send_obj.
        while True:
            message = await websocket.receive_text()
            logger.debug(f"Received message: {message[:50]}...")

            data = await manager.send_obj._test_message_cycle(json.dumps({"test": "invalid_format"}))

            # todo 需要链接到服务器..
            # 广播消息
            await manager.broadcast(json.dumps(data))

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