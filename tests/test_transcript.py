from pathlib import Path
from vietdub.models import Segment
from vietdub.transcript import parse_vtt, merge_into_sentences

FIXTURE = Path(__file__).parent / "fixtures" / "sample.vtt"

def test_parse_vtt_dedupes_rolling_captions():
    segs = parse_vtt(FIXTURE, language="en")
    texts = [s.text for s in segs]
    assert texts == ["Hello world", "this is a test", "of the parser. New sentence", "starts here."]
    assert segs[0].start == 0.0 and segs[0].end == 2.0
    assert all(s.language == "en" for s in segs)

def test_merge_into_sentences_joins_until_punctuation():
    segs = [
        Segment(0.0, 2.0, "Hello world"),
        Segment(2.0, 4.0, "this is a test"),
        Segment(4.0, 6.5, "of the parser. New sentence"),
        Segment(6.5, 8.0, "starts here."),
    ]
    merged = merge_into_sentences(segs)
    # "Hello world this is a test of the parser." + "New sentence starts here."
    assert len(merged) == 2
    assert merged[0].text == "Hello world this is a test of the parser."
    assert merged[0].start == 0.0
    assert merged[1].text == "New sentence starts here."
    assert merged[1].end == 8.0

def test_merge_respects_max_duration():
    segs = [Segment(float(i * 5), float(i * 5 + 5), f"chunk {i}") for i in range(10)]  # không có dấu câu
    merged = merge_into_sentences(segs, max_dur=12.0)
    assert all(m.end - m.start <= 12.0 + 5.0 for m in merged)  # cắt khi vượt ngưỡng
    assert len(merged) > 1
