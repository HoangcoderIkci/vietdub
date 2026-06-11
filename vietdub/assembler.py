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

def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())

def prepare_clip(mp3: Path, speed: float, out_wav: Path) -> None:
    """mp3 -> wav s16le mono 24k, áp atempo nếu cần. Cache: bỏ qua nếu out_wav đã có."""
    if out_wav.exists():
        return
    af = ["-af", f"atempo={speed}"] if speed > 1.0 else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), *af,
                    "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)], check=True)

def render_dub_track(placed: list[PlacedClip], clip_wavs: list[Path],
                     total_dur: float, out_wav: Path) -> None:
    """Ghép tuần tự: silence-gap + clip + ... (clip không chồng nhau nhờ cursor)."""
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        cursor_frames = 0
        for p, cw in zip(placed, clip_wavs):
            start_frames = int(p.start * SR)
            if start_frames > cursor_frames:
                w.writeframes(b"\x00\x00" * (start_frames - cursor_frames))
                cursor_frames = start_frames
            with wave.open(str(cw), "rb") as r:
                assert r.getframerate() == SR and r.getnchannels() == 1
                frames = r.readframes(r.getnframes())
            w.writeframes(frames)
            cursor_frames += len(frames) // 2
        total_frames = int(total_dur * SR)
        if total_frames > cursor_frames:
            w.writeframes(b"\x00\x00" * (total_frames - cursor_frames))

def mix_into_video(video: Path, dub_wav: Path, out_mp4: Path, bg_volume: float = 0.15) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(dub_wav),
         "-filter_complex",
         f"[0:a]volume={bg_volume}[bg];[bg][1:a]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         str(out_mp4)], check=True)
