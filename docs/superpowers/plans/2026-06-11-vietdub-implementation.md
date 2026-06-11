# vietdub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI Python lồng tiếng Việt cho video YouTube tiếng Anh → file `.viet.mp4` offline.

**Architecture:** Pipeline 6 stage (download → transcript 3-tầng fallback → translate → TTS → assemble → mix), mỗi stage cache output vào `.vietdub/<video_id>/` để resume. Spec: `docs/superpowers/specs/2026-06-11-vietdub-design.md`.

**Tech Stack:** Python 3.12, yt-dlp, ffmpeg, edge-tts, deep-translator, faster-whisper (fallback), pytest.

**Model routing (quy tắc chung cho mọi task):**

| Cột | Ý nghĩa |
|---|---|
| **Model** | haiku = cơ học · sonnet = spec rõ, độ khó trung bình · opus/fable = logic khó, làm trong main session |
| **Acceptance** | Lệnh pytest/smoke phải pass thì task mới được tính xong |
| **Escalation** | Subagent fail acceptance 2 lần → đẩy lên model mạnh hơn một bậc, kèm log lỗi 2 lần thử |

Dispatch qua Agent tool với tham số `model`. Orchestrator (main session) chỉ đọc diff + kết quả test, không đọc lại toàn bộ code.

---

## NGÀY 1 — Skeleton + lấy được transcript

### Task 1: Scaffold project — **Model: haiku**

**Files:** Create `.gitignore`, `requirements.in`, `pytest.ini`, `vietdub/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Tạo venv + cài deps**

```powershell
cd D:\codeClaude\vietdub
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install edge-tts deep-translator curl-cffi yt-dlp pytest pytest-asyncio
.\.venv\Scripts\pip freeze > requirements.txt
yt-dlp -U
```

(`requirements.txt` sinh từ pip freeze — KHÔNG tự bịa số version.)

- [ ] **Step 2: Tạo file cấu trúc**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.vietdub/
.pytest_cache/
```

`requirements.in` (ghi deps gốc, để người đọc hiểu):
```
edge-tts
deep-translator
curl-cffi
yt-dlp
pytest
pytest-asyncio
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
markers =
    network: cần mạng thật (chạy tay, CI skip)
    slow: chạy lâu (whisper, integration)
addopts = -m "not network and not slow"
```

`vietdub/__init__.py` và `tests/__init__.py`: file rỗng.

- [ ] **Step 3: Verify** — Run: `.\.venv\Scripts\python -c "import edge_tts, deep_translator, yt_dlp; print('ok')"` → Expected: `ok`. Run: `.\.venv\Scripts\pytest` → Expected: `no tests ran`.

- [ ] **Step 4: Commit** — `git add -A; git commit -m "chore: scaffold project, venv, pinned deps"`

**Acceptance:** 2 lệnh ở Step 3 pass. **Escalation:** → sonnet.

---

### Task 2: `models.py` — Segment + JSONL I/O — **Model: sonnet**

