# 语音流接口测试脚本
import asyncio
import websockets
import json
import time
import os
import wave
import pyaudio
import numpy as np

# 测试配置
SERVER_URL = "ws://localhost:8080/api/voice/stream"
DEVICE_ID = "DE:03:1F:02:00:BF"
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 960  # 60ms at 16kHz


async def test_voice_stream():
    """测试语音流接口"""
    print(f"连接到服务器: {SERVER_URL}")

    try:
        # 连接到WebSocket服务器
        async with websockets.connect(SERVER_URL) as websocket:
            # 接收服务器的hello消息
            response = await websocket.recv()
            hello_data = json.loads(response)
            print(f"收到服务器hello消息: {hello_data}")

            # 发送开始消息
            start_message = {
                "type": "start",
                "device_id": DEVICE_ID
            }
            await websocket.send(json.dumps(start_message))

            # 接收ready消息
            response = await websocket.recv()
            ready_data = json.loads(response)
            print(f"收到服务器ready消息: {ready_data}")

            # 生成测试音频数据 (1秒的440Hz正弦波)
            print("生成测试音频数据...")
            audio_data = generate_test_audio()

            # 分块发送音频数据
            print("发送音频数据...")
            for i in range(0, len(audio_data), CHUNK * 2):  # *2因为每个样本是2字节
                chunk = audio_data[i:i + CHUNK * 2]
                if chunk:
                    await websocket.send(chunk)
                    print(f"已发送 {len(chunk)} 字节的音频数据")

                    # 接收响应
                    try:
                        # 设置超时，避免无限等待
                        response = await asyncio.wait_for(websocket.recv(), timeout=1.0)

                        # 检查是否是二进制数据(音频)或文本数据(JSON)
                        if isinstance(response, bytes):
                            print(f"收到 {len(response)} 字节的音频响应")
                            # 可以将音频保存或播放
                        else:
                            # 文本响应
                            result_data = json.loads(response)
                            print(f"收到文本响应: {result_data}")
                    except asyncio.TimeoutError:
                        print("等待响应超时，继续发送")

                    # 短暂延迟，模拟实时音频流
                    await asyncio.sleep(0.06)  # 60ms

            # 发送结束消息
            end_message = {
                "type": "end"
            }
            await websocket.send(json.dumps(end_message))

            # 接收complete消息
            response = await websocket.recv()
            complete_data = json.loads(response)
            print(f"收到服务器complete消息: {complete_data}")

            print("测试完成!")

    except Exception as e:
        print(f"测试过程中出错: {e}")


def generate_test_audio():
    """生成测试音频数据 (1秒的440Hz正弦波)"""
    duration = 1.0  # 秒
    frequency = 440  # Hz

    # 生成正弦波
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    sine_wave = np.sin(2 * np.pi * frequency * t)

    # 将浮点数转换为16位整数
    audio_data = (sine_wave * 32767).astype(np.int16)

    # 转换为字节
    return audio_data.tobytes()


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_voice_stream())
