"""TTS qua edge-tts. Cache file theo hash(text+voice) -> resume không tốn call lại."""
from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path
from typing import Protocol
from vietdub.models import Segment

VOICES = {"nu": "vi-VN-HoaiMyNeural", "nam": "vi-VN-NamMinhNeural"}
_CONCURRENCY = 4

class TtsEngine(Protocol):
    async def synth(self, text: str, voice: str, out_path: Path) -> None: ...

class EdgeTts:
    async def synth(self, text: str, voice: str, out_path: Path) -> None:
        import edge_tts  # import muộn
        await edge_tts.Communicate(text, voice).save(str(out_path))

def cache_key(text: str, voice: str) -> str:
    return hashlib.sha256(f"{voice}|{text}".encode("utf-8")).hexdigest()[:24]

def synth_all(segs: list[Segment], voice_key: str, cache_dir: Path,
              engine: TtsEngine | None = None) -> list[tuple[Segment, Path]]:
    """Trả [(segment, đường dẫn mp3)] theo đúng thứ tự segs. Bỏ qua file đã có (resume)."""
    engine = engine or EdgeTts()
    voice = VOICES[voice_key]
    cache_dir.mkdir(parents=True, exist_ok=True)
    pairs = [(s, cache_dir / f"{cache_key(s.text, voice)}.mp3") for s in segs]

    async def run():
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def one(seg: Segment, path: Path):
            if path.exists() and path.stat().st_size > 0:
                return
            async with sem:
                for attempt in range(3):
                    try:
                        await engine.synth(seg.text, voice, path)
                        return
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2 ** attempt)
        await asyncio.gather(*(one(s, p) for s, p in pairs))

    asyncio.run(run())
    return pairs
