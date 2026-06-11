# vietdub/assembler.py
"""Đặt clip TTS lên timeline + render dub track + mix với video gốc."""
from __future__ import annotations
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from vietdub.models import Segment

MAX_SPEED = 1.35
SR = 24000  # sample rate dub track

@dataclass
class PlacedClip:
    audio_path: Path
    start: float   # giây trên timeline cuối
    speed: float   # hệ số atempo (1.0 = giữ nguyên)

def plan_timeline(items: list[tuple[Segment, Path, float]], video_dur: float,
                  max_speed: float = MAX_SPEED) -> list[PlacedClip]:
    """items = [(segment, audio_path, audio_duration_giây)] đã sort theo segment.start.

    Quy tắc: clip đặt tại max(seg.start, cursor). Slot = từ điểm đặt tới start clip kế
    (hoặc hết video). Clip dài hơn slot -> tăng tốc tối đa max_speed; vẫn dư -> chấp
    nhận tràn, cursor đẩy clip sau ra muộn (ăn vào khoảng lặng kế tiếp).
    """
    placed: list[PlacedClip] = []
    cursor = 0.0
    for i, (seg, path, dur) in enumerate(items):
        start = max(seg.start, cursor)
        next_start = items[i + 1][0].start if i + 1 < len(items) else video_dur
        slot = max(next_start - start, 0.25)
        speed = round(min(max(dur / slot, 1.0), max_speed), 3)
        placed.append(PlacedClip(path, round(start, 3), speed))
        cursor = start + dur / speed
    return placed
