import pytest
import asyncio
import websockets
from httpx import AsyncClient
from server_1 import app, Settings


@pytest.fixture
async def test_client():
    async with AsyncClient(app=app, base_url="http://localhost:8100") as client:
        yield client


@pytest.mark.asyncio
async def test_websocket_connection(test_client):
    # 使用正确的 WebSocket 路径格式
    ws_path = Settings().websocket_path
    print(ws_path)
    async with test_client.websocket_connect(ws_path) as ws:
        assert ws is not None
        await ws.send_text("test message")
        response = await ws.receive_text()
        assert response.startswith("ECHO: test message")


@pytest.mark.asyncio
async def test_broadcast_functionality(test_client):
    # 测试广播功能
    messages = []

    async def collect_messages():
        async with test_client.websocket_connect(Settings().websocket_path) as ws:
            await ws.send_text("join")
            while True:
                msg = await ws.receive_text()
                messages.append(msg)

    task = asyncio.create_task(collect_messages())

    async with test_client.websocket_connect(Settings().websocket_path) as ws:
        await ws.send_text("broadcast test")
        await asyncio.sleep(0.5)  # 等待广播完成

    task.cancel()
    assert any("broadcast test" in msg for msg in messages)


@pytest.mark.asyncio
async def test_invalid_message():
    # 测试无效消息处理
    async with websockets.connect(
            f"ws://{Settings().host}:{Settings().port}{Settings().websocket_path}"
    ) as ws:
        # 发送二进制消息（服务端期望文本消息）
        await ws.send(b"invalid binary message")
        response = await ws.recv()
        assert "error" in response.lower()


@pytest.mark.asyncio
async def test_health_check(test_client):
    # 测试健康检查端点
    response = await test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"