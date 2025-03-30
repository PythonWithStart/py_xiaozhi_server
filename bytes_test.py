import asyncio
import websockets
import os
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebSocketDebugClient")

# WebSocket 服务器配置
WS_URI = "ws://localhost:8100/ws"  # 替换为你的 WebSocket 服务器地址
TEST_MESSAGE = b"Hello, WebSocket!"  # 测试字节流数据

async def debug_client():
    async with websockets.connect(WS_URI) as websocket:
        logger.info("Connected to WebSocket server")

        try:
            # 发送字节流数据
            logger.info(f"Sending bytes: {TEST_MESSAGE}")
            await websocket.send(TEST_MESSAGE)

            # 接收响应
            response = await websocket.recv()
            logger.info(f"Received response: {response}")

        except Exception as e:
            logger.error(f"Error occurred: {str(e)}")

        finally:
            logger.info("Closing WebSocket connection")
            await websocket.close()

if __name__ == "__main__":
    asyncio.run(debug_client())