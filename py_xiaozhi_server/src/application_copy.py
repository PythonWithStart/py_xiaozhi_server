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
# 导入系统相关库，用于与操作系统进行交互
import sys
# 导入路径操作库，用于处理文件和目录路径
from pathlib import Path

# 在导入 opuslib 之前处理 opus 动态库
from src.utils.system_info import setup_opus
# 调用 setup_opus 函数，确保 opus 动态库正确加载
setup_opus()

# 现在导入 opuslib
try:
    # 尝试导入 opuslib 库，用于音频编解码
    import opuslib  # noqa: F401
except Exception as e:
    # 若导入失败，打印错误信息
    print(f"导入 opuslib 失败: {e}")
    # 提示用户确保 opus 动态库已正确安装或位于正确的位置
    print("请确保 opus 动态库已正确安装或位于正确的位置")
    # 退出程序并返回状态码 1 表示异常退出
    sys.exit(1)

# 从 mqtt_protocol 模块导入 MqttProtocol 类，用于处理 MQTT 协议通信
from src.protocols.mqtt_protocol import MqttProtocol
# 从 websocket_protocol 模块导入 WebsocketProtocol 类，用于处理 WebSocket 协议通信
from src.protocols.websocket_protocol import WebsocketProtocol
# 从 constants 模块导入一些常量，如设备状态、事件类型、音频配置等
from src.constants.constants import (
    DeviceState, EventType, AudioConfig, 
    AbortReason, ListeningMode
)
# 从 display 模块导入 gui_display 和 cli_display 模块，用于显示界面相关操作
from src.display import gui_display, cli_display
# 从 config_manager 模块导入 ConfigManager 类，用于管理配置文件
from src.utils.config_manager import ConfigManager

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

        # 获取配置管理器实例
        self.config = ConfigManager.get_instance()

        # 状态变量
        # 设备当前状态，初始为空闲状态
        self.device_state = DeviceState.IDLE
        # 是否检测到语音
        self.voice_detected = False
        # 是否持续监听
        self.keep_listening = False
        # 是否中止
        self.aborted = False
        # 当前显示的文本
        self.current_text = ""
        # 当前的表情
        self.current_emotion = "neutral"

        # 音频处理相关
        # 音频编解码器，将在 _initialize_audio 中初始化
        self.audio_codec = None
        # TTS（文本转语音）是否正在播放
        self.is_tts_playing = False

        # 事件循环和线程
        # 创建一个新的异步事件循环
        self.loop = asyncio.new_event_loop()
        # 事件循环线程
        self.loop_thread = None
        # 程序是否正在运行
        self.running = False
        # 音频输入事件线程
        self.input_event_thread = None
        # 音频输出事件线程
        self.output_event_thread = None

        # 任务队列和锁
        # 主任务列表
        self.main_tasks = []
        # 线程锁，用于保护共享资源
        self.mutex = threading.Lock()

        # 协议实例
        # 通信协议实例，将在 set_protocol_type 中初始化
        self.protocol = None

        # 回调函数
        # 状态变化回调函数列表
        self.on_state_changed_callbacks = []

        # 初始化事件对象
        self.events = {
            # 调度事件
            EventType.SCHEDULE_EVENT: threading.Event(),
            # 音频输入准备好事件
            EventType.AUDIO_INPUT_READY_EVENT: threading.Event(),
            # 音频输出准备好事件
            EventType.AUDIO_OUTPUT_READY_EVENT: threading.Event()
        }

        # 创建显示界面
        # 显示界面实例，将在 _initialize_display 或 _initialize_cli 中初始化
        self.display = None

        # 添加唤醒词检测器
        # 唤醒词检测器实例
        self.wake_word_detector = None
        # 初始化唤醒词检测器
        self._initialize_wake_word_detector()

    def run(self, **kwargs):
        """启动应用程序"""
        # 打印传入的关键字参数
        print(kwargs)
        # 获取显示模式，默认为 'gui'
        mode = kwargs.get('mode', 'gui')
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

        # 初始化物联网设备
        self._initialize_iot_devices()

        # 启动主循环线程
        main_loop_thread = threading.Thread(target=self._main_loop)
        # 设置为守护线程，主线程退出时自动退出
        main_loop_thread.daemon = True
        # 启动主循环线程
        main_loop_thread.start()
        # 设置显示类型
        self.set_display_type(mode)
        # 启动GUI
        self.display.start()

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

        # 初始化音频编解码器
        self._initialize_audio()

        # 初始化并启动唤醒词检测
        self._initialize_wake_word_detector()
        
        # 设置协议回调
        self.protocol.on_network_error = self._on_network_error
        self.protocol.on_incoming_audio = self._on_incoming_audio
        self.protocol.on_incoming_json = self._on_incoming_json
        self.protocol.on_audio_channel_opened = self._on_audio_channel_opened
        self.protocol.on_audio_channel_closed = self._on_audio_channel_closed
        self.protocol.on_audio_config_changed = self._on_audio_config_changed  # 添加音频配置变更回调

        # 记录日志，表示应用程序初始化完成
        logger.info("应用程序初始化完成")

    def _initialize_audio(self):
        """初始化音频设备和编解码器"""
        try:
            # 从 audio_codec 模块导入 AudioCodec 类
            from src.audio_codecs.audio_codec import AudioCodec
            # 创建 AudioCodec 实例
            self.audio_codec = AudioCodec()
            # 记录日志，表示音频编解码器初始化成功
            logger.info("音频编解码器初始化成功")
            
            # 记录音量控制状态
            has_volume_control = (
                hasattr(self.display, 'volume_controller') and 
                self.display.volume_controller
            )
            if has_volume_control:
                # 记录日志，表示系统音量控制已启用
                logger.info("系统音量控制已启用")
            else:
                # 记录日志，表示系统音量控制未启用，将使用模拟音量控制
                logger.info("系统音量控制未启用，将使用模拟音量控制")
            
        except Exception as e:
            # 记录日志，表示初始化音频设备失败
            logger.error(f"初始化音频设备失败: {e}")
            # 显示警告信息
            self.alert("错误", f"初始化音频设备失败: {e}")

    def _initialize_display(self):
        """初始化显示界面"""
        # 创建 GuiDisplay 实例
        self.display = gui_display.GuiDisplay()

        # 设置回调函数
        self.display.set_callbacks(
            # 按下回调函数，调用 start_listening 方法
            press_callback=self.start_listening,
            # 释放回调函数，调用 stop_listening 方法
            release_callback=self.stop_listening,
            # 状态回调函数，调用 _get_status_text 方法
            status_callback=self._get_status_text,
            # 文本回调函数，调用 _get_current_text 方法
            text_callback=self._get_current_text,
            # 表情回调函数，调用 _get_current_emotion 方法
            emotion_callback=self._get_current_emotion,
            # 模式回调函数，调用 _on_mode_changed 方法
            mode_callback=self._on_mode_changed,
            # 自动回调函数，调用 toggle_chat_state 方法
            auto_callback=self.toggle_chat_state,
            # 中止回调函数，调用 abort_speaking 方法
            abort_callback=lambda: self.abort_speaking(
                AbortReason.WAKE_WORD_DETECTED
            )
        )

    def _initialize_cli(self):
        # 创建 CliDisplay 实例
        self.display = cli_display.CliDisplay()
        # 设置回调函数
        self.display.set_callbacks(
            # 自动回调函数，调用 toggle_chat_state 方法
            auto_callback=self.toggle_chat_state,
            # 中止回调函数，调用 abort_speaking 方法
            abort_callback=lambda: self.abort_speaking(
                AbortReason.WAKE_WORD_DETECTED
            ),
            # 状态回调函数，调用 _get_status_text 方法
            status_callback=self._get_status_text,
            # 文本回调函数，调用 _get_current_text 方法
            text_callback=self._get_current_text,
            # 表情回调函数，调用 _get_current_emotion 方法
            emotion_callback=self._get_current_emotion
        )

    def set_protocol_type(self, protocol_type: str):
        """设置协议类型"""
        if protocol_type == 'mqtt':
            # 如果协议类型为 'mqtt'，创建 MqttProtocol 实例
            self.protocol = MqttProtocol(self.loop)
        else:  # websocket
            # 否则，创建 WebsocketProtocol 实例
            self.protocol = WebsocketProtocol()

    def set_display_type(self, mode: str):
        if mode == 'gui':
            # 如果显示模式为 'gui'，初始化 GUI 显示界面
            self._initialize_display()
        else:
            # 否则，初始化 CLI 显示界面
            self._initialize_cli()

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

                    if event_type == EventType.AUDIO_INPUT_READY_EVENT:
                        # 如果是音频输入准备好事件，调用 _handle_input_audio 方法处理音频输入
                        self._handle_input_audio()
                    elif event_type == EventType.AUDIO_OUTPUT_READY_EVENT:
                        # 如果是音频输出准备好事件，调用 _handle_output_audio 方法处理音频输出
                        self._handle_output_audio()
                    elif event_type == EventType.SCHEDULE_EVENT:
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

    def _handle_input_audio(self):
        """处理音频输入"""
        if self.device_state != DeviceState.LISTENING:
            # 如果设备状态不是监听状态，直接返回
            return

        # 读取并发送音频数据
        encoded_data = self.audio_codec.read_audio()
        if (encoded_data and self.protocol and 
                self.protocol.is_audio_channel_opened()):
            # 如果有编码后的音频数据，且协议实例存在，且音频通道已打开
            # 异步发送音频数据
            asyncio.run_coroutine_threadsafe(
                self.protocol.send_audio(encoded_data),
                self.loop
            )

    def _handle_output_audio(self):
        """处理音频输出"""
        if self.device_state != DeviceState.SPEAKING:
            # 如果设备状态不是说话状态，直接返回
            return
        # 设置 TTS 播放状态为 True
        self.is_tts_playing = True
        # 播放音频
        self.audio_codec.play_audio()

    def _on_network_error(self, message):
        """网络错误回调"""
        # 设置持续监听状态为 False
        self.keep_listening = False
        # 设置设备状态为空闲
        self.set_device_state(DeviceState.IDLE)
        # 恢复唤醒词检测
        if self.wake_word_detector and self.wake_word_detector.paused:
            self.wake_word_detector.resume()
        
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

    def _on_incoming_audio(self, data):
        """接收音频数据回调"""
        if self.device_state == DeviceState.SPEAKING:
            # 如果设备状态为说话状态，将音频数据写入音频编解码器的队列
            self.audio_codec.write_audio(data)
            # 设置音频输出准备好事件标志
            self.events[EventType.AUDIO_OUTPUT_READY_EVENT].set()

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
        # 设置中止状态为 False
        self.aborted = False
        # 设置 TTS 播放状态为 True
        self.is_tts_playing = True
        # 清空可能存在的旧音频数据
        self.audio_codec.clear_audio_queue()

        if self.device_state == DeviceState.IDLE or self.device_state == DeviceState.LISTENING:
            # 如果设备状态为空闲或监听状态，设置设备状态为说话状态
            self.set_device_state(DeviceState.SPEAKING)
            
            # 注释掉恢复VAD检测器的代码
            # if hasattr(self, 'vad_detector') and self.vad_detector:
            #     self.vad_detector.resume()

    def _handle_tts_stop(self):
        """处理TTS停止事件"""
        if self.device_state == DeviceState.SPEAKING:
            # 给音频播放一个缓冲时间，确保所有音频都播放完毕
            def delayed_state_change():
                # 等待音频队列清空
                # 增加等待重试次数，确保音频可以完全播放完毕
                max_wait_attempts = 30  # 增加等待尝试次数
                wait_interval = 0.1  # 每次等待的时间间隔
                attempts = 0
                
                # 等待直到队列为空或超过最大尝试次数
                while not self.audio_codec.audio_decode_queue.empty() and attempts < max_wait_attempts:
                    time.sleep(wait_interval)
                    attempts += 1
                    
                # 确保所有数据都被播放出来
                # 再额外等待一点时间确保最后的数据被处理
                if self.is_tts_playing:
                    time.sleep(0.5)
                    
                # 设置TTS播放状态为False
                self.is_tts_playing = False
                
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
        # 调度启动音频流方法
        self.schedule(lambda: self._start_audio_streams())
        
        # 发送物联网设备描述符
        from src.iot.thing_manager import ThingManager
        # 获取 ThingManager 实例
        thing_manager = ThingManager.get_instance()
        # 异步发送物联网设备描述符
        asyncio.run_coroutine_threadsafe(
            self.protocol.send_iot_descriptors(thing_manager.get_descriptors_json()),
            self.loop
        )

    def _start_audio_streams(self):
        """启动音频流"""
        try:
            # 不再关闭和重新打开流，只确保它们处于活跃状态
            if self.audio_codec.input_stream and not self.audio_codec.input_stream.is_active():
                try:
                    # 启动音频输入流
                    self.audio_codec.input_stream.start_stream()
                except Exception as e:
                    # 记录日志，表示启动输入流时出错
                    logger.warning(f"启动输入流时出错: {e}")
                    # 只有在出错时才重新初始化
                    self.audio_codec._reinitialize_input_stream()

            if self.audio_codec.output_stream and not self.audio_codec.output_stream.is_active():
                try:
                    # 启动音频输出流
                    self.audio_codec.output_stream.start_stream()
                except Exception as e:
                    # 记录日志，表示启动输出流时出错
                    logger.warning(f"启动输出流时出错: {e}")
                    # 只有在出错时才重新初始化
                    self.audio_codec._reinitialize_output_stream()

            # 设置事件触发器
            if self.input_event_thread is None or not self.input_event_thread.is_alive():
                # 创建音频输入事件触发线程
                self.input_event_thread = threading.Thread(
                    target=self._audio_input_event_trigger, daemon=True)
                # 启动音频输入事件触发线程
                self.input_event_thread.start()
                # 记录日志，表示已启动输入事件触发线程
                logger.info("已启动输入事件触发线程")

            # 检查输出事件线程
            if self.output_event_thread is None or not self.output_event_thread.is_alive():
                # 创建音频输出事件触发线程
                self.output_event_thread = threading.Thread(
                    target=self._audio_output_event_trigger, daemon=True)
                # 启动音频输出事件触发线程
                self.output_event_thread.start()
                # 记录日志，表示已启动输出事件触发线程
                logger.info("已启动输出事件触发线程")

            # 记录日志，表示音频流已启动
            logger.info("音频流已启动")
        except Exception as e:
            # 记录日志，表示启动音频流失败
            logger.error(f"启动音频流失败: {e}")

    def _audio_input_event_trigger(self):
        """音频输入事件触发器"""
        while self.running:
            try:
                # 只有在主动监听状态下才触发输入事件
                if self.device_state == DeviceState.LISTENING and self.audio_codec.input_stream:
                    # 设置音频输入准备好事件标志
                    self.events[EventType.AUDIO_INPUT_READY_EVENT].set()
            except OSError as e:
                # 记录日志，表示音频输入流错误
                logger.error(f"音频输入流错误: {e}")
                # 不要退出循环，继续尝试
                time.sleep(0.5)
            except Exception as e:
                # 记录日志，表示音频输入事件触发器错误
                logger.error(f"音频输入事件触发器错误: {e}")
                time.sleep(0.5)

            # 按帧时长触发
            time.sleep(AudioConfig.FRAME_DURATION / 1000)

    def _audio_output_event_trigger(self):
        """音频输出事件触发器"""
        while self.running:
            try:
                # 确保输出流是活跃的
                if (self.device_state == DeviceState.SPEAKING and 
                    self.audio_codec and 
                    self.audio_codec.output_stream):
                    
                    # 如果输出流不活跃，尝试重新激活
                    if not self.audio_codec.output_stream.is_active():
                        try:
                            # 启动音频输出流
                            self.audio_codec.output_stream.start_stream()
                        except Exception as e:
                            # 记录日志，表示启动输出流失败，尝试重新初始化
                            logger.warning(f"启动输出流失败，尝试重新初始化: {e}")
                            # 重新初始化音频输出流
                            self.audio_codec._reinitialize_output_stream()
                    
                    # 当队列中有数据时才触发事件
                    if not self.audio_codec.audio_decode_queue.empty():
                        # 设置音频输出准备好事件标志
                        self.events[EventType.AUDIO_OUTPUT_READY_EVENT].set()
            except Exception as e:
                # 记录日志，表示音频输出事件触发器错误
                logger.error(f"音频输出事件触发器错误: {e}")
                
            # 稍微延长检查间隔
            time.sleep(0.02)

    async def _on_audio_channel_closed(self):
        """音频通道关闭回调"""
        # 记录日志，表示音频通道已关闭
        logger.info("音频通道已关闭")
        # 设置为空闲状态但不关闭音频流
        self.set_device_state(DeviceState.IDLE)
        # 设置持续监听状态为 False
        self.keep_listening = False
        
        # 确保唤醒词检测正常工作
        if self.wake_word_detector:
            if not self.wake_word_detector.is_running():
                # 记录日志，表示在空闲状态下启动唤醒词检测
                logger.info("在空闲状态下启动唤醒词检测")
                # 获取最新的共享流
                if hasattr(self, 'audio_codec') and self.audio_codec:
                    shared_stream = self.audio_codec.get_shared_input_stream()
                    if shared_stream:
                        # 使用共享流启动唤醒词检测
                        self.wake_word_detector.start(shared_stream)
                    else:
                        # 否则，使用独立音频流启动唤醒词检测
                        self.wake_word_detector.start()
                else:
                    # 使用独立音频流启动唤醒词检测
                    self.wake_word_detector.start()
            elif self.wake_word_detector.paused:
                # 记录日志，表示在空闲状态下恢复唤醒词检测
                logger.info("在空闲状态下恢复唤醒词检测")
                # 恢复唤醒词检测
                self.wake_word_detector.resume()

    def set_device_state(self, state):
        """设置设备状态"""
        if self.device_state == state:
            # 如果设备状态没有变化，直接返回
            return

        old_state = self.device_state

        # 如果从 SPEAKING 状态切换出去，确保音频播放完成并设置TTS播放状态为False
        if old_state == DeviceState.SPEAKING:
            # 等待音频队列清空
            self.audio_codec.wait_for_audio_complete()
            # 设置 TTS 播放状态为 False
            self.is_tts_playing = False

        # 设置设备状态
        self.device_state = state
        # 记录日志，表示状态变更
        logger.info(f"状态变更: {old_state} -> {state}")

        # 根据状态执行相应操作
        if state == DeviceState.IDLE:
            # 更新显示界面的状态为待命
            self.display.update_status("待命")
            # 更新显示界面的表情为中立
            self.display.update_emotion("😶")
            # 恢复唤醒词检测（添加安全检查）
            if self.wake_word_detector and hasattr(self.wake_word_detector, 'paused') and self.wake_word_detector.paused:
                # 恢复唤醒词检测
                self.wake_word_detector.resume()
                # 记录日志，表示唤醒词检测已恢复
                logger.info("唤醒词检测已恢复")
            # 恢复音频输入流
            if self.audio_codec and self.audio_codec.is_input_paused():
                # 恢复音频输入流
                self.audio_codec.resume_input()
        elif state == DeviceState.CONNECTING:
            # 更新显示界面的状态为连接中
            self.display.update_status("连接中...")
        elif state == DeviceState.LISTENING:
            # 更新显示界面的状态为聆听中
            self.display.update_status("聆听中...")
            # 更新显示界面的表情为开心
            self.display.update_emotion("🙂")
            # 暂停唤醒词检测（添加安全检查）
            if self.wake_word_detector and hasattr(self.wake_word_detector, 'is_running') and self.wake_word_detector.is_running():
                # 暂停唤醒词检测
                self.wake_word_detector.pause()
                # 记录日志，表示唤醒词检测已暂停
                logger.info("唤醒词检测已暂停")
            # 确保音频输入流活跃
            if self.audio_codec:
                if self.audio_codec.is_input_paused():
                    # 恢复音频输入流
                    self.audio_codec.resume_input()
        elif state == DeviceState.SPEAKING:
            # 更新显示界面的状态为说话中
            self.display.update_status("说话中...")
            # 暂停唤醒词检测（添加安全检查）
            if self.wake_word_detector and hasattr(self.wake_word_detector, 'is_running') and self.wake_word_detector.is_running():
                # 暂停唤醒词检测
                self.wake_word_detector.pause()
                # 记录日志，表示唤醒词检测已暂停
                logger.info("唤醒词检测已暂停")
            # 暂停音频输入流以避免自我监听
            if self.audio_codec and not self.audio_codec.is_input_paused():
                # 暂停音频输入流
                self.audio_codec.pause_input()

        # 通知状态变化
        for callback in self.on_state_changed_callbacks:
            try:
                # 调用状态变化回调函数
                callback(state)
            except Exception as e:
                # 记录日志，表示执行状态变化回调时出错
                logger.error(f"执行状态变化回调时出错: {e}")

    def _get_status_text(self):
        """获取当前状态文本"""
        states = {
            DeviceState.IDLE: "待命",
            DeviceState.CONNECTING: "连接中...",
            DeviceState.LISTENING: "聆听中...",
            DeviceState.SPEAKING: "说话中..."
        }
        # 根据设备状态返回对应的状态文本
        return states.get(self.device_state, "未知")

    def _get_current_text(self):
        """获取当前显示文本"""
        return self.current_text

    def _get_current_emotion(self):
        """获取当前表情"""
        emotions = {
            "neutral": "😶",
            "happy": "🙂",
            "laughing": "😆",
            "funny": "😂",
            "sad": "😔",
            "angry": "😠",
            "crying": "😭",
            "loving": "😍",
            "embarrassed": "😳",
            "surprised": "😲",
            "shocked": "😱",
            "thinking": "🤔",
            "winking": "😉",
            "cool": "😎",
            "relaxed": "😌",
            "delicious": "🤤",
            "kissy": "😘",
            "confident": "😏",
            "sleepy": "😴",
            "silly": "😜",
            "confused": "🙄"
        }
        # 根据当前表情返回对应的表情符号
        return emotions.get(self.current_emotion, "😶")

    def set_chat_message(self, role, message):
        """设置聊天消息"""
        # 设置当前显示文本
        self.current_text = message
        # 更新显示
        if self.display:
            # 更新显示界面的文本
            self.display.update_text(message)

    def set_emotion(self, emotion):
        """设置表情"""
        # 设置当前表情
        self.current_emotion = emotion
        # 更新显示
        if self.display:
            # 更新显示界面的表情
            self.display.update_emotion(self._get_current_emotion())

    def start_listening(self):
        """开始监听"""
        # 调度开始监听的实现方法
        self.schedule(self._start_listening_impl)

    def _start_listening_impl(self):
        """开始监听的实现"""
        if not self.protocol:
            # 记录日志，表示协议未初始化
            logger.error("协议未初始化")
            return

        # 设置持续监听状态为 False
        self.keep_listening = False

        # 检查唤醒词检测器是否存在
        if self.wake_word_detector:
            # 暂停唤醒词检测
            self.wake_word_detector.pause()

        if self.device_state == DeviceState.IDLE:
            # 设置设备状态为连接中
            self.set_device_state(DeviceState.CONNECTING)

            # 尝试打开音频通道
            if not self.protocol.is_audio_channel_opened():
                try:
                    # 等待异步操作完成
                    future = asyncio.run_coroutine_threadsafe(
                        self.protocol.open_audio_channel(),
                        self.loop
                    )
                    # 等待操作完成并获取结果
                    success = future.result(timeout=10.0)  # 添加超时时间
                    
                    if not success:
                        # 弹出错误提示
                        self.alert("错误", "打开音频通道失败")
                        # 设置设备状态为空闲
                        self.set_device_state(DeviceState.IDLE)
                        return
                        
                except Exception as e:
                    # 记录日志，表示打开音频通道时发生错误
                    logger.error(f"打开音频通道时发生错误: {e}")
                    # 弹出错误提示
                    self.alert("错误", f"打开音频通道失败: {str(e)}")
                    # 设置设备状态为空闲
                    self.set_device_state(DeviceState.IDLE)
                    return

            # 异步发送开始监听消息
            asyncio.run_coroutine_threadsafe(
                self.protocol.send_start_listening(ListeningMode.MANUAL),
                self.loop
            )
            # 设置设备状态为监听中
            self.set_device_state(DeviceState.LISTENING)
        elif self.device_state == DeviceState.SPEAKING:
            if not self.aborted:
                # 中止语音输出
                self.abort_speaking(AbortReason.WAKE_WORD_DETECTED)

    async def _open_audio_channel_and_start_manual_listening(self):
        """打开音频通道并开始手动监听"""
        if not await self.protocol.open_audio_channel():
            # 设置设备状态为空闲
            self.set_device_state(DeviceState.IDLE)
            # 弹出错误提示
            self.alert("错误", "打开音频通道失败")
            return

        # 异步发送开始监听消息
        await self.protocol.send_start_listening(ListeningMode.MANUAL)
        # 设置设备状态为监听中
        self.set_device_state(DeviceState.LISTENING)

    def toggle_chat_state(self):
        """切换聊天状态"""
        # 检查唤醒词检测器是否存在
        if self.wake_word_detector:
            # 暂停唤醒词检测
            self.wake_word_detector.pause()
        # 调度切换聊天状态的实现方法
        self.schedule(self._toggle_chat_state_impl)

    def _toggle_chat_state_impl(self):
        """切换聊天状态的具体实现"""
        # 检查协议是否已初始化
        if not self.protocol:
            # 记录日志，表示协议未初始化
            logger.error("协议未初始化")
            return

        # 如果设备当前处于空闲状态，尝试连接并开始监听
        if self.device_state == DeviceState.IDLE:
            # 设置设备状态为连接中
            self.set_device_state(DeviceState.CONNECTING)

            # 尝试打开音频通道
            if not self.protocol.is_audio_channel_opened():
                try:
                    # 等待异步操作完成
                    future = asyncio.run_coroutine_threadsafe(
                        self.protocol.open_audio_channel(),
                        self.loop
                    )
                    # 等待操作完成并获取结果
                    success = future.result(timeout=10.0)  # 添加超时时间
                    
                    if not success:
                        # 弹出错误提示
                        self.alert("错误", "打开音频通道失败")
                        # 设置设备状态为空闲
                        self.set_device_state(DeviceState.IDLE)
                        return
                        
                except Exception as e:
                    # 记录日志，表示打开音频通道时发生错误
                    logger.error(f"打开音频通道时发生错误: {e}")
                    # 弹出错误提示
                    self.alert("错误", f"打开音频通道失败: {str(e)}")
                    # 设置设备状态为空闲
                    self.set_device_state(DeviceState.IDLE)
                    return

            # 设置持续监听状态为 True
            self.keep_listening = True
            # 启动自动停止的监听模式
            asyncio.run_coroutine_threadsafe(
                self.protocol.send_start_listening(ListeningMode.AUTO_STOP),
                self.loop
            )
            # 设置设备状态为监听中
            self.set_device_state(DeviceState.LISTENING)

        # 如果设备正在说话，停止当前说话
        elif self.device_state == DeviceState.SPEAKING:
            # 中止说话
            self.abort_speaking(AbortReason.NONE)

        # 如果设备正在监听，关闭音频通道
        elif self.device_state == DeviceState.LISTENING:
            # 异步关闭音频通道
            asyncio.run_coroutine_threadsafe(
                self.protocol.close_audio_channel(),
                self.loop
            )

    def stop_listening(self):
        """停止监听"""
        # 调度停止监听的实现方法
        self.schedule(self._stop_listening_impl)

    def _stop_listening_impl(self):
        """停止监听的实现"""
        if self.device_state == DeviceState.LISTENING:
            # 异步发送停止监听消息
            asyncio.run_coroutine_threadsafe(
                self.protocol.send_stop_listening(),
                self.loop
            )
            # 设置设备状态为空闲
            self.set_device_state(DeviceState.IDLE)

    def abort_speaking(self, reason):
        """中止语音输出"""
        # 如果已经中止，不要重复处理
        if self.aborted:
            # 记录日志，表示已经中止，忽略重复的中止请求
            logger.debug(f"已经中止，忽略重复的中止请求: {reason}")
            return
        
        # 记录日志，表示中止语音输出
        logger.info(f"中止语音输出，原因: {reason}")
        # 设置中止状态为 True
        self.aborted = True
        
        # 设置TTS播放状态为False
        self.is_tts_playing = False
        
        # 注释掉确保VAD检测器暂停的代码
        # if hasattr(self, 'vad_detector') and self.vad_detector:
        #     self.vad_detector.pause()
        
        # 异步发送中止语音输出消息
        asyncio.run_coroutine_threadsafe(
            self.protocol.send_abort_speaking(reason),
            self.loop
        )
        # 设置设备状态为空闲
        self.set_device_state(DeviceState.IDLE)

        # 添加此代码：当用户主动打断时自动进入录音模式
        if reason == AbortReason.WAKE_WORD_DETECTED and self.keep_listening and self.protocol.is_audio_channel_opened():
            # 短暂延迟确保abort命令被处理
            def start_listening_after_abort():
                time.sleep(0.2)  # 短暂延迟
                # 设置设备状态为空闲
                self.set_device_state(DeviceState.IDLE)
                # 调度切换聊天状态方法
                self.schedule(lambda: self.toggle_chat_state())

            # 启动延迟开始监听线程
            threading.Thread(target=start_listening_after_abort, daemon=True).start()

    def alert(self, title, message):
        """显示警告信息"""
        # 记录日志，表示警告信息
        logger.warning(f"警告: {title}, {message}")
        # 在GUI上显示警告
        if self.display:
            # 更新显示界面的文本
            self.display.update_text(f"{title}: {message}")

    def on_state_changed(self, callback):
        """注册状态变化回调"""
        # 将回调函数添加到状态变化回调函数列表
        self.on_state_changed_callbacks.append(callback)

    def shutdown(self):
        """关闭应用程序"""
        # 记录日志，表示正在关闭应用程序
        logger.info("正在关闭应用程序...")
        # 设置程序运行状态为 False
        self.running = False

        # 关闭音频编解码器
        if self.audio_codec:
            # 关闭音频编解码器
            self.audio_codec.close()

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

        # 停止唤醒词检测
        if self.wake_word_detector:
            # 停止唤醒词检测
            self.wake_word_detector.stop()

        # 关闭VAD检测器
        # if hasattr(self, 'vad_detector') and self.vad_detector:
        #     self.vad_detector.stop()

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
                self.alert("验证码", f"您的验证码是: {code}")

        except Exception as e:
            # 记录日志，表示处理验证码时出错
            logger.error(f"处理验证码时出错: {e}")

    def _on_mode_changed(self, auto_mode):
        """处理对话模式变更"""
        # 只有在IDLE状态下才允许切换模式
        if self.device_state != DeviceState.IDLE:
            # 弹出提示信息
            self.alert("提示", "只有在待命状态下才能切换对话模式")
            return False

        # 设置持续监听状态
        self.keep_listening = auto_mode
        # 记录日志，表示对话模式已切换
        logger.info(f"对话模式已切换为: {'自动' if auto_mode else '手动'}")
        return True

    def _initialize_wake_word_detector(self):
        """初始化唤醒词检测器"""
        # 首先检查配置中是否启用了唤醒词功能
        if not self.config.get_config('USE_WAKE_WORD', False):
            # 记录日志，表示唤醒词功能已在配置中禁用，跳过初始化
            logger.info("唤醒词功能已在配置中禁用，跳过初始化")
            # 设置唤醒词检测器为 None
            self.wake_word_detector = None
            return
        
        try:
            # 从 wake_word_detect 模块导入 WakeWordDetector 类
            from src.audio_processing.wake_word_detect import WakeWordDetector
            import sys
            
            # 获取模型路径配置
            model_path_config = (
                self.config.get_config(
                    "WAKE_WORD_MODEL_PATH", 
                    "models/vosk-model-small-cn-0.22"
                )
            )

            # 对于打包环境
            if getattr(sys, 'frozen', False):
                if hasattr(sys, '_MEIPASS'):
                    base_path = Path(sys._MEIPASS)
                else:
                    base_path = Path(sys.executable).parent
                model_path = base_path / model_path_config
                # 记录日志，表示打包环境下使用的模型路径
                logger.info(f"打包环境下使用模型路径: {model_path}")
            else:
                # 开发环境
                base_path = Path(__file__).parent.parent
                model_path = base_path / model_path_config
                # 记录日志，表示开发环境下使用的模型路径
                logger.info(f"开发环境下使用模型路径: {model_path}")
            
            # 检查模型路径
            if not model_path.exists():
                # 记录日志，表示模型路径不存在
                logger.error(f"模型路径不存在: {model_path}")
                # 自动禁用唤醒词功能
                self.config.update_config("USE_WAKE_WORD", False)
                # 设置唤醒词检测器为 None
                self.wake_word_detector = None
                return
            
            # 创建 WakeWordDetector 实例
            self.wake_word_detector = WakeWordDetector(
                wake_words=self.config.get_config("WAKE_WORDS"),
                model_path=str(model_path)  # 转为字符串，因为Vosk API可能需要字符串路径
            )
            
            # 如果唤醒词检测器被禁用（内部故障），则更新配置
            if not getattr(self.wake_word_detector, 'enabled', True):
                # 记录日志，表示唤醒词检测器被禁用（内部故障）
                logger.warning("唤醒词检测器被禁用（内部故障）")
                # 自动禁用唤醒词功能
                self.config.update_config("USE_WAKE_WORD", False)
                # 设置唤醒词检测器为 None
                self.wake_word_detector = None
                return
            
            # 注册唤醒词检测回调
            self.wake_word_detector.on_detected(self._on_wake_word_detected)
            # 记录日志，表示唤醒词检测器初始化成功
            logger.info("唤醒词检测器初始化成功")

            # 添加错误处理回调
            def on_error(error):
                # 记录日志，表示唤醒词检测错误
                logger.error(f"唤醒词检测错误: {error}")
                # 尝试重新启动检测器
                if self.device_state == DeviceState.IDLE:
                    # 调度重新启动唤醒词检测器方法
                    self.schedule(lambda: self._restart_wake_word_detector())

            self.wake_word_detector.on_error = on_error

            # 确保音频编解码器已初始化
            if hasattr(self, 'audio_codec') and self.audio_codec:
                shared_stream = self.audio_codec.get_shared_input_stream()
                if shared_stream:
                    # 记录日志，表示使用共享的音频输入流启动唤醒词检测器
                    logger.info("使用共享的音频输入流启动唤醒词检测器")
                    # 使用共享流启动唤醒词检测
                    self.wake_word_detector.start(shared_stream)
                else:
                    # 记录日志，表示无法获取共享输入流，唤醒词检测器将使用独立音频流
                    logger.warning("无法获取共享输入流，唤醒词检测器将使用独立音频流")
                    # 使用独立音频流启动唤醒词检测
                    self.wake_word_detector.start()
            else:
                # 记录日志，表示音频编解码器尚未初始化，唤醒词检测器将使用独立音频流
                logger.warning("音频编解码器尚未初始化，唤醒词检测器将使用独立音频流")
                # 使用独立音频流启动唤醒词检测
                self.wake_word_detector.start()

        except Exception as e:
            # 记录日志，表示初始化唤醒词检测器失败
            logger.error(f"初始化唤醒词检测器失败: {e}")
            import traceback
            # 记录详细的错误堆栈信息
            logger.error(traceback.format_exc())
            
            # 禁用唤醒词功能，但不影响程序其他功能
            self.config.update_config("USE_WAKE_WORD", False)
            # 记录日志，表示由于初始化失败，唤醒词功能已禁用，但程序将继续运行
            logger.info("由于初始化失败，唤醒词功能已禁用，但程序将继续运行")
            # 设置唤醒词检测器为 None
            self.wake_word_detector = None

    def _on_wake_word_detected(self, wake_word, full_text):
        """唤醒词检测回调"""
        # 记录日志，表示检测到唤醒词
        logger.info(f"检测到唤醒词: {wake_word} (完整文本: {full_text})")
        # 调度处理唤醒词检测事件方法
        self.schedule(lambda: self._handle_wake_word_detected(wake_word))

    def _handle_wake_word_detected(self, wake_word):
        """处理唤醒词检测事件"""
        if self.device_state == DeviceState.IDLE:
            # 暂停唤醒词检测
            if self.wake_word_detector:
                self.wake_word_detector.pause()

            # 开始连接并监听
            self.set_device_state(DeviceState.CONNECTING)

            # 尝试连接并打开音频通道
            asyncio.run_coroutine_threadsafe(
                self._connect_and_start_listening(wake_word),
                self.loop
            )

    async def _connect_and_start_listening(self, wake_word):
        """连接服务器并开始监听"""
        # 首先尝试连接服务器
        if not await self.protocol.connect():
            # 记录日志，表示连接服务器失败
            logger.error("连接服务器失败")
            # 弹出错误提示
            self.alert("错误", "连接服务器失败")
            # 设置设备状态为空闲
            self.set_device_state(DeviceState.IDLE)
            # 恢复唤醒词检测
            if self.wake_word_detector:
                self.wake_word_detector.resume()
            return

        # 然后尝试打开音频通道
        if not await self.protocol.open_audio_channel():
            # 记录日志，表示打开音频通道失败
            logger.error("打开音频通道失败")
            # 设置设备状态为空闲
            self.set_device_state(DeviceState.IDLE)
            # 弹出错误提示
            self.alert("错误", "打开音频通道失败")
            # 恢复唤醒词检测
            if self.wake_word_detector:
                self.wake_word_detector.resume()
            return

        # 异步发送唤醒词检测到消息
        await self.protocol.send_wake_word_detected(wake_word)
        # 设置为自动监听模式
        self.keep_listening = True
        # 异步发送开始监听消息
        await self.protocol.send_start_listening(ListeningMode.AUTO_STOP)
        # 设置设备状态为监听中
        self.set_device_state(DeviceState.LISTENING)

    def _restart_wake_word_detector(self):
        """重新启动唤醒词检测器"""
        # 记录日志，表示尝试重新启动唤醒词检测器
        logger.info("尝试重新启动唤醒词检测器")
        try:
            # 停止现有的检测器
            if self.wake_word_detector:
                self.wake_word_detector.stop()
                # 给予一些时间让资源释放
                time.sleep(0.5)
            
            # 确保使用最新的共享音频输入流
            if hasattr(self, 'audio_codec') and self.audio_codec:
                shared_stream = self.audio_codec.get_shared_input_stream()
                if shared_stream:
                    # 使用共享流重新启动唤醒词检测
                    self.wake_word_detector.start(shared_stream)
                    # 记录日志，表示使用共享的音频流重新启动唤醒词检测器
                    logger.info("使用共享的音频流重新启动唤醒词检测器")
                else:
                    # 如果无法获取共享流，尝试让检测器创建自己的流
                    self.wake_word_detector.start()
                    # 记录日志，表示使用独立的音频流重新启动唤醒词检测器
                    logger.info("使用独立的音频流重新启动唤醒词检测器")
            else:
                # 使用独立音频流重新启动唤醒词检测
                self.wake_word_detector.start()
                # 记录日志，表示使用独立的音频流重新启动唤醒词检测器
                logger.info("使用独立的音频流重新启动唤醒词检测器")
            
            # 记录日志，表示唤醒词检测器重新启动成功
            logger.info("唤醒词检测器重新启动成功")
            # # 记录日志，表示唤醒词检测器重新启动成功
        except Exception as e:
            logger.error(f"重新启动唤醒词检测器失败: {e}")

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