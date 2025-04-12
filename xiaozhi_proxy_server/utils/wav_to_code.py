import wave
from pydub import AudioSegment
from opuslib import Encoder


def mp3_to_opus_bytecode(mp3_path: str, output_opus_path: str) -> bytes:
    """
    将 MP3 文件转换为 Opus 编码的字节码
    :param mp3_path: 输入 MP3 文件路径
    :param output_opus_path: 输出 Opus 字节码文件路径（可选）
    :return: Opus 字节码数据
    """
    # 1. 读取 MP3 文件并转换为 PCM 数据
    audio = AudioSegment.from_mp3(mp3_path)

    # 2. 统一为 Opus 支持的参数：48kHz 采样率，16-bit 单声道
    audio = audio.set_frame_rate(48000).set_channels(1)
    pcm_data = audio.raw_data  # 获取 PCM 字节数据

    # 3. 初始化 Opus 编码器
    sample_rate = 48000
    channels = 1
    encoder = Encoder(sample_rate, channels, 'audio')

    # 4. 分块编码（每帧 20ms，即 960 个样本）
    frame_size = 960 * 2  # 16-bit 单声道，每个样本 2 字节
    opus_frames = bytearray()

    for i in range(0, len(pcm_data), frame_size):
        chunk = pcm_data[i:i + frame_size]
        if len(chunk) < frame_size:
            chunk += b'\x00' * (frame_size - len(chunk))  # 填充静音数据
        opus_frame = encoder.encode(chunk, frame_size // 2)  # frame_size//2 是样本数
        opus_frames.extend(opus_frame)

    # 5. 保存或返回字节码
    if output_opus_path:
        with open(output_opus_path, 'wb') as f:
            f.write(opus_frames)
    return bytes(opus_frames)


if __name__ == '__main__':
    # 使用示例
    opus_bytes = mp3_to_opus_bytecode("../temp/tts-2025-03-30@4b6c4d683763459286bf4e9c932c312a.mp3", "output.opus")
    print(f"生成的 Opus 字节码长度: {len(opus_bytes)} 字节")