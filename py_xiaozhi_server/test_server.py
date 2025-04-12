# test_server.py
import pytest
import websockets
from fastapi import FastAPI
from httpx import AsyncClient
from server import app


@pytest.mark.asyncio
async def test_websocket_endpoint():
    # 使用 AsyncClient 替代 TestClient
    async with AsyncClient(app=app, base_url="ws://0.0.0.0:8000") as client:
        # 异步连接 WebSocket
        async with client.websocket_connect("/ws") as client_ws:
            # 测试双向通信
            test_message = "test_message"

            # 发送消息
            await client_ws.send_text(test_message)

            # 接收响应（假设目标服务器原样返回）
            try:
                response = await client_ws.receive_text()
                assert response == test_message
            except Exception as e:
                pytest.fail(f"Failed to receive response: {str(e)}")