from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Dict, List, Optional, Any
import pyaudio
import numpy as np
import sys
import base64
import wave

# 添加项目根目录到路径
sys.path.append('/home/ubuntu/py-xiaozhi')

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice_api")


# 音频配置
class AudioConfig:
    CHANNELS = 1
    INPUT_SAMPLE_RATE = 16000
    OUTPUT_SAMPLE_RATE = 16000
    INPUT_FRAME_SIZE = 960  # 60ms at 16kHz
    OUTPUT_FRAME_SIZE = 960
    FRAME_DURATION = 60  # ms


# 创建FastAPI应用
app = FastAPI(title="小智AI 语音流API", description="小智AI设备语音流接口")

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 存储活跃连接
active_connections: Dict[str, WebSocket] = {}
# 存储会话状态
session_states: Dict[str, Dict[str, Any]] = {}


# 语音处理服务
class VoiceProcessingService:
    def __init__(self):
        # 创建聊天记录目录
        os.makedirs("/home/ubuntu/py-xiaozhi/chatVoice", exist_ok=True)

    async def process_audio(self, session_id: str, audio_data: bytes):
        """处理音频数据并返回响应"""
        try:
            # 获取会话状态
            state = session_states.get(session_id, {})
            device_id = state.get("device_id", "unknown")

            # 保存输入音频
            timestamp = int(time.time())
            input_dir = f"/home/ubuntu/py-xiaozhi/chatVoice/{device_id}/input"
            os.makedirs(input_dir, exist_ok=True)
            input_filename = f"{device_id}_{timestamp}.wav"
            input_path = f"{input_dir}/{input_filename}"

            # 将音频数据保存为文件
            with open(input_path, "wb") as f:
                f.write(audio_data)

            logger.info(f"已保存输入音频: {input_path}")

            # 在实际应用中，这里应该:
            # 1. 将音频传递给语音识别服务
            # 2. 将识别结果传递给语言模型
            # 3. 将语言模型响应传递给语音合成服务

            # 模拟语音识别 (实际应用中应使用真实的语音识别)
            recognized_text = "你好，这是模拟的语音识别结果"

            # 模拟语言模型响应 (实际应用中应使用真实的语言模型)
            response_text = "你好，我是小智AI助手，很高兴为您服务！"

            # 模拟语音合成 (实际应用中应使用真实的语音合成)
            # 这里简单地生成一个正弦波作为响应音频
            response_audio = self._generate_sine_wave(frequency=440, duration=2.0)

            # 保存输出音频
            output_dir = f"/home/ubuntu/py-xiaozhi/chatVoice/{device_id}/output"
            os.makedirs(output_dir, exist_ok=True)
            output_filename = f"{device_id}_{timestamp + 1}.wav"
            output_path = f"{output_dir}/{output_filename}"

            # 将响应音频数据保存为WAV文件
            self._save_pcm_to_wav(response_audio, output_path)

            logger.info(f"已保存输出音频: {output_path}")

            # 更新会话状态，添加当前对话
            if "messages" not in state:
                state["messages"] = []

            state["messages"].append({
                "intputText": recognized_text,
                "intputFilePath": f"/chatVoice/{device_id}/input/{input_filename}",
                "outputText": response_text,
                "outputFilePath": f"/chatVoice/{device_id}/output/{output_filename}"
            })

            session_states[session_id] = state

            # 返回处理结果
            return {
                "audio": response_audio,
                "text": response_text,
                "recognized_text": recognized_text
            }

        except Exception as e:
            logger.error(f"音频处理错误: {e}")
            return None

    def _generate_sine_wave(self, frequency=440, duration=1.0):
        """生成正弦波作为模拟的语音响应"""
        sample_rate = AudioConfig.OUTPUT_SAMPLE_RATE
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        sine_wave = np.sin(2 * np.pi * frequency * t)
        # 将浮点数转换为16位整数
        audio_data = (sine_wave * 32767).astype(np.int16)
        return audio_data.tobytes()

    def _save_pcm_to_wav(self, pcm_data, file_path):
        """将PCM数据保存为WAV文件"""
        try:
            with wave.open(file_path, 'wb') as wf:
                wf.setnchannels(AudioConfig.CHANNELS)
                wf.setsampwidth(2)  # 16位音频，每个样本2字节
                wf.setframerate(AudioConfig.INPUT_SAMPLE_RATE)
                wf.writeframes(pcm_data)

            logger.info(f"音频已保存到: {file_path}")
            return True
        except Exception as e:
            logger.error(f"保存音频文件失败: {e}")
            return False

    async def save_chat_history(self, device_id):
        """保存聊天历史记录到后台"""
        try:
            # 查找该设备ID的所有会话
            device_sessions = []
            for session_id, state in session_states.items():
                if state.get("device_id") == device_id:
                    device_sessions.append(session_id)

            if not device_sessions:
                logger.warning(f"未找到设备ID为 {device_id} 的会话")
                return False

            # 收集所有消息
            all_messages = []
            for session_id in device_sessions:
                state = session_states[session_id]
                if "messages" in state:
                    all_messages.extend(state["messages"])

            if not all_messages:
                logger.warning(f"设备ID为 {device_id} 的会话没有消息")
                return False

            # 调用保存聊天记录的API
            # 这里应该使用实际的API调用，这里简化为直接返回成功
            logger.info(f"已保存设备ID为 {device_id} 的 {len(all_messages)} 条聊天记录")
            return True

        except Exception as e:
            logger.error(f"保存聊天历史记录失败: {e}")
            return False


