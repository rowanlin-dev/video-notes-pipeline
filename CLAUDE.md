# Bilibili Video Notes (tool entry · v1.1.5)

Turn Bilibili educational videos into illustrated **Markdown + PDF** notes with clickable timestamps, optionally archived into the ima knowledge base.

> Current version **v1.1.5**, kept in sync with `SKILL.md`; when SKILL.md changes this file is updated too. The endpoint auto-updater (`update_skill.py`) already lists this file in its whitelist.

See **SKILL.md** for the full reference. This file is a quick-start for AI agents/collaborators.

## Workflow

Orchestrated by `run_pipeline.py` in seven steps (resume from any step with `--from-step`):

1. Download video + official AI subtitles (`scripts/extract_frames.py`)
2. OCR pre-filter + perceptual-hash dedup (`scripts/smart_select.py`)
3. Multimodal vision scoring (`scripts/score_frames_concurrent.py --mode score`)
4. Auto-select by score + topic diversity (`auto_select.py`)
5. Extract text/figures/formulas from selected frames (`score_frames_concurrent.py --mode extract`)
6. Fuse subtitles + extracted content into Markdown + PDF (`md_note.py` / `md2pdf.py`)
7. (Optional) Upload to ima knowledge base (`to_ima.py`)

## Time Estimate

**Tell the user the estimated processing time BEFORE starting** (empirical formula, v1.0.2, see SKILL.md):

> **Processing time ≈ 5 + 0.56 × video minutes** (minutes; floor ~6 min)

| Video length | Estimated total | Where the time goes |
|---------|-------------|-------------|
| ≤5 min | ~6-8 min | Fixed overhead (download/frames/notes/PDF/upload) |
| 10 min | ~10-12 min | Download ~1min + ASR + frame scoring |
| 30 min | ~20-25 min | ASR transcription dominates (~0.5-0.7× audio length) |
| 60 min | ~35-40 min | Consider `--segment-minutes 25` |

Measured samples: 3.6 min → ~6 min; 10 min → ~12 min; 33 min → ~23 min.

## Setup

```bash
pip install -r scripts/requirements.txt
```

System `ffmpeg` required.

Configure API:

```bash
cp templates/env.example .env
# fill VISION_API_KEY, VISION_BASE_URL, VISION_MODEL
```

Configure Bilibili cookie:

```bash
cp bilibili_cookies.txt.example bilibili_cookies.txt
# fill SESSDATA from browser F12
```

## Usage

```bash
# One-shot (default current P)
python run_pipeline.py BV1xx411c7mD

# Operation-type videos (code demos/editing): lower threshold
python run_pipeline.py BV1hD42137sx --threshold 0.02 --merge-gap 1.5

# Resume from step 4
python run_pipeline.py BV1xx411c7mD --from-step 4
```

Outputs land in `runs/<BV>_p<N>/output/`. More parameters in SKILL.md.

## Local video

When the user provides a **local video file** (not a Bilibili URL) and wants notes, use `run_local_pipeline.py` (no Cookie / network needed):

```bash
python run_local_pipeline.py --video /path/to/video.mp4
python run_local_pipeline.py --video /path/to/video.mp4 --title "Custom Title"
python run_local_pipeline.py --video /path/to/video.mp4 --segment-minutes 25   # long video splitting
```

Pipeline: extract audio → local ASR (faster-whisper) → interval frames (PyAV) → OCR dedup → vision scoring → auto-select → MD + PDF → (optional) ima.
Differences from Bilibili: self-evolving blacklist disabled by default, hash-dedup threshold 20, output in `runs/local_<title>_p1/output/`.
Dep: extra `pip install av`.

## Agent-native mode (no external LLM)

If the host Agent has its own model, skip the skill's built-in LLM: add `--emit-brief` to the command; the script exports `output/_brief.md` (materials + writing spec) and stops. The Agent writes `note.md` per the brief, then `python md2pdf.py --input <note.md>` renders it. No `TEXT_API_KEY` needed. Default behavior unchanged. See SKILL.md.

## Common Pitfalls

- Bilibili HTTP 412 risk-control: bypass with playurl API + `curl --http1.1` (see SKILL.md)
- Missing/mismatched official AI subtitles: fall back to local ASR (automatic speech recognition) — `scripts/asr_subtitle.py` transcribes the audio with faster-whisper
- Garbled Chinese in PDF: weasyprint + TTF font (`scripts/gen_full_note.py`)
- Zhipu API 429: retry with `--workers 2 --resume` lower concurrency
