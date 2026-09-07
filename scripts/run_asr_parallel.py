#!/usr/bin/env python3
"""
并行 ASR 转写：分块音频 + 多进程并行，大幅提速长视频。

原理：
  1. 将长音频切成 N 块（每块 15-20 分钟，内存可控）
  2. 用 multiprocessing.Pool 并行跑 faster-whisper
  3. 按时间偏移合并字幕结果

自动 VAD 检测（默认）：
  - 先跑第一块（带 VAD），根据字幕密度判断
  - 密集（>8条/分钟）→ 后续块用无 VAD 快速模式
  - 稀疏（≤8条/分钟）→ 后续块保持 VAD

内存自适应（默认）：
  - 自动检测可用内存和 CPU 核数
  - 自动选择模型尺寸（tiny/base/small）
  - 自动调整并行进程数和分块大小
  - 为系统保留至少 4GB 余量，不影响正常使用
  - 可通过环境变量 ASR_MODEL_SIZE / ASR_WORKERS / ASR_CHUNK_MINUTES 覆盖

用法：
  python scripts/run_asr_parallel.py <音频.wav> <输出.json> [输出.txt] [选项]

选项：
  --chunk-minutes CHUNK    每块分钟数（默认 auto，根据内存自适应）
  --workers WORKERS        并行进程数（默认 auto，根据 CPU/内存自适应）
  --model-size SIZE        模型尺寸 tiny|base|small（默认 auto，根据内存自适应）
  --no-vad                 强制禁用 VAD（用 asr_fast.py）
  --vad                    强制启用 VAD（用 asr_subtitle.py，默认自动）
  --keep-chunks            保留分块临时文件

环境变量：
  OMP_NUM_THREADS / MKL_NUM_THREADS  控制 MKL 线程数（默认 2）
  ASR_MODEL_SIZE    tiny | base | small（覆盖模型选择）
  ASR_WORKERS       整数（覆盖并行度）
  ASR_CHUNK_MINUTES 整数（覆盖分块大小）
  ASR_RESERVE_GB    浮点数（覆盖系统保留内存，默认 4）
"""
import json, os, sys, time, argparse, subprocess, shutil, textwrap
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ASR_SUB = str(SCRIPTS / "asr_subtitle.py")   # 带 VAD
ASR_FAST = str(SCRIPTS / "asr_fast.py")       # 无 VAD
DENSITY_THRESHOLD = 8  # 条/分钟，超过则视为密集讲课

# 内存自适应模块
sys.path.insert(0, str(SCRIPTS))
from asr_memory_config import get_asr_config, print_config, MODEL_SIZES


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


