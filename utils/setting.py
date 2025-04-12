import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

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
# 配置管理 (集中管理所有配置)
# --------------------------
class AppSettings(BaseSettings):
    # 服务端配置
    host: str = "0.0.0.0"
    port: int = 9800
    websocket_path: str = "/ws"
    ping_interval: int = 20  # 心跳间隔（秒）
    max_message_size: int = 1024 * 1024  # 1MB

    # 上游WS服务配置
    # 10.239.20.184:8000
    upstream_ws_host: str = "192.168.1.4"
    upstream_ws_port: int = 8000
    upstream_ws_path: str = "/ws"
    upstream_use_ssl: bool = False

    # 身份认证配置
    device_id: str = "f8:e4:e3:ad:36:34"
    client_id: str = "acb42140-a2d1-40e7-944f-591ac3edfad4"
    auth_token: str = "test-token"

    # 音频配置
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_frame_duration: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

settings = AppSettings()


# --------------------------
# 配置类（支持类型注解）
# --------------------------
class DebugConfig:
    # ws://192.168.1.4:8000
    HOST: str = "localhost"  # 服务地址
    # HOST: str = "192.168.1.4"  # 服务地址
    PORT: int = 9800  # 服务端口
    # PORT: int = 8000  # 服务端口
    PATH: str = "/ws"  # WebSocket路径
    USE_SSL: bool = False  # 是否启用wss
    HEADERS: dict = {"session_id":"123123"}

    TEST_MESSAGES: list[bytes] = []
    STRESS_CLIENTS: int = 5  # 并发客户端数量
    RECONNECT_RETRIES: int = 3  # 重连尝试次数
    TIMEOUT: float = 10.0  # 超时时间（秒）
    LOG_VERBOSE: bool = True  # 详细日志模式