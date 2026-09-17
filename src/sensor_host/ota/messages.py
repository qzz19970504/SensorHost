"""Chinese operator-facing text for OTA NACK codes and session phases."""

from __future__ import annotations


NACK_CODE_ZH: dict[str, str] = {
    "NONE": "无错误",
    "FRAME_CRC": "帧 CRC 校验失败",
    "FORMAT": "帧格式或 manifest 头无效",
    "TARGET": "目标 ID 不匹配",
    "SEQUENCE": "序列号错误",
    "OFFSET": "偏移不连续（前跳或乱序）",
    "SD_IO": "SD 写入失败",
    "IMAGE_CRC": "镜像 CRC 校验失败",
    "TIMEOUT": "固件 30 秒不活动已中止会话",
    "STATE": "会话状态错误",
}

PHASE_ZH: dict[str, str] = {
    "HANDSHAKE": "握手中",
    "BEGIN": "发送 manifest",
    "DATA": "传输镜像",
    "COMMIT": "校验并提交",
    "STAGED": "已暂存，等待设备重启",
    "CANCELLED": "已取消",
    "WAIT_RESTART": "等待设备重启并重连",
    "RECONNECTED": "设备已重连",
}


def describe_nack(code: str | None) -> str:
    """Return the Chinese meaning of one NACK code, tolerating unknown values."""
    if code is None:
        return "未知错误"
    return NACK_CODE_ZH.get(code, f"未知错误代码 {code}")


def describe_phase(phase: str | None) -> str:
    """Return the Chinese label of one upload phase."""
    if phase is None:
        return "空闲"
    return PHASE_ZH.get(phase, phase)
