import pytest
from pathlib import Path
from vietdub.downloader import download, DownloadResult

def test_downloadresult_defaults():
    r = DownloadResult(video_path=Path("x.mp4"), video_id="abc", title="t", duration=10.0)
    assert r.subs == {}

@pytest.mark.network
def test_download_real_short_video(tmp_path):
    # video ngắn ổn định, có auto captions
    r = download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)  # "Me at the zoo", 19s
    assert r.video_path.exists()
    assert r.duration > 10
