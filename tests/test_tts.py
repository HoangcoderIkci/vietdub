from pathlib import Path
from vietdub.tts import cache_key, VOICES

def test_voices_map():
    assert VOICES["nu"] == "vi-VN-HoaiMyNeural"
    assert VOICES["nam"] == "vi-VN-NamMinhNeural"

def test_cache_key_stable_and_distinct():
    a = cache_key("Xin chào.", "vi-VN-HoaiMyNeural")
    assert a == cache_key("Xin chào.", "vi-VN-HoaiMyNeural")     # ổn định
    assert a != cache_key("Xin chào.", "vi-VN-NamMinhNeural")     # khác giọng -> khác key
    assert a != cache_key("Xin chào!", "vi-VN-HoaiMyNeural")      # khác text -> khác key
