# 测试脚本 test_connect.py
import asyncio
import websockets

async def test_connection():
    headers = [
        ("Authorization", "Bearer test-token"),
        ("Device-Id", "f8:e4:e3:ad:36:34"),
        ("Client-Id", "acb42140-a2d1-40e7-944f-591ac3edfad4")
    ]
    async with websockets.connect(
        "ws://192.168.1.4:8000/ws",
        headers=headers
    ) as ws:
        await ws.send("Hello")
        response = await ws.recv()
        print(f"Received: {response}")

asyncio.run(test_connection())