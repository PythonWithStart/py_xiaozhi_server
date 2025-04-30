"""
生成一个信息记录管理类
一条数据包含
传入信号 开始信号   json字符串  str
传入信号 传入字节码 字节码      list
传入信号 结束信号   json字符串  str
接收信号 开始信号  json字符串   str
接收信号 sentence开始信号   json字符串 str
接收信号 sentence字节码  字节码  list
接收信号 sentence 结束信号 json字符串  str
接收信号 sentence开始信号   json字符串 str
接收信号 sentence字节码  字节码  list
接收信号 sentence 结束信号 json字符串  str
接收信号 结束信号  json字符串   str

sentence开始信号、字节码列表和结束信号 可能存在多个。

额外信息：
- 需要添加每一个字节码列表对应一个文件名，添加到信息记录里面
- 添加一个session_id，用于区别不同用户的数据。

请基于上述要求生成一个python类，辅助管理数据。
"""

import json
import base64
import os
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union
from uuid import uuid4
import dataclasses  # 新增导入


@dataclass
class BaseRecord:
    """基础记录类，包含时间元数据"""
    user_id: str  # 用户唯一标识
    session_id: str = field(init=False)  # 系统生成的唯一会话ID
    timestamp: float = field(default_factory=time.time)
    start_time: str = field(init=False)  # 可读的会话开始时间

    def __post_init__(self):
        """后初始化处理"""
        dt = datetime.fromtimestamp(self.timestamp)
        # 生成唯一会话ID：用户ID_时间戳_随机后缀
        self.session_id = f"{self.user_id}_{dt:%Y%m%d%H%M%S}_{str(uuid4())[:8]}"
        self.start_time = dt.isoformat()


@dataclass
class ReceivedSentence:
    """接收语句单元"""
    sentence_id: str  # 语句唯一标识
    start_signal: dict  # 开始信号
    bytecodes: List[bytes] = field(default_factory=list)  # 字节码数据
    end_signal: Optional[dict] = None  # 结束信号
    filename: Optional[str] = None  # 关联文件名


@dataclass
class CommunicationSession(BaseRecord):
    """完整通信会话记录"""
    incoming_start: Optional[dict] = None  # 传入开始信号
    incoming_data: List[bytes] = field(default_factory=list)  # 传入字节码
    incoming_end: Optional[dict] = None  # 传入结束信号

    received_start: Optional[dict] = None  # 接收开始信号
    sentences: List[ReceivedSentence] = field(default_factory=list)  # 接收语句
    received_end: Optional[dict] = None  # 接收结束信号
    current_sentence: Optional[ReceivedSentence] = None  # 当前处理的语句


