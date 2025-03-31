# 小智AI API 接口文档

## 接口概述
- 协议：HTTP/HTTPS 和 WebSocket
- 数据格式：JSON 和二进制音频数据
- 编码：UTF-8
- 认证方式：Bearer Token（需要时）

## 通用响应格式
```json
{
  "code": 200,             // 状态码
  "message": "success",    // 消息描述
  "data": {}               // 返回数据
}
```

## API 接口列表

### 1. 获取设备配置

**请求地址**：`/api/iot/getConfig`

**请求方式**：GET

**请求参数**：

| 参数名 | 类型 | 必填 | 说明 | 示例值 |
| ------ | ---- | ---- | ---- | ------ |
| deviceId | String | 是 | 设备物理网卡MAC地址 | DE:03:1F:02:00:BF |

**返回值**：

```json
{
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
  }
}
```

### 2. 保存聊天记录

**请求地址**：`/api/chat/saveChatList`

**请求方式**：POST

**请求参数**：

| 参数名 | 类型 | 必填 | 说明 | 示例值 |
| ------ | ---- | ---- | ---- | ------ |
| deviceId | int | 是 | 设备id | 123 |
| messageList | List | 是 | 本机对话记录,内容有文本和语音文件地址 | 见下方示例 |

**请求体示例**：

```json
{
  "deviceId": 123,
  "messageList": [
    {
      "intputText": "你好",
      "intputFilePath": "/chatVoice/123/intput/123_1616161616.wav",
      "outputText": "我是xxx",
      "outputFilePath": "/chatVoice/123/output/123_1616161617.wav"
    }
  ]
}
```

**返回值**：

```json
{
  "code": 200,
  "message": "OK"
}
```

### 3. 语音流式对话接口

**请求地址**：`/api/voice/stream`

**请求方式**：WebSocket

**连接流程**：

1. 客户端连接WebSocket端点
2. 服务器发送hello消息，包含会话ID和音频参数
3. 客户端发送start消息，包含设备ID
4. 服务器发送ready消息，表示准备接收音频数据
5. 客户端发送二进制音频数据
6. 服务器处理音频并返回二进制音频响应和文本结果
7. 客户端发送end消息，结束会话
8. 服务器发送complete消息，确认会话结束

**消息格式**：

1. 服务器hello消息：
```json
{
  "type": "hello",
  "session_id": "uuid字符串",
  "version": 1,
  "transport": "websocket",
  "audio_params": {
    "format": "wav",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

2. 客户端start消息：
```json
{
  "type": "start",
  "device_id": "DE:03:1F:02:00:BF"
}
```

3. 服务器ready消息：
```json
{
  "type": "ready",
  "message": "准备接收音频数据"
}
```

4. 服务器结果消息：
```json
{
  "type": "result",
  "recognized_text": "识别出的文本",
  "response_text": "响应文本"
}
```

5. 客户端end消息：
```json
{
  "type": "end"
}
```

6. 服务器complete消息：
```json
{
  "type": "complete",
  "message": "音频处理完成"
}
```

**音频数据**：
- 客户端发送的音频数据为二进制WAV格式
- 服务器返回的音频数据为二进制PCM格式（16位，16kHz，单声道）

### 4. 获取语音服务状态

**请求地址**：`/api/voice/status`

**请求方式**：GET

**返回值**：

```json
{
  "code": 200,
  "message": "OK",
  "data": {
    "active_connections": 1,
    "service_status": "running"
  }
}
```

## 客户端示例代码

### WebSocket语音流示例（Python）

```python
import asyncio
import websockets
import json
import wave
import pyaudio
import numpy as np

# 配置
SERVER_URL = "ws://your-server-url/api/voice/stream"
DEVICE_ID = "DE:03:1F:02:00:BF"
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 960  # 60ms at 16kHz

async def voice_stream_test():
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
            
            # 打开音频文件
            with wave.open("input.wav", "rb") as wf:
                # 读取音频数据
                audio_data = wf.readframes(wf.getnframes())
                
                # 分块发送音频数据
                for i in range(0, len(audio_data), CHUNK*2):  # *2因为每个样本是2字节
                    chunk = audio_data[i:i+CHUNK*2]
                    if chunk:
                        await websocket.send(chunk)
                        print(f"已发送 {len(chunk)} 字节的音频数据")
                        
                        # 接收响应
                        try:
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

# 运行测试
asyncio.run(voice_stream_test())
```

## 部署说明

API 服务器使用 FastAPI 框架实现，通过 Uvicorn 服务器运行。服务器默认监听在 `0.0.0.0:8080` 地址上，可以通过以下命令启动：

```bash
cd /path/to/py-xiaozhi
python3 -m uvicorn voice_api:app --host 0.0.0.0 --port 8080
```

## 公网访问

API 服务已部署到公网，可通过以下URL访问：

- HTTP接口: `http://8080-i4tobkmlu1641d7yfsj8z-ae05ca78.manus.computer/`
- WebSocket接口: `ws://8080-i4tobkmlu1641d7yfsj8z-ae05ca78.manus.computer/api/voice/stream`
