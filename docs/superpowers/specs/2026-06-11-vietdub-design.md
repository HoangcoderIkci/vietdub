# vietdub — Design Spec

**Ngày:** 2026-06-11 · **Trạng thái:** Approved (Anh Lan duyệt sau review vòng 2)
**Mục tiêu:** CLI Python lồng tiếng Việt cho video YouTube tiếng Anh — tải video, lấy transcript, dịch, đọc bằng giọng Việt AI, ghép lại thành video nói tiếng Việt.

## 1. Bài toán & phạm vi

Anh Lan muốn xem video YouTube tiếng Anh nhưng **nghe tiếng Việt**. YouTube auto-dubbing chưa hỗ trợ chiều Anh→Việt; extension bên thứ ba là freemium + đưa nội dung qua server ngoài. → Tự build tool offline, free 100%, kiểm soát chất lượng.

**In scope (v1):** video YouTube đơn lẻ (URL) → file `.viet.mp4` xem offline. Giọng nam/nữ chọn được. Resume khi đứt giữa chừng.
**Non-goals (v1):** realtime dubbing khi xem trực tiếp; batch playlist; voice cloning; UI đồ họa; nguồn ngoài YouTube (Facebook/TikTok — kiến trúc không chặn, nhưng không cam kết v1).

## 2. Pipeline

```
URL YouTube
  │ downloader   yt-dlp: video.mp4 + phụ đề (.vtt)
  ▼
  │ transcript   3 tầng fallback:
  │              ① phụ đề VI auto-translated từ YouTube (nhanh nhất, bỏ được stage dịch)
  │              ② phụ đề EN (manual > auto) → cần dịch
  │              ③ faster-whisper transcribe (video không phụ đề) → cần dịch
  ▼              output: list[Segment] — schema segments.jsonl dùng chung với claudeLearn
  │ translator   (chỉ tầng ②③) gom segment thành câu → EN→VI qua deep-translator, retry/backoff
  ▼
  │ tts          edge-tts, giọng vi-VN-HoaiMyNeural (nữ, mặc định) / vi-VN-NamMinhNeural (nam)
  ▼              1 file audio / câu; interface TTS pluggable (backend VieNeu-TTS là stretch goal)
  │ assembler    đặt audio theo timestamp; câu dài hơn slot → atempo tăng tốc ≤1.35×,
  │              vẫn dư → tràn sang khoảng lặng kế tiếp
  ▼
  │ mix (ffmpeg) audio gốc giảm còn 15% + track tiếng Việt đè lên; copy video stream (không re-encode)
  ▼
video.viet.mp4
```

**Lý do quyết định chính:**
- **Tầng ① là phát hiện đã verify** (test thật 2026-06-11): YouTube phục vụ phụ đề auto-translated sang VI qua `yt-dlp --write-auto-subs --sub-langs vi`. Endpoint hay trả 429 → chỉ thử 1 lần có retry ngắn rồi rớt xuống tầng ②. Cần `curl-cffi` (impersonation) + `yt-dlp -U`.
- **Subtitles-first thay vì Whisper-always:** máy không GPU, whisper-small CPU chậm (video 15' ≈ 10-15'); ~90% video EN có phụ đề. Whisper chỉ là tầng ③ — model mặc định `large-v3-turbo` (claudeLearn đã chạy ổn trên chính CPU này), flag đổi được.
- **edge-tts mặc định, không phải TTS local:** cài nhẹ, giọng Việt tốt nhất nhóm free. Rủi ro: endpoint Microsoft không chính thức → interface `TtsEngine` pluggable, VieNeu-TTS (local CPU) là stretch goal Day 4.
- **Mix 15% thay vì thay thế audio:** giữ nhạc nền/không khí; flag `--bg-volume` chỉnh được.
- **Tái dùng claudeLearn:** port (copy + tỉa, có ghi nguồn) code downloader/subtitle-first/whisper từ `D:\codeClaude\claudeLearn\video_to_text.py` — đã có test, đã chạy thật. vietdub vẫn standalone (repo portfolio riêng); interop qua schema `segments.jsonl` chung: `{start, end, text, source, language}` + nhận input `--segments path.jsonl`.

## 3. Module & boundaries

