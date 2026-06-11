"""EN->VI. Interface pluggable: sau này thay GoogleFreeTranslator bằng LLM nếu cần."""
from __future__ import annotations
import time
from typing import Protocol
from vietdub.models import Segment

class Translator(Protocol):
    def translate_batch(self, texts: list[str]) -> list[str]: ...

class GoogleFreeTranslator:
    BATCH = 25  # số câu / lần gọi

    def __init__(self, max_retries: int = 4, backoff_base: float = 2.0):
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def _translate_once(self, texts: list[str]) -> list[str]:
        from deep_translator import GoogleTranslator  # import muộn
        return GoogleTranslator(source="en", target="vi").translate_batch(texts)

    def translate_batch(self, texts: list[str]) -> list[str]:
        out: list[str] = []
        for i in range(0, len(texts), self.BATCH):
            chunk = texts[i:i + self.BATCH]
            for attempt in range(self.max_retries):
                try:
                    out.extend(self._translate_once(chunk))
                    break
                except Exception:
                    if attempt == self.max_retries - 1:
                        raise
                    time.sleep(self.backoff_base ** attempt)
        return out

def translate_segments(segs: list[Segment], translator: Translator) -> list[Segment]:
    """Dịch các segment EN; segment đã VI (tầng ①) giữ nguyên. Timing không đổi."""
    en_idx = [i for i, s in enumerate(segs) if s.language == "en"]
    translated = translator.translate_batch([segs[i].text for i in en_idx]) if en_idx else []
    out = [Segment(s.start, s.end, s.text, s.source, "vi") for s in segs]
    for i, vi_text in zip(en_idx, translated):
        out[i] = Segment(segs[i].start, segs[i].end, vi_text, segs[i].source, "vi")
    return out
