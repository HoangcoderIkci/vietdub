import json
from pathlib import Path
from vietdub.models import Segment, load_segments, save_segments

def test_segment_roundtrip(tmp_path: Path):
    segs = [
        Segment(start=0.0, end=2.5, text="Hello world", source="subs", language="en"),
        Segment(start=2.5, end=5.0, text="Xin chào", source="subs-auto", language="vi"),
    ]
    p = tmp_path / "segments.jsonl"
    save_segments(segs, p)
    loaded = load_segments(p)
    assert loaded == segs
    # schema tương thích claudeLearn: mỗi dòng là JSON object có đủ 5 key
    first = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert set(first) == {"start", "end", "text", "source", "language"}
