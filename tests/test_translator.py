from unittest.mock import patch
from vietdub.models import Segment
from vietdub.translator import GoogleFreeTranslator, translate_segments

def test_translate_segments_skips_vi_and_maps_en():
    segs = [
        Segment(0, 2, "Hello.", language="en"),
        Segment(2, 4, "Đã là tiếng Việt.", language="vi"),
    ]
    with patch.object(GoogleFreeTranslator, "translate_batch", return_value=["Xin chào."]) as mb:
        out = translate_segments(segs, GoogleFreeTranslator())
    assert [s.text for s in out] == ["Xin chào.", "Đã là tiếng Việt."]
    assert all(s.language == "vi" for s in out)
    assert out[0].start == 0 and out[0].end == 2          # giữ nguyên timing
    mb.assert_called_once_with(["Hello."])

def test_retry_then_succeed():
    t = GoogleFreeTranslator(max_retries=3, backoff_base=0)
    calls = {"n": 0}
    def flaky(texts):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return ["ok"]
    with patch.object(t, "_translate_once", side_effect=flaky):
        assert t.translate_batch(["x"]) == ["ok"]
    assert calls["n"] == 3
