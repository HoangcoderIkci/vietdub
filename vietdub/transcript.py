# vietdub/transcript.py
"""VTT -> list[Segment]; gộp segment thành câu cho dịch/TTS tự nhiên."""
from __future__ import annotations
import re
from pathlib import Path
from vietdub.models import Segment

_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
_TAG = re.compile(r"<[^>]+>")
_SENT_END = re.compile(r"""[.!?…]['""]?\s*$""")

def _to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

def parse_vtt(path: Path, language: str = "en", source: str = "subs") -> list[Segment]:
    segs: list[Segment] = []
    seen_lines: list[str] = []          # dedupe rolling captions
    cur: tuple[float, float] | None = None
    buf: list[str] = []

    def flush():
        nonlocal buf, cur
        if cur and buf:
            text = " ".join(buf).strip()
            if text:
                segs.append(Segment(cur[0], cur[1], text, source, language))
        buf, cur = [], None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = _TS.search(line)
        if m:
            flush()
            cur = (_to_sec(*m.groups()[:4]), _to_sec(*m.groups()[4:]))
            continue
        if not cur or not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        clean = _TAG.sub("", line).strip()
        if clean and clean not in seen_lines[-4:]:   # cửa sổ dedupe 4 dòng gần nhất
            buf.append(clean)
            seen_lines.append(clean)
    flush()
    return segs

def merge_into_sentences(segs: list[Segment], max_dur: float = 12.0, max_chars: int = 280) -> list[Segment]:
    """Gộp các segment liên tiếp tới khi gặp dấu kết câu, hoặc vượt max_dur/max_chars."""
    merged: list[Segment] = []
    acc: Segment | None = None
    for s in segs:
        if acc is None:
            acc = Segment(s.start, s.end, s.text, s.source, s.language)
        else:
            acc = Segment(acc.start, s.end, f"{acc.text} {s.text}", acc.source, acc.language)
        too_long = (acc.end - acc.start) > max_dur or len(acc.text) > max_chars
        if _SENT_END.search(acc.text) or too_long:
            merged.append(acc)
            acc = None
    if acc:
        merged.append(acc)
    # Tách câu nội bộ kiểu "...parser. New sentence": cắt tại ranh giới câu giữa text
    out: list[Segment] = []
    for m in merged:
        parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ỹ0-9])", m.text)
        if len(parts) == 1:
            out.append(m)
            continue
        dur = m.end - m.start
        total = sum(len(p) for p in parts)
        t = m.start
        for p in parts:
            d = dur * len(p) / total
            out.append(Segment(round(t, 3), round(t + d, 3), p.strip(), m.source, m.language))
            t += d
    return _coalesce_sentence_halves(out, max_dur=max_dur)

def _coalesce_sentence_halves(segs: list[Segment], max_dur: float = 12.0) -> list[Segment]:
    """Sau khi split, nửa câu chưa kết ('New sentence') gộp với phần sau ('starts here.').
    Không gộp nếu kết quả vượt max_dur (tránh undo các cut do too_long)."""
    out: list[Segment] = []
    for s in segs:
        if out and not _SENT_END.search(out[-1].text):
            prev = out[-1]
            merged_dur = s.end - prev.start
            if merged_dur <= max_dur:
                out.pop()
                out.append(Segment(prev.start, s.end, f"{prev.text} {s.text}".strip(), prev.source, prev.language))
            else:
                out.append(s)
        else:
            out.append(s)
    return out

from vietdub.downloader import DownloadResult

def pick_tier(dl: DownloadResult) -> tuple[str, Path | None]:
    if "vi" in dl.subs:
        return "vi-subs", dl.subs["vi"]
    if "en" in dl.subs:
        return "en-subs", dl.subs["en"]
    return "whisper", None

def transcribe_whisper(video_path: Path, model_size: str = "large-v3-turbo") -> list[Segment]:
    """Tầng 3: chỉ chạy khi không có phụ đề. CPU int8 — chậm, in cảnh báo."""
    from faster_whisper import WhisperModel  # import muộn: faster-whisper nặng
    print(f"[vietdub] Không có phụ đề -> Whisper {model_size} trên CPU (sẽ lâu)...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    raw, _info = model.transcribe(str(video_path), language="en", vad_filter=True)
    return [Segment(round(s.start, 3), round(s.end, 3), s.text.strip(), "whisper", "en") for s in raw]

def get_segments(dl: DownloadResult, whisper_model: str = "large-v3-turbo") -> list[Segment]:
    tier, path = pick_tier(dl)
    if tier == "vi-subs":
        return merge_into_sentences(parse_vtt(path, language="vi", source="subs-auto"))
    if tier == "en-subs":
        return merge_into_sentences(parse_vtt(path, language="en", source="subs"))
    return merge_into_sentences(transcribe_whisper(dl.video_path, whisper_model))
