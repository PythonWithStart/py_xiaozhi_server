# 导入异步I/O库，用于处理异步任务
import asyncio
# 导入JSON处理库，用于解析和生成JSON数据
import json
# 导入日志记录库，用于记录程序运行信息
import logging
# 导入线程库，用于实现多线程编程
import threading
# 导入时间库，用于处理时间相关操作
import time


# 从 websocket_protocol 模块导入 WebsocketProtocol 类，用于处理 WebSocket 协议通信
from src.protocols.websocket_protocol import WebsocketProtocol
# 从 constants 模块导入一些常量，如设备状态、事件类型、音频配置等
from src.constants.constants import (
    DeviceState, EventType, AudioConfig, 
    AbortReason, ListeningMode
)

# 配置日志，创建一个名为 "Application" 的日志记录器
logger = logging.getLogger("Application")


class Application:
    """智能音箱应用程序主类"""
    # 单例实例变量
    _instance = None

    @classmethod
    def get_instance(cls):
        """获取单例实例"""
        # 如果实例未创建，则创建一个新的 Application 实例
        if cls._instance is None:
            cls._instance = Application()
        # 返回单例实例
        return cls._instance

    def __init__(self):
        """初始化应用程序"""
        # 确保单例模式，若实例已存在则抛出异常
        if Application._instance is not None:
            raise Exception("Application是单例类，请使用get_instance()获取实例")
        # 将当前实例赋值给单例实例变量
        Application._instance = self


        # 状态变量
        # 设备当前状态，初始为空闲状态
        self.device_state = DeviceState.IDLE
        # 是否持续监听
        self.keep_listening = False

        # 事件循环和线程
        # 创建一个新的异步事件循环
        self.loop = asyncio.new_event_loop()
        # 事件循环线程
        self.loop_thread = None
        # 程序是否正在运行
        self.running = False

        # 任务队列和锁
        # 主任务列表
        self.main_tasks = []
        # 线程锁，用于保护共享资源
        self.mutex = threading.Lock()

        # 协议实例
        # 通信协议实例，将在 set_protocol_type 中初始化
        self.protocol = None

        # 初始化事件对象
        self.events = {
            # 调度事件
            EventType.SCHEDULE_EVENT: threading.Event(),
        }

    def run(self, **kwargs):
        """启动应用程序"""
        # 打印传入的关键字参数
        print(kwargs)
        # 获取显示模式，默认为 'gui'
        # mode = kwargs.get('mode', 'gui')
        # 获取协议类型，默认为 'websocket'
        protocol = kwargs.get('protocol', 'websocket')

        # 设置协议类型
        self.set_protocol_type(protocol)

        # 创建并启动事件循环线程
        self.loop_thread = threading.Thread(target=self._run_event_loop)
        # 设置为守护线程，主线程退出时自动退出
        self.loop_thread.daemon = True
        # 启动事件循环线程
        self.loop_thread.start()

        # 等待事件循环准备就绪
        time.sleep(0.1)

        # 初始化应用程序（移除自动连接）
        asyncio.run_coroutine_threadsafe(self._initialize_without_connect(), self.loop)


        # 启动主循环线程
        main_loop_thread = threading.Thread(target=self._main_loop)
        # 设置为守护线程，主线程退出时自动退出
        main_loop_thread.daemon = True
        # 启动主循环线程
        main_loop_thread.start()

    def _run_event_loop(self):
        """运行事件循环的线程函数"""
        # 设置当前线程的事件循环为 self.loop
        asyncio.set_event_loop(self.loop)
        # 启动事件循环
        self.loop.run_forever()

    async def _initialize_without_connect(self):
        """初始化应用程序组件（不建立连接）"""
        # 记录日志，表示正在初始化应用程序
        logger.info("正在初始化应用程序...")

        # 设置设备状态为待命
        self.set_device_state(DeviceState.IDLE)

        
        # 设置协议回调
        self.protocol.on_network_error = self._on_network_error
        self.protocol.on_incoming_audio = self._on_incoming_audio
        self.protocol.on_incoming_json = self._on_incoming_json
        self.protocol.on_audio_channel_opened = self._on_audio_channel_opened
        self.protocol.on_audio_channel_closed = self._on_audio_channel_closed
        # self.protocol.on_audio_config_changed = self._on_audio_config_changed  # 添加音频配置变更回调

        # 记录日志，表示应用程序初始化完成
        logger.info("应用程序初始化完成")


    def set_protocol_type(self, protocol_type: str):
        """设置协议类型"""
        # if protocol_type == 'mqtt':
        #     # 如果协议类型为 'mqtt'，创建 MqttProtocol 实例
        #     self.protocol = MqttProtocol(self.loop)
        # else:  # websocket
        # 直接使用 WebSocket 协议
        self.protocol = WebsocketProtocol()


    def _main_loop(self):
        """应用程序主循环"""
        # 记录日志，表示主循环已启动
        logger.info("主循环已启动")
        # 设置程序运行状态为 True
        self.running = True

        while self.running:
            # 等待事件
            for event_type, event in self.events.items():
                if event.is_set():
                    # 清除事件标志
                    event.clear()

                    if event_type == EventType.SCHEDULE_EVENT:
                        # 如果是调度事件，调用 _process_scheduled_tasks 方法处理调度任务
                        self._process_scheduled_tasks()

            # 短暂休眠以避免CPU占用过高
            time.sleep(0.01)

    def _process_scheduled_tasks(self):
        """处理调度任务"""
        with self.mutex:
            # 复制主任务列表
            tasks = self.main_tasks.copy()
            # 清空主任务列表
            self.main_tasks.clear()

        for task in tasks:
            try:
                # 执行任务
                task()
            except Exception as e:
                # 记录日志，表示执行调度任务时出错
                logger.error(f"执行调度任务时出错: {e}")

    def schedule(self, callback):
        """调度任务到主循环"""
        with self.mutex:
            # 如果是中止语音的任务，检查是否已经存在相同类型的任务
            if 'abort_speaking' in str(callback):
                # 如果已经有中止任务在队列中，就不再添加
                has_abort_task = any(
                    'abort_speaking' in str(task) 
                    for task in self.main_tasks
                )
                if has_abort_task:
                    return
            # 将任务添加到主任务列表
            self.main_tasks.append(callback)
        # 设置调度事件标志
        self.events[EventType.SCHEDULE_EVENT].set()


    def _on_network_error(self, message):
        """网络错误回调"""
        # 设置持续监听状态为 False
        self.keep_listening = False
        # 设置设备状态为空闲
        self.set_device_state(DeviceState.IDLE)
        
        if self.device_state != DeviceState.CONNECTING:
            # 记录日志，表示检测到连接断开
            logger.info("检测到连接断开")
            # 设置设备状态为空闲
            self.set_device_state(DeviceState.IDLE)
            
            # 关闭现有连接，但不关闭音频流
            if self.protocol:
                asyncio.run_coroutine_threadsafe(
                    self.protocol.close_audio_channel(),
                    self.loop
                )

    def _attempt_reconnect(self):
        """尝试重新连接服务器"""
        if self.device_state != DeviceState.CONNECTING:
            # 记录日志，表示检测到连接断开，尝试重新连接
            logger.info("检测到连接断开，尝试重新连接...")
            # 设置设备状态为连接中
            self.set_device_state(DeviceState.CONNECTING)

            # 关闭现有连接
            if self.protocol:
                asyncio.run_coroutine_threadsafe(
                    self.protocol.close_audio_channel(),
                    self.loop
                )

            # 延迟一秒后尝试重新连接
            def delayed_reconnect():
                time.sleep(1)
                asyncio.run_coroutine_threadsafe(self._reconnect(), self.loop)

            # 启动延迟重新连接线程
            threading.Thread(target=delayed_reconnect, daemon=True).start()

    async def _reconnect(self):
        """重新连接到服务器"""

        # 设置协议回调
        self.protocol.on_network_error = self._on_network_error
        self.protocol.on_incoming_audio = self._on_incoming_audio
        self.protocol.on_incoming_json = self._on_incoming_json
        self.protocol.on_audio_channel_opened = self._on_audio_channel_opened
        self.protocol.on_audio_channel_closed = self._on_audio_channel_closed

        # 连接到服务器
        retry_count = 0
        max_retries = 3

        while retry_count < max_retries:
            # 记录日志，表示尝试重新连接
            logger.info(f"尝试重新连接 (尝试 {retry_count + 1}/{max_retries})...")
            if await self.protocol.connect():
                # 记录日志，表示重新连接成功
                logger.info("重新连接成功")
                # 设置设备状态为空闲
                self.set_device_state(DeviceState.IDLE)
                return True

            retry_count += 1
            # 等待2秒后重试
            await asyncio.sleep(2)

        # 记录日志，表示重新连接失败
        logger.error(f"重新连接失败，已尝试 {max_retries} 次")
        # 调度警告信息
        self.schedule(lambda: self.alert("连接错误", "无法重新连接到服务器"))
        # 设置设备状态为空闲
        self.set_device_state(DeviceState.IDLE)
        return False

    def _on_incoming_json(self, json_data):
        """接收JSON数据回调"""
        try:
            if not json_data:
                # 如果没有 JSON 数据，直接返回
                return

            # 解析JSON数据
            if isinstance(json_data, str):
                data = json.loads(json_data)
            else:
                data = json_data
            # 打印解析后的 JSON 数据
            print("data", data)
            # 处理不同类型的消息
            msg_type = data.get("type", "")
            if msg_type == "tts":
                # 如果是 TTS 消息，调用 _handle_tts_message 方法处理
                self._handle_tts_message(data)
            elif msg_type == "stt":
                # 如果是 STT 消息，调用 _handle_stt_message 方法处理
                self._handle_stt_message(data)
            elif msg_type == "llm":
                # 如果是 LLM 消息，调用 _handle_llm_message 方法处理
                self._handle_llm_message(data)
            elif msg_type == "iot":
                # 如果是 IoT 消息，调用 _handle_iot_message 方法处理
                self._handle_iot_message(data)
            else:
                # 记录日志，表示收到未知类型的消息
                logger.warning(f"收到未知类型的消息: {msg_type}")
        except Exception as e:
            # 记录日志，表示处理 JSON 消息时出错
            logger.error(f"处理JSON消息时出错: {e}")

    def _handle_tts_message(self, data):
        """处理TTS消息"""
        state = data.get("state", "")
        if state == "start":
            # 如果是 TTS 开始消息，调度 _handle_tts_start 方法处理
            self.schedule(lambda: self._handle_tts_start())
        elif state == "stop":
            # 如果是 TTS 停止消息，调度 _handle_tts_stop 方法处理
            self.schedule(lambda: self._handle_tts_stop())
        elif state == "sentence_start":
            text = data.get("text", "")
            if text:
                # 记录日志，表示收到 TTS 句子开始消息
                logger.info(f"<< {text}")
                # 调度设置聊天消息方法
                self.schedule(lambda: self.set_chat_message("assistant", text))

                # 检查是否包含验证码信息
                if "请登录到控制面板添加设备，输入验证码" in text:
                    # 调度处理验证码信息方法
                    self.schedule(lambda: self._handle_verification_code(text))

    def _handle_tts_start(self):
        """处理TTS开始事件"""

        if self.device_state == DeviceState.IDLE or self.device_state == DeviceState.LISTENING:
            # 如果设备状态为空闲或监听状态，设置设备状态为说话状态
            self.set_device_state(DeviceState.SPEAKING)


    def _handle_tts_stop(self):
        """处理TTS停止事件"""
        if self.device_state == DeviceState.SPEAKING:
            # 给音频播放一个缓冲时间，确保所有音频都播放完毕
            def delayed_state_change():
                # 状态转换
                if self.keep_listening:
                    # 如果持续监听状态为 True，发送开始监听消息
                    asyncio.run_coroutine_threadsafe(
                        self.protocol.send_start_listening(ListeningMode.AUTO_STOP),
                        self.loop
                    )
                    # 设置设备状态为监听状态
                    self.set_device_state(DeviceState.LISTENING)
                else:
                    # 否则，设置设备状态为空闲状态
                    self.set_device_state(DeviceState.IDLE)

            # 安排延迟执行
            threading.Thread(target=delayed_state_change, daemon=True).start()

    def _handle_stt_message(self, data):
        """处理STT消息"""
        text = data.get("text", "")
        if text:
            # 记录日志，表示收到 STT 消息
            logger.info(f">> {text}")
            # 调度设置聊天消息方法
            self.schedule(lambda: self.set_chat_message("user", text))

    def _handle_llm_message(self, data):
        """处理LLM消息"""
        emotion = data.get("emotion", "")
        if emotion:
            # 调度设置表情方法
            self.schedule(lambda: self.set_emotion(emotion))

    async def _on_audio_channel_opened(self):
        """音频通道打开回调"""
        # 记录日志，表示音频通道已打开
        logger.info("音频通道已打开")

    async def _on_audio_channel_closed(self):
        """音频通道关闭回调"""
        # 记录日志，表示音频通道已关闭
        logger.info("音频通道已关闭")
        # 设置为空闲状态但不关闭音频流
        self.set_device_state(DeviceState.IDLE)
        # 设置持续监听状态为 False
        self.keep_listening = False


    def set_device_state(self, state):
        """设置设备状态"""
        if self.device_state == state:
            # 如果设备状态没有变化，直接返回
            return

        old_state = self.device_state

        # 设置设备状态
        self.device_state = state
        # 记录日志，表示状态变更
        logger.info(f"状态变更: {old_state} -> {state}")

        # 根据状态执行相应操作
        if state == DeviceState.IDLE:
            pass
        elif state == DeviceState.CONNECTING:
            pass
        elif state == DeviceState.LISTENING:
            pass
        elif state == DeviceState.SPEAKING:
            pass







    def shutdown(self):
        """关闭应用程序"""
        # 记录日志，表示正在关闭应用程序
        logger.info("正在关闭应用程序...")
        # 设置程序运行状态为 False
        self.running = False

        # # 关闭音频编解码器
        # if self.audio_codec:
        #     # 关闭音频编解码器
        #     self.audio_codec.close()

        # 关闭协议
        if self.protocol:
            # 异步关闭音频通道
            asyncio.run_coroutine_threadsafe(
                self.protocol.close_audio_channel(),
                self.loop
            )

        # 停止事件循环
        if self.loop and self.loop.is_running():
            # 停止事件循环
            self.loop.call_soon_threadsafe(self.loop.stop)

        # 等待事件循环线程结束
        if self.loop_thread and self.loop_thread.is_alive():
            # 等待事件循环线程结束
            self.loop_thread.join(timeout=1.0)

        # 记录日志，表示应用程序已关闭
        logger.info("应用程序已关闭")

    def _handle_verification_code(self, text):
        """处理验证码信息"""
        try:
            # 提取验证码
            import re
            verification_code = re.search(r'验证码：(\d+)', text)
            if verification_code:
                code = verification_code.group(1)

                # 尝试复制到剪贴板
                try:
                    import pyperclip
                    # 复制验证码到剪贴板
                    pyperclip.copy(code)
                    # 记录日志，表示验证码已复制到剪贴板
                    logger.info(f"验证码 {code} 已复制到剪贴板")
                except Exception as e:
                    # 记录日志，表示无法复制验证码到剪贴板
                    logger.warning(f"无法复制验证码到剪贴板: {e}")

                # 尝试打开浏览器
                try:
                    import webbrowser
                    if webbrowser.open("https://xiaozhi.me/login"):
                        # 记录日志，表示已打开登录页面
                        logger.info("已打开登录页面")
                    else:
                        # 记录日志，表示无法打开浏览器
                        logger.warning("无法打开浏览器")
                except Exception as e:
                    # 记录日志，表示打开浏览器时出错
                    logger.warning(f"打开浏览器时出错: {e}")

                # 无论如何都显示验证码
                # self.alert("验证码", f"您的验证码是: {code}")

        except Exception as e:
            # 记录日志，表示处理验证码时出错
            logger.error(f"处理验证码时出错: {e}")



    def _initialize_iot_devices(self):
        """初始化物联网设备"""
        from src.iot.thing_manager import ThingManager
        from src.iot.things.lamp import Lamp
        from src.iot.things.speaker import Speaker
        from src.iot.things.music_player import MusicPlayer
        from src.iot.things.CameraVL.Camera import Camera
        from src.iot.things.query_bridge_rag import QueryBridgeRAG
        # 获取物联网设备管理器实例
        thing_manager = ThingManager.get_instance()

        # 添加设备
        thing_manager.add_thing(Lamp())
        thing_manager.add_thing(Speaker())
        thing_manager.add_thing(MusicPlayer())
        thing_manager.add_thing(Camera())
        thing_manager.add_thing(QueryBridgeRAG())
        logger.info("物联网设备初始化完成")

    def _handle_iot_message(self, data):
        """处理物联网消息"""
        from src.iot.thing_manager import ThingManager
        thing_manager = ThingManager.get_instance()

        commands = data.get("commands", [])
        print(commands)
        for command in commands:
            try:
                result = thing_manager.invoke(command)
                logger.info(f"执行物联网命令结果: {result}")

                # 命令执行后更新设备状态
                self.schedule(lambda: self._update_iot_states())
            except Exception as e:
                logger.error(f"执行物联网命令失败: {e}")

    def _update_iot_states(self):
        """更新物联网设备状态"""
        from src.iot.thing_manager import ThingManager
        thing_manager = ThingManager.get_instance()

        # 获取当前设备状态
        states_json = thing_manager.get_states_json()

        # 发送状态更新
        asyncio.run_coroutine_threadsafe(
            self.protocol.send_iot_states(states_json),
            self.loop
        )
        logger.info("物联网设备状态已更新")

    def _update_wake_word_detector_stream(self):
        """更新唤醒词检测器的音频流"""
        if self.wake_word_detector and self.audio_codec:
            shared_stream = self.audio_codec.get_shared_input_stream()
            if shared_stream and self.wake_word_detector.is_running():
                self.wake_word_detector.update_stream(shared_stream)
                logger.info("已更新唤醒词检测器的音频流")

    async def _on_audio_config_changed(self, new_config):
        """处理音频配置变更"""
        logger.info(f"音频配置已变更，重新初始化音频编解码器")

        # 安全地关闭旧的编解码器
        if self.audio_codec:
            # 暂停任何活动的操作
            current_state = self.device_state
            self.set_device_state(DeviceState.IDLE)

            # 关闭旧的编解码器
            self.audio_codec.close()
            self.audio_codec = None

            # 重新初始化音频编解码器
            self._initialize_audio()

            # 恢复之前的状态
            self.set_device_state(current_state)

            # 如果有唤醒词检测器，更新其音频流
            self._update_wake_word_detector_stream()

            logger.info("音频编解码器重新初始化完成")


if __name__ == "__main__":
    app = Application.get_instance()
    app.run()