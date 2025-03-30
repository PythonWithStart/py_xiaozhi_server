# debug_websocket.py
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
import websockets
from websockets.client import connect, WebSocketClientProtocol
from src.constants.constants import AudioConfig


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
# 日志配置（保持不变）
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WSDebug")


# --------------------------
# 核心调试类（修改_connect方法）
# --------------------------
class WebSocketDebugger:
    def __init__(self, config: DebugConfig) -> None:
        self.cfg = config
        self.uri = f"{'wss' if self.cfg.USE_SSL else 'ws'}://{self.cfg.HOST}:{self.cfg.PORT}{self.cfg.PATH}"

    async def _connect(self) -> WebSocketClientProtocol:
        """建立带Header的WebSocket连接"""
        try:
            return await connect(
                self.uri,
                ping_interval=None,
                close_timeout=self.cfg.TIMEOUT,
                logger=logger if self.cfg.LOG_VERBOSE else None,
                extra_headers=self.cfg.HEADERS  # 新增Header注入
            )
        except Exception as e:
            logger.error(f"Connection failed: {e!r}")
            raise

    async def _stress_test(self) -> None:
        """压力测试（统一使用_connect方法）"""
        logger.info(f"🚀 Starting stress test with {self.cfg.STRESS_CLIENTS} clients")

        async def _client_task(client_id: int) -> None:
            try:
                ws = await self._connect()  # 使用统一的连接方法
                async with ws:
                    msg = f"Stress#{client_id}"
                    await ws.send(msg)
                    response = await ws.recv()
                    if msg not in response:
                        logger.error(f"Client {client_id} received invalid response")
            except Exception as e:
                logger.error(f"Client {client_id} failed: {e!r}")

        tasks = [
            asyncio.create_task(_client_task(i))
            for i in range(self.cfg.STRESS_CLIENTS)
        ]
        await asyncio.gather(*tasks)
        logger.info("✅ Stress test completed")

    async def _reliability_test(self) -> None:
        """可靠性测试（统一使用_connect方法）"""
        logger.info(f"🔁 Starting reliability test ({self.cfg.RECONNECT_RETRIES} retries)")

        for attempt in range(1, self.cfg.RECONNECT_RETRIES + 1):
            try:
                ws = await self._connect()  # 使用统一的连接方法
                async with ws:
                    msg = f"PING#{attempt}"
                    await ws.send(msg)
                    response = await ws.recv()
                    if msg not in response:
                        logger.error(f"Attempt {attempt} response validation failed")
            except Exception as e:
                logger.error(f"Attempt {attempt} failed: {e!r}")
            await asyncio.sleep(1)

        logger.info("✅ Reliability test completed")

    async def _test_message_cycle(self, message: str) -> None:
        """测试完整消息生命周期"""
        ws: Optional[WebSocketClientProtocol] = None
        try:
            # 建立连接
            ws = await self._connect()

            # 发送消息
            send_ts = datetime.now().timestamp()
            await ws.send(message)
            logger.info(f"▶ Sent: {self._trim(message)}")

            # 接收响应
            response = await asyncio.wait_for(ws.recv(), self.cfg.TIMEOUT)
            recv_ts = datetime.now().timestamp()

            # 计算延迟
            latency = (recv_ts - send_ts) * 1000
            # logger.info(f"◀ Received ({latency:.2f}ms): {self._trim(response)}")
            logger.info(f"◀ Received ({latency:.2f}ms): {response}")

            # 验证响应
            self._validate_response(message, response)

        except asyncio.TimeoutError:
            logger.error("⌛ Response timeout")
        except websockets.ConnectionClosed as e:
            logger.error(f"🔌 Connection closed: code={e.code}, reason={e.reason!r}")
        except Exception as e:
            logger.error(f"💥 Unexpected error: {e!r}", exc_info=self.cfg.LOG_VERBOSE)
        finally:
            if ws and not ws.closed:
                await ws.close()

    def _validate_response(self, sent: str, received: str) -> None:
        """验证响应有效性"""
        if not received.startswith("ECHO:"):
            logger.error(f"❌ Invalid response format: {self._trim(received)}")
            return

        original = sent.strip()
        echoed = received[5:].strip()

        if original != echoed:
            logger.error("❌ Content mismatch!\n"
                         f"Sent:     {self._trim(original)}\n"
                         f"Received: {self._trim(echoed)}")

    @staticmethod
    def _trim(text: str, max_len: int = 50) -> str:
        """截断长文本"""
        return (text[:max_len] + "...") if len(text) > max_len else text



    # 其他方法保持不变...
    async def run(self) -> None:
        """执行完整测试套件"""
        logger.info("=" * 60)
        logger.info(f"🔧 Starting WebSocket debug session: {self.uri}")
        logger.info("=" * 60)

        # 基础功能测试
        logger.info("\n📩 Basic message testing")
        for msg in self.cfg.TEST_MESSAGES:
            await self._test_message_cycle(msg)

        # 压力测试
        logger.info("\n📊 Stress testing")
        await self._stress_test()

        # 可靠性测试
        logger.info("\n🛡 Reliability testing")
        await self._reliability_test()

        # 异常测试
        logger.info("\n⚠️ Anomaly testing")
        await self._test_message_cycle(json.dumps({"test": "invalid_format"}))
        await self._test_message_cycle(bytes(range(256)).decode('latin-1'))

        logger.info("=" * 60)
        logger.info("🏁 All tests completed")
        logger.info("=" * 60)


# --------------------------
# 主入口（保持不变）
# --------------------------
async def main() -> None:
    fill_debugger = WebSocketDebugger(DebugConfig())
    try:
        await fill_debugger.run()
    except KeyboardInterrupt:
        logger.info("🛑 Debug session interrupted")


if __name__ == "__main__":
    asyncio.run(main())