"""Tải video + phụ đề. Phụ đề vi (auto-translated) hay 429 -> bắt lỗi riêng từng ngôn ngữ."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yt_dlp

@dataclass
class DownloadResult:
    video_path: Path
    video_id: str
    title: str
    duration: float
    subs: dict[str, Path] = field(default_factory=dict)  # {"vi": ..., "en": ...}

def video_id_of(url: str) -> str:
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        return ydl.extract_info(url, download=False)["id"]

def download(url: str, workdir: Path) -> DownloadResult:
    workdir.mkdir(parents=True, exist_ok=True)
    base = {"quiet": True, "noprogress": True, "retries": 5, "socket_timeout": 60}

    # 1) video (không kèm subs để lỗi subs không phá download chính)
    video_opts = base | {
        "outtmpl": str(workdir / "video.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(video_opts) as ydl:
        info = ydl.extract_info(url, download=not (workdir / "video.mp4").exists())
    result = DownloadResult(
        video_path=workdir / "video.mp4",
        video_id=info["id"], title=info.get("title", ""),
        duration=float(info.get("duration") or 0),
    )

    # 2) phụ đề: thử từng ngôn ngữ độc lập, lỗi (429...) thì bỏ qua
    for lang in ("vi", "en"):
        target = workdir / f"subs.{lang}.vtt"
        if target.exists():
            result.subs[lang] = target
            continue
        sub_opts = base | {
            "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": [lang], "subtitlesformat": "vtt",
            "outtmpl": str(workdir / "subs.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(sub_opts) as ydl:
                ydl.extract_info(url, download=True)
            got = next(workdir.glob(f"subs.{lang}*.vtt"), None)
            if got:
                got = got.rename(target) if got != target else got
                result.subs[lang] = target
        except yt_dlp.utils.DownloadError:
            pass  # 429/không có phụ đề ngôn ngữ này -> tầng sau lo
    return result
