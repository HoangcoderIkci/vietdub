"""Orchestration: mỗi stage ghi output vào workdir; có sẵn -> skip (resume)."""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path
from vietdub.models import Segment, load_segments, save_segments

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vietdub", description="Lồng tiếng Việt cho video YouTube tiếng Anh.")
    p.add_argument("url", help="URL YouTube (hoặc bất kỳ nếu dùng --segments)")
    p.add_argument("--voice", choices=["nu", "nam"], default="nu")
    p.add_argument("-o", "--output", default=None, help="File mp4 đầu ra (mặc định <title>.viet.mp4)")
    p.add_argument("--bg-volume", type=float, default=0.15, help="Âm lượng audio gốc giữ lại")
    p.add_argument("--whisper-model", default="large-v3-turbo")
    p.add_argument("--segments", default=None, help="Dùng segments.jsonl có sẵn (interop claudeLearn)")
    p.add_argument("--workdir", default=None, help="Mặc định .vietdub/<video_id>/")
    p.add_argument("--force", action="store_true", help="Bỏ cache, chạy lại mọi stage")
    return p

def _check_binaries() -> None:
    for b in ("ffmpeg", "ffprobe"):
        if not shutil.which(b):
            sys.exit(f"[vietdub] Thiếu {b} trên PATH — cài ffmpeg trước.")

def run_pipeline(url: str, voice: str = "nu", workdir: Path | None = None,
                 out_path: Path | None = None, bg_volume: float = 0.15,
                 whisper_model: str = "large-v3-turbo",
                 segments_file: Path | None = None, force: bool = False) -> Path:
    from vietdub.downloader import download, video_id_of
    from vietdub.transcript import get_segments
    from vietdub.translator import GoogleFreeTranslator, translate_segments
    from vietdub.tts import synth_all
    from vietdub.assembler import (plan_timeline, prepare_clip, probe_duration,
                                   render_dub_track, mix_into_video)
    _check_binaries()
    workdir = workdir or Path(".vietdub") / video_id_of(url)
    workdir.mkdir(parents=True, exist_ok=True)
    if force:
        for f in workdir.glob("segments*.jsonl"):
            f.unlink()

    print("[1/5] Tải video + phụ đề...")
    dl = download(url, workdir)

    seg_file = workdir / "segments.jsonl"
    if segments_file:
        segs = load_segments(Path(segments_file))
    elif seg_file.exists():
        segs = load_segments(seg_file)
    else:
        print("[2/5] Lấy transcript...")
        segs = get_segments(dl, whisper_model)
        save_segments(segs, seg_file)

    vi_file = workdir / "segments.vi.jsonl"
    if vi_file.exists():
        vi_segs = load_segments(vi_file)
    else:
        print("[3/5] Dịch sang tiếng Việt...")
        vi_segs = translate_segments(segs, GoogleFreeTranslator())
        save_segments(vi_segs, vi_file)

    print(f"[4/5] TTS {len(vi_segs)} câu (giọng {voice})...")
    pairs = synth_all(vi_segs, voice, workdir / "tts")

    print("[5/5] Ghép audio + mix...")
    items = [(s, p, probe_duration(p)) for s, p in pairs]
    placed = plan_timeline(items, dl.duration)
    clip_wavs = []
    for pc in placed:
        cw = pc.audio_path.with_suffix(f".x{pc.speed}.wav")
        prepare_clip(pc.audio_path, pc.speed, cw)
        clip_wavs.append(cw)
    dub = workdir / "dub.wav"
    render_dub_track(placed, clip_wavs, dl.duration, dub)
    out = Path(out_path) if out_path else Path(f"{dl.title[:60] or dl.video_id}.viet.mp4")
    mix_into_video(dl.video_path, dub, out, bg_volume)
    print(f"✅ Xong: {out}")
    return out

def main() -> None:
    a = build_parser().parse_args()
    run_pipeline(a.url, voice=a.voice,
                 workdir=Path(a.workdir) if a.workdir else None,
                 out_path=Path(a.output) if a.output else None,
                 bg_volume=a.bg_volume, whisper_model=a.whisper_model,
                 segments_file=Path(a.segments) if a.segments else None,
                 force=a.force)