**Files:** Create `vietdub/models.py`, `tests/test_models.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: Run** `.\.venv\Scripts\pytest tests/test_models.py -v` → Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement**

```python
# vietdub/models.py
"""Kiểu dữ liệu dùng chung. Schema segments.jsonl tương thích claudeLearn."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class Segment:
    start: float          # giây
    end: float            # giây
    text: str
    source: str = "subs"  # subs | subs-auto | whisper
    language: str = "en"  # en | vi

def save_segments(segments: list[Segment], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in segments:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")

def load_segments(path: Path) -> list[Segment]:
    out: list[Segment] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(Segment(**json.loads(line)))
    return out
```

- [ ] **Step 4: Run lại test** → Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A; git commit -m "feat: Segment model + jsonl io (schema chung voi claudeLearn)"`

**Acceptance:** `pytest tests/test_models.py` pass. **Escalation:** → opus.

---

### Task 3: `transcript.py` — parse VTT + dedupe + gộp câu — **Model: sonnet**

**Files:** Create `vietdub/transcript.py`, `tests/test_transcript.py`, `tests/fixtures/sample.vtt`

Bối cảnh cho người không biết domain: phụ đề auto của YouTube là VTT **rolling captions** — cue sau lặp lại dòng của cue trước rồi thêm dòng mới → bắt buộc dedupe. Tag inline kiểu `<00:00:01.500><c>word</c>` phải strip.

- [ ] **Step 1: Tạo fixture**

```
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
Hello world

00:00:02.000 --> 00:00:04.000
Hello world
this is a test

00:00:04.000 --> 00:00:06.500
this is a test
of the <c>parser</c>. New sentence

00:00:06.500 --> 00:00:08.000
starts here.
```

(Lưu thành `tests/fixtures/sample.vtt`, đúng nguyên văn.)

- [ ] **Step 2: Failing tests**

```python
# tests/test_transcript.py
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
```

- [ ] **Step 3: Run** → Expected: FAIL.

- [ ] **Step 4: Implement**

```python
# vietdub/transcript.py
"""VTT -> list[Segment]; gộp segment thành câu cho dịch/TTS tự nhiên."""
from __future__ import annotations
import re
from pathlib import Path
from vietdub.models import Segment

_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
_TAG = re.compile(r"<[^>]+>")
_SENT_END = re.compile(r"[.!?…]['\"”)]?\s*$")

def _to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

def parse_vtt(path: Path, language: str = "en", source: str = "subs") -> list[Segment]:
    segs: list[Segment] = []
    seen_lines: list[str] = []          # dedupe rolling captions
    cur: tuple[float, float] | None = None
    buf: list[str] = []

    def flush():
        nonlocal buf, cur
        if cur and buf:
            text = " ".join(buf).strip()
            if text:
                segs.append(Segment(cur[0], cur[1], text, source, language))
        buf, cur = [], None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = _TS.search(line)
        if m:
            flush()
            cur = (_to_sec(*m.groups()[:4]), _to_sec(*m.groups()[4:]))
            continue
        if not cur or not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        clean = _TAG.sub("", line).strip()
        if clean and clean not in seen_lines[-4:]:   # cửa sổ dedupe 4 dòng gần nhất
            buf.append(clean)
            seen_lines.append(clean)
    flush()
    return segs

def merge_into_sentences(segs: list[Segment], max_dur: float = 12.0, max_chars: int = 280) -> list[Segment]:
    """Gộp các segment liên tiếp tới khi gặp dấu kết câu, hoặc vượt max_dur/max_chars."""
    merged: list[Segment] = []
    acc: Segment | None = None
    for s in segs:
        if acc is None:
            acc = Segment(s.start, s.end, s.text, s.source, s.language)
        else:
            acc = Segment(acc.start, s.end, f"{acc.text} {s.text}", acc.source, acc.language)
        too_long = (acc.end - acc.start) > max_dur or len(acc.text) > max_chars
        if _SENT_END.search(acc.text) or too_long:
            merged.append(acc)
            acc = None
    if acc:
        merged.append(acc)
    # Tách câu nội bộ kiểu "...parser. New sentence": cắt tại ranh giới câu giữa text
    out: list[Segment] = []
    for m in merged:
        parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ỹ0-9])", m.text)
        if len(parts) == 1:
            out.append(m)
            continue
        dur = m.end - m.start
        total = sum(len(p) for p in parts)
        t = m.start
        for p in parts:
            d = dur * len(p) / total
            out.append(Segment(round(t, 3), round(t + d, 3), p.strip(), m.source, m.language))
            t += d
    return _coalesce_sentence_halves(out)

def _coalesce_sentence_halves(segs: list[Segment]) -> list[Segment]:
    """Sau khi split, nửa câu chưa kết ('New sentence') gộp với phần sau ('starts here.')."""
    out: list[Segment] = []
    for s in segs:
        if out and not _SENT_END.search(out[-1].text):
            prev = out.pop()
            out.append(Segment(prev.start, s.end, f"{prev.text} {s.text}".strip(), prev.source, prev.language))
        else:
            out.append(s)
    return out
```

- [ ] **Step 5: Run** → Expected: 3 test PASS. Nếu logic split/coalesce trượt fixture, sửa tới khi pass — KHÔNG sửa test.
- [ ] **Step 6: Commit** — `git commit -am "feat: VTT parser voi dedupe rolling captions + sentence merge"`

**Acceptance:** `pytest tests/test_transcript.py` pass. **Escalation:** → opus (logic dedupe/merge là chỗ dễ trượt nhất Ngày 1).

---

### Task 4: `downloader.py` — yt-dlp wrapper — **Model: sonnet**

**Files:** Create `vietdub/downloader.py`, `tests/test_downloader.py`

- [ ] **Step 1: Implement** (test unit trước phần thuần logic, network để smoke)

```python
# vietdub/downloader.py
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
```

- [ ] **Step 2: Unit test phần không-mạng + smoke network**

```python
# tests/test_downloader.py
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
```

- [ ] **Step 3: Run** `pytest tests/test_downloader.py -v` (non-network) → PASS. Smoke tay: `pytest -m network tests/test_downloader.py -v` → PASS (cần mạng; nếu 429 phụ đề thì vẫn pass vì subs optional).
- [ ] **Step 4: Commit** — `git commit -am "feat: downloader voi per-language subtitle tolerance"`

**Acceptance:** non-network pass + smoke network pass ít nhất 1 lần. **Escalation:** → opus.

---

### Task 5: `transcript.get_segments` — logic 3 tầng + whisper fallback — **Model: sonnet**

**Files:** Modify `vietdub/transcript.py` (thêm cuối file), `tests/test_transcript.py` (thêm test)

- [ ] **Step 1: Failing test**

```python
# thêm vào tests/test_transcript.py
from vietdub.downloader import DownloadResult
from vietdub.transcript import pick_tier

def test_pick_tier_prefers_vi_then_en_then_whisper(tmp_path):
    vi = tmp_path / "subs.vi.vtt"; vi.write_text("WEBVTT\n", encoding="utf-8")
    en = tmp_path / "subs.en.vtt"; en.write_text("WEBVTT\n", encoding="utf-8")
    base = dict(video_path=tmp_path / "v.mp4", video_id="x", title="", duration=1.0)
    assert pick_tier(DownloadResult(**base, subs={"vi": vi, "en": en})) == ("vi-subs", vi)
    assert pick_tier(DownloadResult(**base, subs={"en": en})) == ("en-subs", en)
    assert pick_tier(DownloadResult(**base, subs={})) == ("whisper", None)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
# thêm vào vietdub/transcript.py
from vietdub.downloader import DownloadResult

def pick_tier(dl: DownloadResult) -> tuple[str, Path | None]:
    if "vi" in dl.subs:
        return "vi-subs", dl.subs["vi"]
    if "en" in dl.subs:
        return "en-subs", dl.subs["en"]
    return "whisper", None

def transcribe_whisper(video_path: Path, model_size: str = "large-v3-turbo") -> list[Segment]:
    """Tầng 3: chỉ chạy khi không có phụ đề. CPU int8 — chậm, in cảnh báo."""
    from faster_whisper import WhisperModel  # import muộn: faster-whisper nặng
    print(f"[vietdub] Không có phụ đề -> Whisper {model_size} trên CPU (sẽ lâu)...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    raw, _info = model.transcribe(str(video_path), language="en", vad_filter=True)
    return [Segment(round(s.start, 3), round(s.end, 3), s.text.strip(), "whisper", "en") for s in raw]

def get_segments(dl: DownloadResult, whisper_model: str = "large-v3-turbo") -> list[Segment]:
    tier, path = pick_tier(dl)
    if tier == "vi-subs":
        return merge_into_sentences(parse_vtt(path, language="vi", source="subs-auto"))
    if tier == "en-subs":
        return merge_into_sentences(parse_vtt(path, language="en", source="subs"))
    return merge_into_sentences(transcribe_whisper(dl.video_path, whisper_model))
```

- [ ] **Step 4: Run** `pytest tests/test_transcript.py -v` → PASS (whisper không chạy trong unit test).
- [ ] **Step 5: Milestone Ngày 1 (smoke tay):**

```powershell
.\.venv\Scripts\python -c "from pathlib import Path; from vietdub.downloader import download; from vietdub.transcript import get_segments; dl = download('https://www.youtube.com/watch?v=jNQXAC9IVRw', Path('.vietdub/smoke')); [print(f'[{s.start:6.1f}] ({s.language}) {s.text}') for s in get_segments(dl)[:10]]"
```
Expected: in ra các câu kèm timestamp (vi nếu tầng ① ăn, en nếu rớt tầng ②).

- [ ] **Step 6: Commit** — `git commit -am "feat: 3-tier transcript acquisition (vi-subs > en-subs > whisper)"`

**Acceptance:** pytest pass + smoke Step 5 in ra segments. **Escalation:** → opus.

---

## NGÀY 2 — Dịch + TTS

### Task 6: `translator.py` — **Model: sonnet**

**Files:** Create `vietdub/translator.py`, `tests/test_translator.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_translator.py
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
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
# vietdub/translator.py
"""EN->VI. Interface pluggable: sau này thay GoogleFreeTranslator bằng LLM nếu cần."""
from __future__ import annotations
import time
from typing import Protocol
from vietdub.models import Segment

class Translator(Protocol):
    def translate_batch(self, texts: list[str]) -> list[str]: ...

class GoogleFreeTranslator:
    BATCH = 25  # số câu / lần gọi

    def __init__(self, max_retries: int = 4, backoff_base: float = 2.0):
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def _translate_once(self, texts: list[str]) -> list[str]:
        from deep_translator import GoogleTranslator  # import muộn
        return GoogleTranslator(source="en", target="vi").translate_batch(texts)

    def translate_batch(self, texts: list[str]) -> list[str]:
        out: list[str] = []
        for i in range(0, len(texts), self.BATCH):
            chunk = texts[i:i + self.BATCH]
            for attempt in range(self.max_retries):
                try:
                    out.extend(self._translate_once(chunk))
                    break
                except Exception:
                    if attempt == self.max_retries - 1:
                        raise
                    time.sleep(self.backoff_base ** attempt)
        return out

def translate_segments(segs: list[Segment], translator: Translator) -> list[Segment]:
    """Dịch các segment EN; segment đã VI (tầng ①) giữ nguyên. Timing không đổi."""
    en_idx = [i for i, s in enumerate(segs) if s.language == "en"]
    translated = translator.translate_batch([segs[i].text for i in en_idx]) if en_idx else []
    out = [Segment(s.start, s.end, s.text, s.source, "vi") for s in segs]
    for i, vi_text in zip(en_idx, translated):
        out[i] = Segment(segs[i].start, segs[i].end, vi_text, segs[i].source, "vi")
    return out
```

- [ ] **Step 4: Run** → PASS. **Step 5: Smoke network (tay):** `.\.venv\Scripts\python -c "from vietdub.translator import GoogleFreeTranslator; print(GoogleFreeTranslator().translate_batch(['Hello, how are you?']))"` → Expected: câu tiếng Việt.
- [ ] **Step 6: Commit** — `git commit -am "feat: translator voi batching + retry/backoff, skip segment da vi"`

**Acceptance:** pytest pass + smoke ra tiếng Việt. **Escalation:** → opus.

---

### Task 7: `tts.py` — edge-tts + cache — **Model: sonnet**

**Files:** Create `vietdub/tts.py`, `tests/test_tts.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_tts.py
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
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
# vietdub/tts.py
"""TTS qua edge-tts. Cache file theo hash(text+voice) -> resume không tốn call lại."""
from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path
from typing import Protocol
from vietdub.models import Segment

VOICES = {"nu": "vi-VN-HoaiMyNeural", "nam": "vi-VN-NamMinhNeural"}
_CONCURRENCY = 4

class TtsEngine(Protocol):
    async def synth(self, text: str, voice: str, out_path: Path) -> None: ...

class EdgeTts:
    async def synth(self, text: str, voice: str, out_path: Path) -> None:
        import edge_tts  # import muộn
        await edge_tts.Communicate(text, voice).save(str(out_path))

def cache_key(text: str, voice: str) -> str:
    return hashlib.sha256(f"{voice}|{text}".encode("utf-8")).hexdigest()[:24]

def synth_all(segs: list[Segment], voice_key: str, cache_dir: Path,
              engine: TtsEngine | None = None) -> list[tuple[Segment, Path]]:
    """Trả [(segment, đường dẫn mp3)] theo đúng thứ tự segs. Bỏ qua file đã có (resume)."""
    engine = engine or EdgeTts()
    voice = VOICES[voice_key]
    cache_dir.mkdir(parents=True, exist_ok=True)
    pairs = [(s, cache_dir / f"{cache_key(s.text, voice)}.mp3") for s in segs]

    async def run():
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def one(seg: Segment, path: Path):
            if path.exists() and path.stat().st_size > 0:
                return
            async with sem:
                for attempt in range(3):
                    try:
                        await engine.synth(seg.text, voice, path)
                        return
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2 ** attempt)
        await asyncio.gather(*(one(s, p) for s, p in pairs))

    asyncio.run(run())
    return pairs
```

- [ ] **Step 4: Run** → PASS. **Step 5: Smoke network (tay):**

```powershell
.\.venv\Scripts\python -c "from pathlib import Path; from vietdub.models import Segment; from vietdub.tts import synth_all; pairs = synth_all([Segment(0, 2, 'Xin chào, đây là vietdub.')], 'nu', Path('.vietdub/tts-smoke')); print(pairs[0][1], pairs[0][1].stat().st_size, 'bytes')"
```
Expected: file mp3 > 5KB. Mở nghe thử bằng tai.

- [ ] **Step 6: Commit** — `git commit -am "feat: edge-tts engine voi hash cache + concurrency + retry"`

**Acceptance:** pytest pass + mp3 smoke nghe được tiếng Việt. **Escalation:** → opus.

---

## NGÀY 3 — Assembler (phần khó nhất) — **Model: opus/fable, làm TRỰC TIẾP trong main session, KHÔNG dispatch**

### Task 8: `assembler.plan_timeline` — logic đặt clip thuần (pure function)

**Files:** Create `vietdub/assembler.py`, `tests/test_assembler.py`

- [ ] **Step 1: Failing tests — 3 case timing cốt lõi**

```python
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
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
# vietdub/assembler.py
"""Đặt clip TTS lên timeline + render dub track + mix với video gốc."""
from __future__ import annotations
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from vietdub.models import Segment

MAX_SPEED = 1.35
SR = 24000  # sample rate dub track

@dataclass
class PlacedClip:
    audio_path: Path
    start: float   # giây trên timeline cuối
    speed: float   # hệ số atempo (1.0 = giữ nguyên)

def plan_timeline(items: list[tuple[Segment, Path, float]], video_dur: float,
                  max_speed: float = MAX_SPEED) -> list[PlacedClip]:
    """items = [(segment, audio_path, audio_duration_giây)] đã sort theo segment.start.

    Quy tắc: clip đặt tại max(seg.start, cursor). Slot = từ điểm đặt tới start clip kế
    (hoặc hết video). Clip dài hơn slot -> tăng tốc tối đa max_speed; vẫn dư -> chấp
    nhận tràn, cursor đẩy clip sau ra muộn (ăn vào khoảng lặng kế tiếp).
    """
    placed: list[PlacedClip] = []
    cursor = 0.0
    for i, (seg, path, dur) in enumerate(items):
        start = max(seg.start, cursor)
        next_start = items[i + 1][0].start if i + 1 < len(items) else video_dur
        slot = max(next_start - start, 0.25)
        speed = round(min(max(dur / slot, 1.0), max_speed), 3)
        placed.append(PlacedClip(path, round(start, 3), speed))
        cursor = start + dur / speed
    return placed
```

- [ ] **Step 4: Run** `pytest tests/test_assembler.py -v` → 4 PASS. Đây là acceptance cứng — speed 1.2 phải ra đúng 1.2, không xấp xỉ lung tung.
- [ ] **Step 5: Commit** — `git commit -am "feat: plan_timeline - dat clip, atempo cap 1.35, spillover"`

---

### Task 9: Render dub track + mix ffmpeg + integration e2e — **Model: opus/fable (tiếp)**

**Files:** Modify `vietdub/assembler.py` (thêm cuối file), `tests/test_assembler.py` (thêm), `tests/test_integration.py`

- [ ] **Step 1: Thêm render + mix**

```python
# thêm vào vietdub/assembler.py

def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())

def prepare_clip(mp3: Path, speed: float, out_wav: Path) -> None:
    """mp3 -> wav s16le mono 24k, áp atempo nếu cần. Cache: bỏ qua nếu out_wav đã có."""
    if out_wav.exists():
        return
    af = ["-af", f"atempo={speed}"] if speed > 1.0 else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), *af,
                    "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)], check=True)

def render_dub_track(placed: list[PlacedClip], clip_wavs: list[Path],
                     total_dur: float, out_wav: Path) -> None:
    """Ghép tuần tự: silence-gap + clip + ... (clip không chồng nhau nhờ cursor)."""
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        cursor_frames = 0
        for p, cw in zip(placed, clip_wavs):
            start_frames = int(p.start * SR)
            if start_frames > cursor_frames:
                w.writeframes(b"\x00\x00" * (start_frames - cursor_frames))
                cursor_frames = start_frames
            with wave.open(str(cw), "rb") as r:
                assert r.getframerate() == SR and r.getnchannels() == 1
                frames = r.readframes(r.getnframes())
            w.writeframes(frames)
            cursor_frames += len(frames) // 2
        total_frames = int(total_dur * SR)
        if total_frames > cursor_frames:
            w.writeframes(b"\x00\x00" * (total_frames - cursor_frames))

def mix_into_video(video: Path, dub_wav: Path, out_mp4: Path, bg_volume: float = 0.15) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(dub_wav),
         "-filter_complex",
         f"[0:a]volume={bg_volume}[bg];[bg][1:a]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         str(out_mp4)], check=True)
```

- [ ] **Step 2: Unit test render (không cần mạng — tự sinh wav bằng ffmpeg sine)**

```python
# thêm vào tests/test_assembler.py
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
```

- [ ] **Step 3: Run** → PASS.
- [ ] **Step 4: Integration test e2e (marker slow+network, chạy tay)**

```python
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
```

- [ ] **Step 5: Milestone Ngày 3 (tay):** nối pipeline tạm bằng REPL/scratch script với video 19s, mở `out.viet.mp4` nghe thật. Expected: video gốc nền nhỏ + giọng Việt rõ, khớp thời điểm nói.
- [ ] **Step 6: Commit** — `git commit -am "feat: render dub track (wave concat) + ffmpeg mix"`

**Acceptance:** `pytest tests/test_assembler.py` pass + nghe tay milestone đạt. **Escalation:** không có — đây đã là model mạnh nhất; nếu kẹt thì dừng lại viết note phân tích cho Anh Lan quyết.

---

## NGÀY 4 — CLI, resume, portfolio polish

### Task 10: `cli.py` — orchestration + resume — **Model: sonnet**

**Files:** Create `vietdub/cli.py`, `vietdub/__main__.py`, `tests/test_cli.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_cli.py
from vietdub.cli import build_parser

def test_parser_defaults():
    args = build_parser().parse_args(["https://youtube.com/watch?v=x"])
    assert args.voice == "nu" and args.bg_volume == 0.15
    assert args.whisper_model == "large-v3-turbo" and not args.force

def test_parser_all_flags():
    args = build_parser().parse_args(
        ["URL", "--voice", "nam", "-o", "out.mp4", "--bg-volume", "0.3",
         "--segments", "s.jsonl", "--workdir", "w", "--force"])
    assert args.voice == "nam" and args.output == "out.mp4" and args.force
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**

```python
# vietdub/cli.py
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
```

```python
# vietdub/__main__.py
from vietdub.cli import main
main()
```

- [ ] **Step 4: Run** `pytest tests/test_cli.py -v` → PASS. Rồi chạy integration: `pytest -m "slow and network" tests/test_integration.py -v` → PASS.
- [ ] **Step 5: Chạy thật 1 video dài hơn (5-10'), Ctrl+C giữa chừng, chạy lại** → Expected: các stage đã xong được skip (resume hoạt động).
- [ ] **Step 6: Commit** — `git commit -am "feat: CLI orchestration voi stage caching/resume"`

**Acceptance:** pytest pass + integration pass + resume verify tay. **Escalation:** → opus.

---

### Task 11: README + LICENSE + demo — **Model: haiku**

**Files:** Create `README.md`, `LICENSE` (MIT)

- [ ] **Step 1: README.md** gồm: mô tả 1 đoạn, badge, demo GIF/ảnh, kiến trúc (mermaid flowchart 6 stage như spec §2), bảng CLI flags (đúng theo `build_parser` Task 10), Setup (venv + requirements.txt + ffmpeg/yt-dlp), mục "Cách hoạt động" giải thích 3 tầng fallback, mục Roadmap (VieNeu-TTS local, glossary thuật ngữ, batch playlist), mục "Built with cost-aware agent orchestration" 3-4 câu mô tả quy trình model routing (điểm khoe portfolio).
- [ ] **Step 2: LICENSE** — MIT, copyright 2026.
- [ ] **Step 3: Verify** — mọi lệnh trong README copy-paste chạy được; flag khớp `--help`.
- [ ] **Step 4: Commit** — `git commit -am "docs: README + LICENSE"`

**Acceptance:** README không chứa lệnh sai/flag không tồn tại (orchestrator đối chiếu `--help`). **Escalation:** → sonnet.

---

### Task 12 (stretch — chỉ làm nếu Day 4 còn giờ): backend VieNeu-TTS — **Model: opus**

- [ ] Test thử VieNeu-TTS local (https://github.com/pnnbao97/VieNeu-TTS) trên CPU: tốc độ + chất lượng so edge-tts. Nếu đạt → implement `VieNeuTts(TtsEngine)` trong `tts.py` + flag `--tts vieneu`. Nếu không đạt → ghi kết quả đo vào README Roadmap, không merge code.

**Acceptance:** quyết định có-data (đo tốc độ giây/câu trên CPU thật). **Escalation:** không — stretch goal, hết giờ thì dừng.

---

## Self-review (đã chạy)

- **Spec coverage:** pipeline 6 stage ↔ Task 4,5,6,7,8,9; 3 tầng fallback ↔ Task 5; caching/resume ↔ Task 7 (tts cache) + 10 (stage skip); CLI flags ↔ spec §3 khớp; interop `--segments` ↔ Task 10; curl-cffi + yt-dlp -U ↔ Task 1; VieNeu stretch ↔ Task 12. ✔
- **Type consistency:** `Segment(start, end, text, source, language)` thống nhất; `synth_all` trả `list[tuple[Segment, Path]]` → Task 10 dùng đúng; `plan_timeline` nhận `(Segment, Path, float)` → Task 10 build đúng; `PlacedClip(audio_path, start, speed)` thống nhất Task 8/9/10. ✔
- **Placeholder scan:** không còn TBD/`...`-logic; mọi code block đầy đủ. ✔
- **Lưu ý người thực thi:** Task 3 nói "port từ claudeLearn" trong spec — code parser ở đây đã viết sẵn đầy đủ nên KHÔNG cần mở claudeLearn; chỉ tham khảo `D:\codeClaude\claudeLearn\video_to_text.py` nếu kẹt edge case VTT thực tế.
