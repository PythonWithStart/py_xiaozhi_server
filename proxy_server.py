# main.py (优化后)
import json
import asyncio
import logging
import os
from hashlib import md5
from uuid import uuid4

import uvicorn
import requests
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from utils.connectionManager import ConnectionManager
from utils.connectionManager import UpstreamWSClient
from utils.record_message import SessionManager
from utils.setting import settings
from starlette.websockets import WebSocketState

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

Session_manager = SessionManager(storage_path="chat_records")

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

        p_session_id = Session_manager.start_session(session_id)
        if not session_id:
            session_id = md5(str(headers)).hexdigest()
            headers["session_id"] = session_id

        current_client = manager.client_map.get("session_id")
        if current_client is None:
            client = await UpstreamWSClient.get_instance(status="start", headers=headers)
            manager.client_map[session_id] = client
        else:
            client =  current_client

        try:
            await client.send_current_json(json.dumps({
                "type": "listen",
                "message": "接收音频数据",
                "mode": True,
                "state": "start",
                "session_id": session_id
            }, ensure_ascii=False))
            Session_manager.add_incoming(p_session_id, "start", {
                "type": "listen",
                "message": "接收音频数据",
                "mode": True,
                "state": "start",
                "session_id": session_id
            })
        except AttributeError as e:
            await client.send_current_json(json.dumps({
                "type": "listen",
                "message": "接收音频数据",
                "mode": True,
                "state": "start",
                "session_id": session_id
            }, ensure_ascii=False))

        try:
            first_recv_data =await  asyncio.wait_for(client.recv(),timeout=5)
            print("first 发送接收音频数据的返回数据",first_recv_data)
        except TimeoutError:
            print("first 发送接收音频数据的返回数据-无")
        receive_bytes_flag = True


        recv_all_data = []
        while True:
            try:
                # 添加连接状态检查
                if websocket.client_state != WebSocketState.CONNECTED:
                    logger.info("WebSocket connection lost, breaking loop")
                    break
                # 传入传入音频数据
                message = await asyncio.wait_for(websocket.receive_bytes(), timeout=10)

                # 当传入b'' 默认音频数据传入结束
                if isinstance(message, bytes) and len(message) == 0 and receive_bytes_flag:
                    Session_manager.add_incoming(p_session_id, "data", recv_all_data)
                    await client.send_current_json(json.dumps({
                        "type": "listen",
                        "message": "停止接收音频数据",
                        "mode": True,
                        "state": "stop",
                        "session_id": session_id
                    }))
                    Session_manager.add_incoming(p_session_id, "end", {
                        "type": "listen",
                        "message": "停止接收音频数据",
                        "mode": True,
                        "state": "stop",
                        "session_id": session_id
                    })
                    # Session_manager.add_incoming(p_session_id, "data", recv_all_data)
                    # 循环等待服务端回传数据
                    post_new_data = []
                    seq = 0
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
                                        Session_manager.add_received(p_session_id, "end", {"format": "opus","total":seq})
                                        print("收到停止信号，跳出循环")
                                        break
                                    elif data.get('type') == 'stt' and data.get('state') == 'start':
                                        Session_manager.add_received(p_session_id, "start", {"format": "opus"})
                                        print("收到开始信号，进行循环")
                                    # elif data.get('type') == 'stt' and data.get("state") == 'start':
                                        # Session_manager.add_received(session_id, "sentence_data", post_new_data)
                                    else:
                                        if data.get('type') == 'tts' and data.get("state") == 'sentence_start':
                                            # Session_manager.add_received(session_id, "sentence_start",
                                            #                      {"seq": 2}, filename="statement_2.opus")
                                            current_record = {"seq":seq}
                                            current_record.update(data)
                                            Session_manager.add_received(p_session_id, "sentence_start", current_record,filename="statement_2.opus")
                                            post_new_data.clear()
                                            seq += 1
                                        if data.get('type') == 'tts' and data.get("state") == 'sentence_end':
                                            # post_new_data.append(recv_all_data)
                                            Session_manager.add_received(p_session_id, "sentence_data", post_new_data)
                                            Session_manager.add_received(p_session_id, "sentence_end", data)

                                except json.JSONDecodeError:
                                    print("数据格式不正确!!")
                                    pass
                            elif isinstance(recv_data, bytes):
                                # 回传的是字节数据 音频数据传输
                                print("recv_data12", recv_data)
                                post_new_data.append(recv_all_data)
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
                    # Session_manager.save_session(p_session_id)
                    break
                recv_all_data.append(message)
                logger.info(f"Received message: {len(message)} types...")
                await manager.proxy_message(client, message)
            except TimeoutError as e:
                logger.error(f"No message received within timeout period + \n + {traceback.print_exc()}")
            except asyncio.exceptions.CancelledError as e:
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
    finally:
        Session_manager.save_session(p_session_id)


# --------------------------
# 辅助路由
# --------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "connections": len(manager.active_connections),
        "upstream_status": "connected" if len(manager.client_map.values()) > 0 else "disconnected",
        "session_ids": list(manager.client_map.keys())
    }


@app.post("/chat/save")
async def save_chat(data: dict):
    """保存聊天记录"""
    session_id =data.get("session_id","")
    if session_id == '':
        session_id = str(uuid4())
        return {"session_id":session_id,"result":[]}
    else:
        file_list = os.listdir("chat_records")
        need_file_list = [file_li for file_li in file_list if session_id in file_li]
        need_file_list = sorted(need_file_list,reverse=True)
        datas = []
        for need_file_li in need_file_list:
            data = json.loads(open(f"chat_records/{need_file_li}",'r',encoding='utf-8').read())
            datas.append(data)
        return {"session_id": session_id, "result": datas}


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