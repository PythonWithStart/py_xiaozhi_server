import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, List
import websockets
from websockets.client import connect, WebSocketClientProtocol
import sys

# 在导入 opuslib 之前处理 opus 动态库
from src.utils.system_info import setup_opus
setup_opus()

import opuslib

from src.constants.constants import AudioConfig
opus_encoder = opuslib.Encoder(
 fs=AudioConfig.SAMPLE_RATE,
 channels=AudioConfig.CHANNELS,
 application=opuslib.APPLICATION_AUDIO
 )

# 现在导入 opuslib
try:
    import opuslib
except Exception as e:
    print(f"导入 opuslib 失败: {e}")
    print("请确保 opus 动态库已正确安装或位于正确的位置")
    sys.exit(1)

from src.constants.constants import AudioConfig

opus_encoder = opuslib.Encoder(
    fs=AudioConfig.SAMPLE_RATE,
    channels=AudioConfig.CHANNELS,
    application=opuslib.APPLICATION_AUDIO
)

# --------------------------
# 配置类（支持类型注解）
# --------------------------
class DebugConfig:
    HOST: str = "localhost"  # 服务地址
    PORT: int = 9800  # 服务端口
    PATH: str = "/ws"  # WebSocket路径
    USE_SSL: bool = False  # 是否启用wss

    TEST_MESSAGES: List[bytes] = [
        b"Hello World",
        b"Ping",
        b"Test with spaces",
        b"Large message: " + b"A" * 1024,  # 1KB消息
        b""
    ]
    STRESS_CLIENTS: int = 5  # 并发客户端数量
    RECONNECT_RETRIES: int = 3  # 重连尝试次数
    TIMEOUT: float = 10.0  # 超时时间（秒）
    LOG_VERBOSE: bool = True  # 详细日志模式


# --------------------------
# 日志配置（优化输出格式）
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WSDebug")


# --------------------------
# 核心调试类（完全类型注解）
# --------------------------
class WebSocketDebugger:
    def __init__(self, config: DebugConfig) -> None:
        self.cfg = config
        self.uri = f"{'wss' if self.cfg.USE_SSL else 'ws'}://{self.cfg.HOST}:{self.cfg.PORT}{self.cfg.PATH}"
        logger.info(f"WebSocket URI: {self.uri}")

    async def _connect(self) -> WebSocketClientProtocol:
        """安全建立WebSocket连接"""
        try:
            return await connect(
                self.uri,
                ping_interval=None,
                close_timeout=self.cfg.TIMEOUT,
                logger=logger if self.cfg.LOG_VERBOSE else None
            )
        except Exception as e:
            logger.error(f"Connection failed: {e!r}")
            raise

    async def _test_message_cycle(self, messages: List[bytes]) -> None:
        """测试完整消息生命周期"""
        ws: Optional[WebSocketClientProtocol] = None
        try:
            # 建立连接
            ws = await self._connect()
            for message in messages:
                # 发送消息
                send_ts = datetime.now().timestamp()
                if isinstance(message, str):
                    await ws.send(message.encode('utf-8'))
                    logger.info(f"▶ Sent: {message}")
                elif isinstance(message, bytes):
                    encoded_data = opus_encoder.encode(message, AudioConfig.FRAME_SIZE)
                    await ws.send(encoded_data)
                    logger.info(f"▶ Sent: {len(message)} bytes")

                # 接收响应
                try:
                    response = await asyncio.wait_for(ws.recv(), self.cfg.TIMEOUT)
                except asyncio.TimeoutError:
                    logger.error("⌛ Response timeout")
                    continue

                recv_ts = datetime.now().timestamp()
                # 计算延迟
                latency = (recv_ts - send_ts) * 1000
                if isinstance(response, str):
                    logger.info(f"◀ Received ({latency:.2f}ms): {response}")
                else:
                    logger.info(f"◀ Received ({latency:.2f}ms): {len(response)} bytes")

        except websockets.ConnectionClosed as e:
            logger.error(f"🔌 Connection closed: code={e.code}, reason={e.reason!r}")
        except Exception as e:
            logger.error(f"💥 Unexpected error: {e!r}", exc_info=self.cfg.LOG_VERBOSE)
        finally:
            if ws and not ws.closed:
                await ws.close()

    async def run(self) -> None:
        """执行完整测试套件"""
        logger.info("=" * 60)
        logger.info(f"🔧 Starting WebSocket debug session: {self.uri}")
        logger.info("=" * 60)

        # 基础功能测试
        logger.info("\n📩 Basic message testing")
        await self._test_message_cycle(self.cfg.TEST_MESSAGES)

        logger.info("=" * 60)
        logger.info("🏁 All tests completed")
        logger.info("=" * 60)


# --------------------------
# 主入口（最佳实践）
# --------------------------
async def main() -> None:
    debugger = WebSocketDebugger(DebugConfig())
    try:
        await debugger.run()
    except KeyboardInterrupt:
        logger.info("🛑 Debug session interrupted")


if __name__ == "__main__":
    asyncio.run(main())