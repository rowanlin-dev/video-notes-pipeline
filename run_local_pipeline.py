#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机视频 → 图文笔记  一键流水线
================================
对本地视频文件做 ASR + 抽帧 + 笔记生成，无需 B 站下载。

用法：
  python run_local_pipeline.py --video /path/to/video.mp4
  python run_local_pipeline.py --video /path/to/video.mp4 --title "自定义标题"
  python run_local_pipeline.py --video /path/to/video.mp4 --segment-minutes 25

依赖：
  pip install faster-whisper av
  ffmpeg（抽取音频用）
"""
import os, sys, json, shutil, subprocess, glob, re, time
import av  # 抽帧用，本地视频流水线硬依赖（需 pip install av）
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# venv 路径跨平台：Windows=venv/Scripts/python.exe，macOS/Linux=venv/bin/python
if os.name == "nt":
    venv_py = ROOT / "venv" / "Scripts" / "python.exe"
else:
    venv_py = ROOT / "venv" / "bin" / "python"
PY = str(venv_py) if venv_py.exists() else sys.executable
SCRIPTS = ROOT / "scripts"


def load_env():
    """读取 .env 到进程环境（不覆盖已有变量）。"""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def safe_name(s: str, limit=60) -> str:
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s[:limit].rstrip(" .") or "untitled"


def run(cmd, cwd=None, env=None, step=""):
    print(f"\n{'=' * 62}")
    if step:
        print(f">> {step}")
    print(f"{'=' * 62}")
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env)
    if r.returncode != 0:
        print(f"\n[fail] 步骤失败：{step} (exit {r.returncode})", file=sys.stderr)
        sys.exit(r.returncode)


def get_video_duration(video_path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", video_path], capture_output=True, text=True)
    return float(r.stdout.strip())


def main():
    import argparse
    ap = argparse.ArgumentParser(description="本机视频转图文笔记流水线")
    ap.add_argument("--video", required=True, help="本地视频文件路径")
    ap.add_argument("--title", default=None, help="笔记标题（缺省用文件名）")
    ap.add_argument("--interval", type=int, default=5, help="抽帧间隔（秒，默认 5）")
    ap.add_argument("--min-frames", type=int, default=5, help="最少精选帧数")
    ap.add_argument("--max-frames", type=int, default=12, help="精选基础上限")
    ap.add_argument("--hard-max-frames", type=int, default=30, help="精选绝对上限")
    ap.add_argument("--segment-minutes", type=int, default=0,
                    help="长视频切块：每段约多少分钟（<=1 关闭切块，默认关闭）")
    ap.add_argument("--max-segments", type=int, default=12, help="长视频切块最大段数")
    ap.add_argument("--no-ima", action="store_true", help="跳过上传到 ima 知识库")
    ap.add_argument("--emit-brief", action="store_true",
                    help="Agent 原生模式：生成笔记简报后停止，由宿主 Agent 自带模型撰写笔记")
    ap.add_argument("--from-step", type=int, default=1, help="从第几步开始")
    args = ap.parse_args()

    load_env()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"[error] 视频文件不存在：{video_path}", file=sys.stderr)
        sys.exit(1)

    title = args.title or video_path.stem
    bvid = f"local_{safe_name(title)}"
    page = 1
    run_dir = ROOT / "runs" / f"{bvid}_p{page}"
    scene_dir = run_dir / "scene"
    selected_dir = run_dir / "selected"
    final_dir = run_dir / "final"
    out_dir = run_dir / "output"
    img_dir = out_dir / "images"
    for d in [run_dir, scene_dir, selected_dir, final_dir, out_dir, img_dir]:
        d.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    # 优先使用完整版 ffmpeg（WinGet 安装的 Gyan.FFmpeg），TRAE 自带精简版缺少音频编码器
    full_ffmpeg_dir = Path(r"C:\Users\12629\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0-full_build\bin")
    env["PATH"] = str(full_ffmpeg_dir) + os.pathsep + env.get("PATH", "")
    ffmpeg_bin = str(full_ffmpeg_dir / "ffmpeg.exe")
    env["BILI_NOTES_WORKSPACE"] = str(run_dir)
    env["BILI_NOTES_FRAMES"] = str(run_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["LEARNED_TRASH_FILE"] = ""       # 本地视频禁用自进化黑名单，避免跨视频误杀
    env["HASH_THRESHOLD"] = "20"         # 适当提高哈希去重阈值，保留更多帧

    # 本地视频直接使用原始文件，不再复制到工作目录
    # （避免大文件二次占用磁盘空间与拷贝耗时；源文件不会被修改，可安全直读）
    video_ws = video_path
    duration = get_video_duration(str(video_ws))
    print(f"[pipeline] 视频时长：{duration:.0f}s ({duration/60:.1f}min)")
    print(f"[pipeline] 标题：{title}")
    print(f"[pipeline] 工作目录：{run_dir}")

    t0 = time.time()

    # ---- Step 1: 提取音频 + ASR 字幕 ----
    sub_json = run_dir / f"{bvid}_p{page}_subtitles.json"
    sub_txt = run_dir / f"{bvid}_p{page}_subtitles.txt"

    if args.from_step <= 1:
        if not sub_json.exists():
            print(f"\n{'=' * 62}")
            print(">> Step 1/6  提取音频 + ASR 语音转文字")
            print(f"{'=' * 62}")
            audio_wav = run_dir / "audio_16k.wav"
            # 提取音频
            subprocess.run([ffmpeg_bin, "-y", "-i", str(video_ws),
                           "-vn", "-ar", "16000", "-ac", "1", str(audio_wav)],
                           check=True, capture_output=True, env=env)
            print(f"  音频提取完成：{audio_wav}")

            # ASR 转写
            subprocess.run([PY, str(SCRIPTS / "asr_subtitle.py"),
                           str(audio_wav), str(sub_json), str(sub_txt)],
                           check=True, env=env)
            print(f"  ASR 字幕已生成：{sub_json}")

            # 清理临时音频
            if audio_wav.exists():
                audio_wav.unlink()
                print(f"  临时音频已清理")
        else:
            print(f"  字幕已存在，跳过 ASR")

    # ---- Step 1b: 抽帧 ----
    if args.from_step <= 1:
        existing_frames = sorted(glob.glob(str(scene_dir / "frame_*.jpg")))
        if not existing_frames:
            print(f"\n{'=' * 62}")
            print(">> Step 1b/6  抽帧")
            print(f"{'=' * 62}")
            timestamps = list(range(0, int(duration), args.interval))
            print(f"  {len(timestamps)} frames at {args.interval}s intervals")

            container = av.open(str(video_ws))
            stream = container.streams.video[0]
            fc = 0
            for ts in timestamps:
                # 指定 stream 时，av_seek_frame 的时间戳以「流时基」为单位，
                # 需把「秒」换算成流时间戳（ts / stream.time_base）；
                # 流时基缺失（极端情况）时回退到微秒（AV_TIME_BASE = 1e6）。
                # 注意：旧写法 int(ts * av.time_base) 会把秒除以 1e6，几乎恒为 0，
                # 导致所有帧都 seek 到视频开头同一帧。
                if stream.time_base:
                    seek_ts = int(ts / stream.time_base)
                else:
                    seek_ts = int(ts * 1_000_000)
                # seek 到最近的关键帧（默认 seek 到 PTS >= seek_ts 的关键帧）
                container.seek(seek_ts, stream=stream)
                # 关键帧可能远早于目标时间戳（尤其屏幕录制视频 GOP 很长），
                # 需要继续解码直到到达目标时间戳，否则所有帧都取到同一个关键帧。
                for frame in container.decode(video=0):
                    # frame.time 是帧的显示时间（秒），尚未到达目标则跳过继续解码
                    if frame.time is not None and frame.time < ts - 0.05:
                        continue
                    img = frame.to_image()
                    out = scene_dir / f"frame_{fc+1:04d}_{ts//60:02d}m{ts%60:02d}s.jpg"
                    img.save(str(out), "JPEG", quality=85)
                    fc += 1
                    break
            container.close()
            print(f"  提取 {fc} 帧")
        else:
            print(f"  {len(existing_frames)} 帧已存在，跳过抽帧")

    n_raw = len(list(scene_dir.glob("frame_*.jpg")))
    print(f"[pipeline] 原始帧：{n_raw}")

    # ---- Step 2: OCR 预筛 + 去重 ----
    if args.from_step <= 2:
        run([PY, SCRIPTS / "smart_select.py", scene_dir,
             "--output-dir", selected_dir, "--workspace", run_dir],
            env=env, step="Step 2/6  OCR 预筛 + 感知哈希去重")

    n_sel = len(list(selected_dir.glob("*.jpg")))
    print(f"[pipeline] 去重后：{n_sel}")

    if n_sel == 0:
        print("[warn] 没有帧通过去重，跳过后续帧处理步骤")

    scores_json = run_dir / "vision_scores.json"
    extract_json = run_dir / "vision_extract.json"

    # ---- Step 3: 视觉打分 ----
    if args.from_step <= 3 and n_sel > 0:
        run([PY, SCRIPTS / "score_frames_concurrent.py",
             "--frames", selected_dir, "--output", scores_json, "--mode", "score"],
            env=env, step="Step 3/6  多模态视觉打分")

    # ---- Step 4: 自动精选 ----
    if args.from_step <= 4 and n_sel > 0:
        select_cmd = [PY, ROOT / "auto_select.py",
                      "--scores", scores_json, "--selected-dir", selected_dir,
                      "--final-dir", final_dir,
                      "--min", str(args.min_frames), "--max", str(args.max_frames),
                      "--hard-max", str(args.hard_max_frames)]
        select_cmd += ["--min-score", os.getenv("FRAME_MIN_SCORE", "3")]
        select_cmd += ["--learned-trash", ""]  # 显式禁用自进化黑名单
        run(select_cmd, env=env, step="Step 4/6  按分数 + 主题多样性自动精选")

    n_final = len(list(final_dir.glob("*.jpg")))
    print(f"[pipeline] 精选帧：{n_final}")

    # ---- Step 5: 图内文字提取 ----
    if args.from_step <= 5 and n_final > 0:
        try:
            run([PY, SCRIPTS / "score_frames_concurrent.py",
                 "--frames", final_dir, "--output", extract_json, "--mode", "extract"],
                env=env, step="Step 5/6  提取图中文字/公式/流程")
        except SystemExit:
            print("[warn] 图内文字提取部分失败，继续生成笔记")

    # ---- Step 6: 生成 MD + PDF ----
    if args.from_step <= 6:
        for f in final_dir.glob("*.jpg"):
            shutil.copy2(str(f), str(img_dir / f.name))

        note_md = out_dir / f"{safe_name(title)}.md"
        cmd = [PY, ROOT / "md_note.py",
               "--bvid", bvid, "--page", str(page), "--title", title,
               "--final-dir", final_dir,
               "--origin-map", selected_dir / "_origin_map.json",
               "--extract-json", extract_json,
               "--scores-json", scores_json,
               "--interval", str(args.interval),
               "--img-prefix", "images",
               "--output", note_md,
               "--subject", "general",
               "--desc", f"本地视频：{video_path.name}",
               "--duration", str(int(duration)),
               "--comment-enabled", "0",
               "--stat-view", "0", "--stat-like", "0", "--stat-favorite", "0"]
        if args.segment_minutes and args.segment_minutes > 1:
            cmd += ["--segment-minutes", str(args.segment_minutes),
                    "--max-segments", str(args.max_segments)]
        if sub_txt.exists():
            cmd += ["--subtitle", sub_txt]
        if args.emit_brief:
            cmd += ["--emit-brief"]
        run(cmd, env=env, step="Step 6/6  导出 Agent 原生模式简报" if args.emit_brief
             else "Step 6/6  融合字幕生成 Markdown 笔记")

        # Agent 原生模式：导出简报后停止，由宿主 Agent 自带模型撰写笔记
        if args.emit_brief:
            brief = note_md.with_name("_brief.md")
            print(f"\n{'=' * 62}")
            print(f"[Agent 模式] 已导出简报：{brief}")
            print(f"  请宿主 Agent 按简报撰写 {note_md}（含图文穿插），再运行：")
            print(f"    python md2pdf.py --input {note_md}")
            print(f"{'=' * 62}")
            return  # 跳过 PDF 与 ima 上传，交由 Agent 完成笔记

        # 生成 PDF
        run([PY, ROOT / "md2pdf.py", "--input", note_md],
            env=env, step="  转 PDF")

        print(f"\n{'=' * 62}")
        print(f"完成！总耗时 {time.time() - t0:.0f}s")
        print(f"  Markdown : {note_md}")
        pdf = note_md.with_suffix(".pdf")
        if pdf.exists():
            print(f"  PDF      : {pdf}")
        print(f"  配图     : {img_dir}")
        print(f"{'=' * 62}")

        # ---- （可选）上传到 ima 知识库 ----
        if not args.no_ima and pdf.exists():
            to_ima = ROOT / "to_ima.py"
            kb_id = os.getenv("IMA_KB_ID")
            route = os.getenv("IMA_ROUTE")
            if kb_id or route:
                ima_cmd = [PY, to_ima, "--pdf", str(pdf)]
                if route:
                    ima_cmd += ["--route", "--md", str(note_md)]
                elif kb_id:
                    ima_cmd += ["--kb-id", str(kb_id)]
                try:
                    run(ima_cmd, env=env, step="  上传到 ima 知识库")
                except SystemExit:
                    print("[warn] ima 上传失败，MD/PDF 已生成，可单独运行 to_ima.py 重试")


if __name__ == "__main__":
    main()