"""Kiểu dữ liệu dùng chung. Schema segments.jsonl tương thích claudeLearn."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class Segment:
    start: float          # giây
    end: float            # giây
    text: str
    source: str = "subs"  # subs | subs-auto | whisper
    language: str = "en"  # en | vi

def save_segments(segments: list[Segment], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in segments:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")

def load_segments(path: Path) -> list[Segment]:
    out: list[Segment] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(Segment(**json.loads(line)))
    return out
