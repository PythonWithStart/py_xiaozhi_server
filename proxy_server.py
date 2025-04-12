# main.py (优化后)
import json
import asyncio
import logging
from hashlib import md5

import uvicorn
import requests
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from utils.connectionManager import ConnectionManager
from utils.connectionManager import UpstreamWSClient, settings

# --------------------------
# 日志配置
# --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WSGateway")


# --------------------------
# FastAPI 生命周期管理
# --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化操作
    logger.info("Starting WebSocket gateway...")
    yield
    # 清理操作
    logger.info("Shutting down WebSocket gateway...")


app = FastAPI(lifespan=lifespan)
manager = ConnectionManager()

# --------------------------
# WebSocket 路由端点 (优化错误处理)
# --------------------------
@app.websocket(settings.websocket_path)
async def websocket_endpoint(websocket: WebSocket):
    print("执行到这里了_start")
    await manager.connect_client(websocket)
    try:
        # 获取请求头信息
        headers = {
            "Authorization": websocket.headers.get("Authorization", ""),
            "Device-Id": websocket.headers.get("Device-Id", ""),
            "Client-Id": websocket.headers.get("Client-Id", ""),
            "session_id": websocket.headers.get("session_id", "")
        }
        # 使用session_id获取或创建客户端
        session_id = headers.get("session_id")
        if not session_id:
            session_id = md5(str(headers)).hexdigest()
            headers["session_id"] = session_id

        current_client = manager.client_map.get("session_id")
        if current_client is None:
            client = await UpstreamWSClient.get_instance(status="start", headers=headers)
            manager.client_map[session_id] = client
        else:
            client =  current_client

        await client.send(json.dumps({
            "type": "listen",
            "message": "接收音频数据",
            "mode": True,
            "state": "start",
            "session_id": session_id
        }, ensure_ascii=False))

        try:
            first_recv_data =await  asyncio.wait_for(client.recv_bytes(),timeout=5)
            print("first 发送接收音频数据的返回数据",first_recv_data)
        except TimeoutError:
            print("first 发送接收音频数据的返回数据-无")
        receive_bytes_flag = True

        while True:
            try:
                # if websocket.client_state != "CONNECTED":  # 检查是否已连接
                #     break
                # 传入传入音频数据
                message = await asyncio.wait_for(websocket.receive_bytes(), timeout=10)
                # 当传入b'' 默认音频数据传入结束
                if isinstance(message, bytes) and len(message) == 0 and receive_bytes_flag:
                    await client.send(json.dumps({
                        "type": "listen",
                        "message": "停止接收音频数据",
                        "mode": True,
                        "state": "stop",
                        "session_id": session_id
                    }))
                    # 循环等待服务端回传数据
                    while True and receive_bytes_flag:
                        try:
                            recv_data = await client.recv()
                            # 判断回传数据的类型
                            if isinstance(recv_data, str):
                                try:
                                    # 回传的事字符串数据 声明开始和结束
                                    data = json.loads(recv_data)
                                    await manager._broadcast_safe(data)
                                    if data.get('type') == 'tts' and data.get('state') == 'stop':
                                        print("收到停止信号，跳出循环")
                                        break
                                    elif data.get('type') == 'stt' and data.get('state') == 'start':
                                        print("收到开始信号，进行循环")
                                    else:
                                        print("收到sentence，进行循环")
                                except json.JSONDecodeError:
                                    print("数据格式不正确!!")
                                    pass
                            elif isinstance(recv_data, bytes):
                                # 回传的是字节数据 音频数据传输
                                print("recv_data12", recv_data)
                                await manager._broadcast_safe(recv_data)
                        except Exception as e:
                            print("recv_data error", e, f"{traceback.print_exc()}")
                            break
                    # 收到终止信号，开始中断与服务端的链接
                    # await client.close()
                    # 声明结束服务端数据的接收状态
                    receive_bytes_flag = False
                    # 跳出 接收消息的过程
                    continue
                if message == b'':
                    break
                logger.info(f"Received message: {len(message)} types...")
                await manager.proxy_message(client, message)
            except TimeoutError as e:
                logger.error(f"No message received within timeout period + \n + {traceback.print_exc()}")
    except WebSocketDisconnect as e:
        logger.info(f"Client disconnected: code={e.code}, reason={e.reason}")
        manager.disconnect_client(websocket)
        if session_id in manager.client_map:
            del manager.client_map[session_id]
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)} +\n + {traceback.print_exc()}")
        manager.disconnect_client(websocket)
        if session_id in manager.client_map:
            del manager.client_map[session_id]
        await websocket.close(code=1011)


# --------------------------
# 辅助路由
# --------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "connections": len(manager.active_connections),
        "upstream_status": "connected" if manager.ws_client.conn else "disconnected"
    }


@app.post("/chat/save")
async def save_chat(data: dict):
    """保存聊天记录"""
    # 建议将URL移至配置
    response = requests.post(
        "http://localhost:8000/api/chat/saveChatList",
        json=data
    )
    response.raise_for_status()
    return response.json()


# --------------------------
# 运行入口
# --------------------------
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        ws_ping_interval=settings.ping_interval,
        ws_max_size=settings.max_message_size
    )