def _run_asr_chunk(chunk_info: dict, asr_script: str = None) -> dict:
    """在子进程中跑 ASR，返回 {index, offset, body}。"""
    chunk_path = str(chunk_info["path"])
    offset = chunk_info["offset"]
    index = chunk_info["index"]
    script = asr_script or ASR_SUB

    # 临时输出路径
    tmp_json = chunk_path.replace(".wav", ".json")
    tmp_txt = chunk_path.replace(".wav", ".txt")

    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "2"
    env["MKL_NUM_THREADS"] = "2"

    r = subprocess.run(
        [sys.executable, script, chunk_path, tmp_json, tmp_txt],
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
        description="并行 ASR 转写：分块 + 多进程（内存自适应）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python scripts/run_asr_parallel.py runs/xxx/audio_16k.wav runs/xxx/subtitles.json
              python scripts/run_asr_parallel.py audio.wav out.json --chunk-minutes 20 --workers 2
              python scripts/run_asr_parallel.py audio.wav out.json --no-vad
              python scripts/run_asr_parallel.py audio.wav out.json --model-size tiny
        """))
    ap.add_argument("audio", help="16kHz 单声道 WAV 音频文件")
    ap.add_argument("output_json", help="输出字幕 JSON 路径")
    ap.add_argument("output_txt", nargs="?", default=None, help="输出字幕 TXT 路径")
    ap.add_argument("--chunk-minutes", type=int, default=None,
                    help="每块分钟数（默认 auto，根据内存自适应）")
    ap.add_argument("--workers", type=int, default=None,
                    help="并行进程数（默认 auto，根据 CPU/内存自适应）")
    ap.add_argument("--model-size", type=str, default=None,
                    choices=["tiny", "base", "small"],
                    help="模型尺寸（默认 auto，根据内存自适应）")
    vad_group = ap.add_mutually_exclusive_group()
    vad_group.add_argument("--no-vad", action="store_true", help="强制禁用 VAD（用 asr_fast.py）")
    vad_group.add_argument("--vad", action="store_true", help="强制启用 VAD（用 asr_subtitle.py，默认自动）")
    ap.add_argument("--keep-chunks", action="store_true", help="保留分块临时文件")
    args = ap.parse_args()

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

    # ---- 内存自适应配置 ----
    print(f"\n>>> 内存自适应检测")
    cfg = get_asr_config(
        prefer_model=args.model_size,
        prefer_workers=args.workers,
        prefer_chunk=args.chunk_minutes,
    )
    print_config(cfg)

    # 将模型尺寸写入环境变量，子进程可继承
    os.environ["ASR_MODEL_SIZE"] = cfg.model_size

    t0 = time.time()

    # Step 1: 切分音频
    chunk_dir = audio_path.parent / f"_chunks_{Path(args.output_json).stem}"
    print(f"\n>>> Step 1/3  切分音频 → {chunk_dir}")
    chunks = _split_audio(audio_path, chunk_dir, cfg.chunk_minutes, ffmpeg_bin, ffprobe_bin)
    n_chunks = len(chunks)
    print(f"  共 {n_chunks} 块")

    # Step 2: 并行 ASR
    print(f"\n>>> Step 2/3  并行 ASR（{cfg.workers} 进程）")

    # 自动检测 VAD 模式
    auto_asr: list[str] = []
    if args.no_vad:
        print("  [vad] 强制禁用 VAD（所有块用 asr_fast.py）")
        for _ in chunks:
            auto_asr.append(ASR_FAST)
    elif args.vad:
        print("  [vad] 强制启用 VAD（所有块用 asr_subtitle.py）")
        for _ in chunks:
            auto_asr.append(ASR_SUB)
    else:
        # 默认：先跑第一块（带 VAD），计算密度决定后续
        print("  [vad] 自动检测：先跑第一块计算密度")
        first_chunks = [chunks[0]]
        with ProcessPoolExecutor(max_workers=1) as pool:
            futures = {pool.submit(_run_asr_chunk, ch, ASR_SUB): ch["index"] for ch in first_chunks}
            for fut in as_completed(futures):
                idx = futures[fut]
                res = fut.result()
                n_seg = len(res["body"])
                density = n_seg / (chunks[0]["duration"] / 60)
                print(f"  [chunk 000] OK {n_seg} 条, 密度 {density:.1f} 条/分钟")
                if density > DENSITY_THRESHOLD:
                    print(f"  [vad] 密度 > {DENSITY_THRESHOLD} → 密集讲课，后续启用无 VAD 快速模式")
                    mode_first = ASR_SUB
                    mode_rest = ASR_FAST
                else:
                    print(f"  [vad] 密度 ≤ {DENSITY_THRESHOLD} → 稀疏，后续保持 VAD")
                    mode_first = ASR_SUB
                    mode_rest = ASR_SUB
                auto_asr.append(mode_first)
                for _ in chunks[1:]:
                    auto_asr.append(mode_rest)

    t1 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=cfg.workers) as pool:
        futures = {pool.submit(_run_asr_chunk, ch, auto_asr[i]): i for i, ch in enumerate(chunks)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                res = fut.result()
                results.append(res)
                n_seg = len(res["body"])
                status = "OK" if res["returncode"] == 0 else "FAIL"
                script_name = Path(auto_asr[idx]).name
                print(f"  [chunk {idx:03d}] {status}  {n_seg} 条字幕 ({script_name})"
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