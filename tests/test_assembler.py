# tests/test_assembler.py
from pathlib import Path
from vietdub.models import Segment
from vietdub.assembler import plan_timeline, PlacedClip

P = Path("dummy.mp3")

def _items(*triples):
    return [(Segment(st, en, "x"), P, dur) for st, en, dur in triples]

def test_clip_fits_slot_no_speedup():
    placed = plan_timeline(_items((0.0, 2.0, 1.8), (3.0, 5.0, 1.5)), video_dur=10.0)
    assert placed[0] == PlacedClip(P, 0.0, 1.0)
    assert placed[1].start == 3.0 and placed[1].speed == 1.0

def test_clip_slightly_long_gets_atempo():
    # slot tới clip sau = 3.0s, clip dài 3.6s -> speed 1.2
    placed = plan_timeline(_items((0.0, 2.0, 3.6), (3.0, 5.0, 1.0)), video_dur=10.0)
    assert placed[0].speed == 1.2
    assert placed[1].start == 3.0          # clip sau không bị đẩy

def test_clip_way_too_long_caps_at_max_and_pushes_next():
    # slot 2.0s, clip 4.0s -> cần 2.0x nhưng cap 1.35 -> eff = 4/1.35 = 2.963s
    placed = plan_timeline(_items((0.0, 2.0, 4.0), (2.0, 4.0, 1.0)), video_dur=10.0)
    assert placed[0].speed == 1.35
    assert placed[1].start > 2.0           # clip sau bị đẩy ra sau (tràn vào khoảng lặng)
    assert abs(placed[1].start - 4.0 / 1.35) < 0.01

def test_never_places_before_cursor():
    placed = plan_timeline(_items((0.0, 2.0, 5.0), (2.0, 4.0, 1.0), (8.0, 9.0, 0.5)), video_dur=10.0)
    starts = [p.start for p in placed]
    assert starts == sorted(starts)
    assert placed[2].start == 8.0          # khoảng lặng dài -> clip 3 về đúng vị trí gốc

import subprocess, wave
from vietdub.assembler import prepare_clip, render_dub_track, probe_duration, SR

def _sine_mp3(path, dur=1.0):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"sine=frequency=440:duration={dur}", str(path)], check=True)

def test_render_dub_track_lengths(tmp_path):
    mp3 = tmp_path / "a.mp3"; _sine_mp3(mp3, 1.0)
    wav = tmp_path / "a.wav"; prepare_clip(mp3, 1.0, wav)
    out = tmp_path / "dub.wav"
    render_dub_track([PlacedClip(mp3, 2.0, 1.0)], [wav], total_dur=5.0, out_wav=out)
    with wave.open(str(out)) as r:
        dur = r.getnframes() / r.getframerate()
    assert abs(dur - 5.0) < 0.05            # track đúng độ dài video
    # 2 giây đầu phải là im lặng
    with wave.open(str(out)) as r:
        head = r.readframes(int(1.9 * SR))
    assert head == b"\x00\x00" * (len(head) // 2)

def test_prepare_clip_atempo_shortens(tmp_path):
    mp3 = tmp_path / "a.mp3"; _sine_mp3(mp3, 2.0)
    fast = tmp_path / "fast.wav"; prepare_clip(mp3, 1.35, fast)
    assert abs(probe_duration(fast) - 2.0 / 1.35) < 0.1
