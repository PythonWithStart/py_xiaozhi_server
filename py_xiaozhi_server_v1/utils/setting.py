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