class SessionManager:
    def __init__(self, storage_path: str = "sessions"):
        """
        初始化管理器
        :param storage_path: 会话存储目录路径
        """
        self.sessions: Dict[str, CommunicationSession] = {}
        self.storage_path = storage_path
        os.makedirs(storage_path, exist_ok=True)

    def _get_session(self, session_id: str) -> CommunicationSession:
        """获取会话对象"""
        if session_id not in self.sessions:
            raise KeyError(f"无效的会话ID: {session_id}")
        return self.sessions[session_id]

    def start_session(self, user_id: str) -> str:
        """
        创建新会话
        :param user_id: 用户唯一标识
        :return: 生成的会话ID
        """
        new_session = CommunicationSession(user_id=user_id)
        self.sessions[new_session.session_id] = new_session
        return new_session.session_id

    def add_incoming(self, session_id: str, signal_type: str, data: Union[dict, list]):
        """
        处理传入信号
        :param session_id: 会话ID
        :param signal_type: 信号类型 (start/data/end)
        :param data: 信号数据
        """
        session = self._get_session(session_id)

        if signal_type == "start":
            if session.incoming_start is not None:
                raise ValueError("重复的传入开始信号")
            session.incoming_start = data
        elif signal_type == "data":
            if not session.incoming_start:
                raise ValueError("缺少传入开始信号")
            if session.incoming_end:
                raise ValueError("传入流程已结束")
            session.incoming_data.extend(data)
        elif signal_type == "end":
            if not session.incoming_start:
                raise ValueError("缺少传入开始信号")
            session.incoming_end = data
        else:
            raise ValueError(f"无效的传入信号类型: {signal_type}")

    def add_received(self, session_id: str, signal_type: str, data: Union[dict, list, bytes],
                     filename: Optional[str] = None):
        """
        处理接收信号
        :param session_id: 会话ID
        :param signal_type: 信号类型 (start/sentence_start/sentence_data/sentence_end/end)
        :param data: 信号数据
        :param filename: 关联文件名（仅sentence_start时有效）
        """
        session = self._get_session(session_id)

        if signal_type == "start":
            if session.received_start is not None:
                raise ValueError("重复的接收开始信号")
            session.received_start = data
        elif signal_type == "sentence_start":
            if session.current_sentence is not None:
                raise ValueError("存在未结束的语句")
            sentence_id = f"{session_id}_{len(session.sentences) + 1}"
            session.current_sentence = ReceivedSentence(
                sentence_id=sentence_id,
                start_signal=data,
                filename=filename
            )
        elif signal_type == "sentence_data":
            if not session.current_sentence:
                raise ValueError("没有活动的语句")
            session.current_sentence.bytecodes.extend(data)
        elif signal_type == "sentence_end":
            if not session.current_sentence:
                raise ValueError("没有活动的语句")
            session.current_sentence.end_signal = data
            session.sentences.append(session.current_sentence)
            session.current_sentence = None
        elif signal_type == "end":
            if session.current_sentence is not None:
                raise ValueError("存在未结束的语句")
            session.received_end = data
        else:
            raise ValueError(f"无效的接收信号类型: {signal_type}")

    def save_session(self, session_id: str):
        """
        保存会话到JSON文件
        :param session_id: 要保存的会话ID
        """
        session = self._get_session(session_id)

        def bytes_converter(o):
            """字节数据转换处理器"""
            if isinstance(o, bytes):
                return base64.b64encode(o).decode('utf-8')
            if dataclasses.is_dataclass(o):  # 处理所有数据类实例
                return dataclasses.asdict(o)
            raise TypeError(f"无法序列化类型 {type(o).__name__}")

        file_path = os.path.join(self.storage_path, f"{session_id}.json")
        with open(file_path, 'w') as f:
            # 使用数据类的asdict方法进行深度转换
            session_dict = dataclasses.asdict(session, dict_factory=lambda x: {k: v for (k, v) in x if v is not None})
            json.dump(session_dict, f, default=bytes_converter, indent=2)

    def get_session_info(self, session_id: str) -> dict:
        """获取会话摘要信息"""
        session = self._get_session(session_id)
        return {
            "session_id": session_id,
            "user_id": session.user_id,
            "start_time": session.start_time,
            "incoming_status": bool(session.incoming_end),
            "received_sentences": len(session.sentences),
            "storage_path": os.path.join(self.storage_path, f"{session_id}.json")
        }


# 使用示例
if __name__ == "__main__":
    # 初始化管理器
    manager = SessionManager(storage_path="chat_records")

    # 用户A开始会话
    user_a = "user_123"
    session_id = manager.start_session(user_a)

    # 处理传入数据
    manager.add_incoming(session_id, "start", {"type": "voice_stream"})
    manager.add_incoming(session_id, "data", [b"audio_chunk_1", b"audio_chunk_2"])
    manager.add_incoming(session_id, "end", {"status": "complete"})

    # 处理接收数据
    manager.add_received(session_id, "start", {"format": "opus"})

    # 第一个语句
    manager.add_received(session_id, "sentence_start",
                         {"seq": 1}, filename="statement_1.opus")
    manager.add_received(session_id, "sentence_data", [b"response_1_1", b"response_1_2"])
    manager.add_received(session_id, "sentence_end", {"status": 200})

    # 第二个语句
    manager.add_received(session_id, "sentence_start",
                         {"seq": 2}, filename="statement_2.opus")
    manager.add_received(session_id, "sentence_data", [b"response_2_1"])
    manager.add_received(session_id, "sentence_end", {"status": 200})

    manager.add_received(session_id, "end", {"total": 2})

    # 保存会话
    manager.save_session(session_id)

    # 获取会话信息
    print(json.dumps(manager.get_session_info(session_id), indent=2))