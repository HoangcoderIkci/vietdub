# tests/test_integration.py
import pytest
from pathlib import Path

@pytest.mark.slow
@pytest.mark.network
def test_end_to_end_short_video(tmp_path):
    from vietdub.cli import run_pipeline  # Task 10 cung cấp; trước đó test này skip
    out = run_pipeline("https://www.youtube.com/watch?v=jNQXAC9IVRw",
                       voice="nu", workdir=tmp_path, out_path=tmp_path / "out.viet.mp4")
    from vietdub.assembler import probe_duration
    assert out.exists()
    assert abs(probe_duration(out) - 19.0) < 2.0