```
vietdub/
  models.py       Segment dataclass {start: float, end: float, text: str, source: str, language: str}
  downloader.py   yt-dlp wrapper: tải video + subs; trả (video_path, subs_path|None, sub_lang|None)
  transcript.py   parse VTT → list[Segment]; whisper fallback; logic chọn tầng ①②③
  translator.py   interface Translator + GoogleFreeTranslator (deep-translator); batch câu, retry/backoff
  tts.py          interface TtsEngine + EdgeTts (async, 1 call/câu, cache file theo hash text+voice)
  assembler.py    timeline placement + atempo + spillover; build dub track; ffmpeg mix + mux
  cli.py          argparse, orchestrate, work dir
tests/            unit test per module (sample VTT, mock mạng), 1 integration test video ngắn thật
```

Mỗi module: một việc, test độc lập, không import chéo (chỉ qua `models.py`).

**CLI:**
```
vietdub <url> [--voice nu|nam] [-o OUT.mp4] [--bg-volume 0.15] [--whisper-model large-v3-turbo]
              [--segments path.jsonl] [--workdir DIR] [--force]
```

## 4. Caching / resume / error handling

- Work dir `.vietdub/<video_id>/`: mỗi stage ghi output ra đĩa (`video.mp4`, `segments.jsonl`, `segments.vi.jsonl`, `tts/<hash>.mp3`, `dub_track.m4a`). Chạy lại → stage nào có output thì skip (trừ `--force`).
- Lý do: translate/TTS là hàng trăm network call với video dài; đứt giữa chừng không được mất công đoạn đã xong (bài học từ lỗi SSL/429 gặp thật hôm nay).
- Network call (yt-dlp, translate, tts): retry với exponential backoff, lỗi rõ ràng kèm gợi ý khắc phục (429 → đợi/giảm tốc; extract fail → `yt-dlp -U`).
- Validate input ở boundary: URL hợp lệ, ffmpeg/yt-dlp có trên PATH (fail sớm, message rõ).

## 5. Môi trường & dependency

- Python 3.12, venv riêng tại `D:\codeClaude\vietdub\.venv`, pin trong `requirements.txt`.
- Mới: `edge-tts`, `deep-translator`, `curl-cffi`, `pytest` (dev). Có sẵn trên máy: yt-dlp (chạy `yt-dlp -U` ở setup), ffmpeg, faster-whisper 1.2.1.
- Không GPU → mọi lựa chọn mặc định phải chạy tốt trên CPU.

## 6. Testing

- Unit: VTT parser (fixture file), assembler timing (case: vừa khít / dài hơn slot / dài quá phải tràn), translator batching (mock), tts cache key.
- Integration: 1 video YouTube ngắn (<2') chạy end-to-end → file output tồn tại, có 2 luồng audio mix, duration khớp video gốc ±1s.
- Verify chuẩn: `pytest` pass là điều kiện hoàn thành mỗi task (xem implementation plan).

## 7. Rủi ro đã biết

| Rủi ro | Mitigation |
|---|---|
| Chất lượng = dịch máy + giọng TTS đều | Chấp nhận ở v1 ("nghe hiểu nội dung"); glossary giữ thuật ngữ EN là enhancement sau |
| YouTube 429 ở endpoint phụ đề | curl-cffi + retry + fallback tầng ② |
| edge-tts endpoint không chính thức có thể hỏng | Interface pluggable; VieNeu-TTS local là phương án B |
| deep-translator dev chậm lại / Google chặn | Interface Translator pluggable; tầng ① bỏ hẳn nhu cầu dịch khi available |
| Tiếng Việt dài hơn EN ~10-20% → lệch sync | atempo ≤1.35 + spillover; đây là phần khó nhất, giao model mạnh làm trực tiếp |

## 8. Lộ trình 4 ngày (chi tiết trong implementation plan)

| Ngày | Việc | Milestone kiểm chứng |
|---|---|---|
| 1 | Scaffold + setup + port downloader/transcript + fast-path VI subs | URL thật → segments in ra |
| 2 | translator + tts + tests | Mỗi câu có file audio VI nghe được |
| 3 | assembler + mix | Video đầu tiên nói tiếng Việt end-to-end |
| 4 | Resume polish + CLI + README/demo + (stretch) VieNeu-TTS | Portfolio-ready, lên GitHub |

Thực thi theo cơ chế **model routing** (xem `docs/superpowers/plans/2026-06-11-vietdub-implementation.md`): Opus/Fable giữ design + assembler + review; Sonnet làm module có spec rõ; Haiku làm việc cơ học; mỗi task có acceptance test; fail 2 lần → escalate model.