# 创建语音处理服务实例
voice_service = VoiceProcessingService()


@app.get("/")
async def root():
    return {"message": "小智AI 语音流API服务正在运行"}


@app.websocket("/api/voice/stream")
async def voice_stream(websocket: WebSocket):
    """
    WebSocket端点，用于语音流式处理

    客户端发送音频数据，服务器返回处理后的语音响应
    """
    # 生成唯一会话ID
    session_id = str(uuid.uuid4())

    await websocket.accept()
    active_connections[session_id] = websocket

    # 初始化会话状态
    session_states[session_id] = {
        "start_time": time.time(),
        "device_id": None,
        "messages": []
    }

    logger.info(f"新的WebSocket连接已建立: {session_id}")

    try:
        # 发送hello消息
        hello_message = {
            "type": "hello",
            "session_id": session_id,
            "version": 1,
            "transport": "websocket",
            "audio_params": {
                "format": "wav",  # 使用wav格式
                "sample_rate": AudioConfig.INPUT_SAMPLE_RATE,
                "channels": AudioConfig.CHANNELS,
                "frame_duration": 60,  # ms
            }
        }
        await websocket.send_text(json.dumps(hello_message))

        # 处理消息循环
        while True:
            message = await websocket.receive()

            # 处理文本消息
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "start":
                        # 客户端开始发送音频
                        device_id = data.get("device_id")
                        if device_id:
                            session_states[session_id]["device_id"] = device_id
                            logger.info(f"会话 {session_id} 关联到设备 {device_id}")

                        await websocket.send_text(json.dumps({
                            "type": "ready",
                            "message": "准备接收音频数据"
                        }))

                    elif msg_type == "end":
                        # 客户端结束发送音频
                        device_id = session_states[session_id].get("device_id")
                        if device_id:
                            # 保存聊天历史
                            await voice_service.save_chat_history(device_id)

                        await websocket.send_text(json.dumps({
                            "type": "complete",
                            "message": "音频处理完成"
                        }))

                except json.JSONDecodeError:
                    logger.error(f"无效的JSON消息: {message['text']}")

            # 处理二进制音频数据
            elif "bytes" in message:
                audio_data = message["bytes"]

                # 处理音频数据
                result = await voice_service.process_audio(session_id, audio_data)

                if result:
                    # 发送处理后的音频数据
                    await websocket.send_bytes(result["audio"])

                    # 发送文本结果
                    await websocket.send_text(json.dumps({
                        "type": "result",
                        "recognized_text": result["recognized_text"],
                        "response_text": result["text"]
                    }))

    except WebSocketDisconnect:
        logger.info(f"WebSocket连接已关闭: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket处理错误: {e}")
    finally:
        # 清理连接
        if session_id in active_connections:
            del active_connections[session_id]


@app.post("/api/chat/saveChatList")
async def save_chat_list(request: Request):
    """
    保存聊天记录

    参数:
    - deviceId: 设备ID
    - messageList: 聊天消息列表

    返回:
    - 操作结果
    """
    try:
        data = await request.json()
        device_id = data.get("deviceId")
        message_list = data.get("messageList", [])

        if not device_id:
            return {"code": 400, "message": "缺少设备ID"}

        if not message_list:
            return {"code": 400, "message": "消息列表为空"}

        # 确保设备目录存在
        device_dir = f"/home/ubuntu/py-xiaozhi/chatVoice/{device_id}"
        os.makedirs(f"{device_dir}/input", exist_ok=True)
        os.makedirs(f"{device_dir}/output", exist_ok=True)

        # 保存聊天记录
        chat_record = {
            "deviceId": device_id,
            "timestamp": time.time(),
            "messages": message_list
        }

        # 将聊天记录保存到文件（模拟数据库操作）
        with open(f"{device_dir}/chat_history.json", "a") as f:
            f.write(json.dumps(chat_record) + "\n")

        return {"code": 200, "message": "聊天记录保存成功"}

    except Exception as e:
        logger.error(f"保存聊天记录失败: {e}")
        return {"code": 500, "message": f"保存聊天记录失败: {str(e)}"}


@app.get("/api/iot/getConfig")
async def get_device_config(deviceId: str):
    """
    获取设备配置信息

    参数:
    - deviceId: 设备物理网卡MAC地址

    返回:
    - 设备配置信息
    """
    # 模拟设备配置数据库
    DEVICE_CONFIGS = {
        "DE:03:1F:02:00:BF": {
            "id": 123,
            "configId": 123,
            "roleTemplate": "助手",
            "roleVoice": "标准女声",
            "roleIntroduction": "我是您的智能助手，可以帮您解答问题和完成任务。",
            "memoryCore": "标准记忆模块",
            "llmModel": "GPT-4",
            "asrModel": "标准语音识别",
            "vadModel": "标准VAD",
            "ttsModel": "标准TTS"
        }
    }

    if deviceId not in DEVICE_CONFIGS:
        return {"code": 404, "message": "设备未注册", "data": None}

    return {
        "code": 200,
        "message": "OK",
        "data": DEVICE_CONFIGS[deviceId]
    }


@app.get("/api/voice/status")
async def voice_status():
    """获取语音服务状态"""
    return {
        "code": 200,
        "message": "OK",
        "data": {
            "active_connections": len(active_connections),
            "service_status": "running"
        }
    }


# 启动服务器
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
