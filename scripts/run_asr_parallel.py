#!/usr/bin/env python3
"""
并行 ASR 转写：分块音频 + 多进程并行，大幅提速长视频。

原理：
  1. 将长音频切成 N 块（每块 15-20 分钟，内存可控）
  2. 用 multiprocessing.Pool 并行跑 faster-whisper
  3. 按时间偏移合并字幕结果

用法：
  python scripts/run_asr_parallel.py <音频.wav> <输出.json> [输出.txt] [选项]

选项：
  --chunk-minutes CHUNK    每块分钟数（默认 15，越小内存越省）
  --workers WORKERS        并行进程数（默认 4，根据 CPU 核数调整）
  --no-vad                 禁用 VAD（
  --keep-chunks            保留分块临时文件

环境变量：
  OMP_NUM_THREADS / MKL_NUM_THREADS  控制 MKL 线程数（默认 2）
"""
import json, os, sys, time, argparse, subprocess, shutil, textwrap
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ASR_SCRIPT = str(SCRIPTS / "asr_subtitle.py")


def _mmss(s: float) -> str:
    s = int(round(s))
    m, sec = divmod(s, 60)
    return f"{m:02d}m{sec:02d}s"


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m < 60 else f"{m//60}h{m%60:02d}m"


def _split_audio(audio_path: Path, chunk_dir: Path, chunk_minutes: int,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> list[dict]:
    """用 ffmpeg 切分音频为等长块（最后一块可能短些）。"""
    import subprocess as sp

    # 获取音频时长
    r = sp.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(audio_path)], capture_output=True, text=True)
    duration = float(r.stdout.strip())
    chunk_sec = chunk_minutes * 60
    n_chunks = max(1, int(duration // chunk_sec) + (1 if duration % chunk_sec > 0 else 0))

    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunks = []

    for i in range(n_chunks):
        start = i * chunk_sec
        actual_sec = min(chunk_sec, duration - start)
        out = chunk_dir / f"chunk_{i:03d}.wav"

        # 用传入的 ffmpeg 路径
        sp.run([ffmpeg, "-y", "-ss", str(start), "-t", str(actual_sec),
                "-i", str(audio_path), "-c", "copy", str(out)],
               capture_output=True, check=True)

        chunks.append({
            "index": i,
            "path": out,
            "offset": start,
            "duration": actual_sec,
        })
        print(f"  [chunk {i:03d}] {_mmss(start)}-{_mmss(start+actual_sec)} ({_fmt_duration(actual_sec)})")

    return chunks


def _resolve_ffmpeg() -> tuple[str, str]:
    """优先使用 WinGet 完整版 ffmpeg/ffprobe。
    返回 (ffmpeg_path, ffprobe_path)，找不到则回退 PATH。
    """
    pkgs = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if pkgs.is_dir():
        matches = sorted(pkgs.glob("Gyan.FFmpeg_*/ffmpeg-*-full_build/bin"), reverse=True)
        for d in matches:
            ffmpeg = d / "ffmpeg.exe"
            ffprobe = d / "ffprobe.exe"
            if ffmpeg.exists() and ffprobe.exists():
                return str(ffmpeg), str(ffprobe)
    return "ffmpeg", "ffprobe"


def _run_asr_chunk(chunk_info: dict) -> dict:
    """在子进程中跑 ASR，返回 {index, offset, body}。"""
    chunk_path = str(chunk_info["path"])
    offset = chunk_info["offset"]
    index = chunk_info["index"]

    # 临时输出路径（JSON + TXT 都落在 chunk_dir，避免写入 cwd 产生 stray subtitles.txt）
    tmp_json = chunk_path.replace(".wav", ".json")
    tmp_txt = chunk_path.replace(".wav", ".txt")

    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "2"
    env["MKL_NUM_THREADS"] = "2"

    r = subprocess.run(
        [sys.executable, ASR_SCRIPT, chunk_path, tmp_json, tmp_txt],
        capture_output=True, text=True, env=env
    )

    body = []
    if r.returncode == 0 and os.path.exists(tmp_json):
        with open(tmp_json) as f:
            data = json.load(f)
        for seg in data.get("body", []):
            body.append({
                "from": round(seg["from"] + offset, 1),
                "to": round(seg["to"] + offset, 1),
                "content": seg["content"],
            })

    return {"index": index, "offset": offset, "body": body, "returncode": r.returncode,
            "stderr": r.stderr[:200] if r.stderr else ""}


def main():
    ap = argparse.ArgumentParser(
        description="并行 ASR 转写：分块 + 多进程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python scripts/run_asr_parallel.py runs/xxx/audio_16k.wav runs/xxx/subtitles.json
              python scripts/run_asr_parallel.py audio.wav out.json --chunk-minutes 20 --workers 2
        """))
    ap.add_argument("audio", help="16kHz 单声道 WAV 音频文件")
    ap.add_argument("output_json", help="输出字幕 JSON 路径")
    ap.add_argument("output_txt", nargs="?", default=None, help="输出字幕 TXT 路径")
    ap.add_argument("--chunk-minutes", type=int, default=15, help="每块分钟数（默认 15）")
    ap.add_argument("--workers", type=int, default=4, help="并行进程数（默认 4）")
    ap.add_argument("--no-vad", action="store_true", help="禁用 VAD（用 asr_fast.py）")
    ap.add_argument("--keep-chunks", action="store_true", help="保留分块临时文件")
    args = ap.parse_args()

    global ASR_SCRIPT
    if args.no_vad:
        ASR_SCRIPT = str(SCRIPTS / "asr_fast.py")

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"[error] 音频不存在: {audio_path}", file=sys.stderr)
        sys.exit(1)

    # 解析完整版 ffmpeg/ffprobe
    ffmpeg_bin, ffprobe_bin = _resolve_ffmpeg()
    if ffmpeg_bin != "ffmpeg":
        print(f"[pipeline] 使用完整版 ffmpeg: {ffmpeg_bin}")

    # 音频时长
    r = subprocess.run([ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(audio_path)], capture_output=True, text=True)
    duration = float(r.stdout.strip())
    print(f"[pipeline] 音频: {audio_path.name} ({_fmt_duration(duration)})")
    print(f"[pipeline] 分块: {args.chunk_minutes}min/块 × {args.workers} 进程并行")

    t0 = time.time()

    # Step 1: 切分音频
    chunk_dir = audio_path.parent / f"_chunks_{Path(args.output_json).stem}"
    print(f"\n>>> Step 1/3  切分音频 → {chunk_dir}")
    chunks = _split_audio(audio_path, chunk_dir, args.chunk_minutes, ffmpeg_bin, ffprobe_bin)
    n_chunks = len(chunks)
    print(f"  共 {n_chunks} 块")

    # Step 2: 并行 ASR
    print(f"\n>>> Step 2/3  并行 ASR（{args.workers} 进程）")
    t1 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_asr_chunk, ch): ch["index"] for ch in chunks}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                res = fut.result()
                results.append(res)
                n_seg = len(res["body"])
                status = "OK" if res["returncode"] == 0 else "FAIL"
                print(f"  [chunk {idx:03d}] {status}  {n_seg} 条字幕"
                      + (f"  err: {res['stderr'][:80]}" if res["returncode"] != 0 else ""))
            except Exception as e:
                print(f"  [chunk {idx:03d}] ERROR: {e}")
                results.append({"index": idx, "offset": 0, "body": [], "returncode": -1, "stderr": str(e)})

    print(f"  ASR 耗时: {_fmt_duration(time.time() - t1)}")

    # Step 3: 合并
    print(f"\n>>> Step 3/3  合并字幕")
    results.sort(key=lambda x: x["index"])
    all_body = []
    for res in results:
        all_body.extend(res["body"])

    # 写 JSON
    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"body": all_body}, f, ensure_ascii=False, indent=1)

    # 写 TXT
    txt_path = Path(args.output_txt or args.output_json.replace(".json", ".txt"))
    with open(txt_path, "w", encoding="utf-8") as f:
        for s in all_body:
            f.write(f"[{_mmss(s['from'])}] {s['content']}\n")

    # 清理
    if not args.keep_chunks and chunk_dir.exists():
        shutil.rmtree(chunk_dir)
        print(f"  临时分块已清理")

    total = time.time() - t0
    print(f"\n{'=' * 55}")
    print(f"完成！{len(all_body)} 条字幕, 总耗时 {_fmt_duration(total)}")
    print(f"  JSON: {out_path}")
    print(f"  TXT:  {txt_path}")
    print(f"{'=' * 55}")

    for s in all_body[:5]:
        print(f"  {s['from']:6.1f}-{s['to']:6.1f}  {s['content'][:60]}")


if __name__ == "__main__":
    main()