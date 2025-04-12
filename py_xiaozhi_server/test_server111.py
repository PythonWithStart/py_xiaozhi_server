from src.protocols.websocket_protocol import WebsocketProtocol
from logging import log
import time
import threading
import asyncio
import json

logger = log()


class Application_server():


    async def _initialize_without_connect(self):
        """初始化应用程序组件（不建立连接）"""
        logger.info("正在初始化应用程序...")

        # # 设置设备状态为待命
        # self.set_device_state(DeviceState.IDLE)

        # 初始化音频编解码器
        self._initialize_audio()

        # 设置协议回调
        # self.protocol.on_network_error = self._on_network_error
        # self.protocol.on_incoming_audio = self._on_incoming_audio
        self.protocol.on_incoming_json = self._on_incoming_json
        self.protocol.on_audio_channel_opened = self._on_audio_channel_opened
        self.protocol.on_audio_channel_closed = self._on_audio_channel_closed
        self.protocol.on_audio_config_changed = self._on_audio_config_changed  # 添加音频配置变更回调
        logger.info("应用程序初始化完成")


    def _on_incoming_json(self, json_data):
        """接收JSON数据回调"""
        try:
            if not json_data:
                return

            # 解析JSON数据
            if isinstance(json_data, str):
                data = json.loads(json_data)
            else:
                data = json_data
            print("data", data)
            # 处理不同类型的消息
            msg_type = data.get("type", "")
            if msg_type == "tts":
                self._handle_tts_message(data)
            elif msg_type == "stt":
                self._handle_stt_message(data)
            elif msg_type == "llm":
                self._handle_llm_message(data)
            elif msg_type == "iot":
                self._handle_iot_message(data)
            else:
                logger.warning(f"收到未知类型的消息: {msg_type}")
        except Exception as e:
            logger.error(f"处理JSON消息时出错: {e}")

    # def _on_incoming_audio(self, data):
    #     """接收音频数据回调"""
    #     if self.device_state == DeviceState.SPEAKING:
    #         self.audio_codec.write_audio(data)
    #         self.events[EventType.AUDIO_OUTPUT_READY_EVENT].set()

    def _on_network_error(self, message):
        """网络错误回调"""
        self.keep_listening = False
        # self.set_device_state(DeviceState.IDLE)
        # # 恢复唤醒词检测
        # if self.wake_word_detector and self.wake_word_detector.paused:
        #     self.wake_word_detector.resume()

        # if self.device_state != DeviceState.CONNECTING:
        #     logger.info("检测到连接断开")
        #     # self.set_device_state(DeviceState.IDLE)
        #
        #     # 关闭现有连接，但不关闭音频流
        #     if self.protocol:
        #         asyncio.run_coroutine_threadsafe(
        #             self.protocol.close_audio_channel(),
        #             self.loop
        #         )

    def set_protocol_type(self, protocol_type: str):
        self.protocol = WebsocketProtocol()

    def _run_event_loop(self):
        """运行事件循环的线程函数"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, **kwargs):
        """启动应用程序"""
        print(kwargs)
        mode = kwargs.get('mode', 'gui')
        protocol = kwargs.get('protocol', 'websocket')

        self.set_protocol_type(protocol)

        # 创建并启动事件循环线程
        self.loop_thread = threading.Thread(target=self._run_event_loop)
        self.loop_thread.daemon = True
        self.loop_thread.start()

        # 等待事件循环准备就绪
        time.sleep(0.1)

        # 初始化应用程序（移除自动连接）
        asyncio.run_coroutine_threadsafe(self._initialize_without_connect(), self.loop)

        # 初始化物联网设备
        self._initialize_iot_devices()

        # 启动主循环线程
        main_loop_thread = threading.Thread(target=self._main_loop)
        main_loop_thread.daemon = True
        main_loop_thread.start()
        self.set_display_type(mode)
        # 启动GUI
        self.display.start()



if __name__ == '__main__':
    Application_server()