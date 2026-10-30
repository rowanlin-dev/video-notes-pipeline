#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机视频 → 图文笔记  一键流水线
================================
对本地视频文件做 ASR + 抽帧 + 笔记生成，无需 B 站下载。

视觉模式（两个独立维度）：
  - 长视频(≥30min) 默认只做脑图：跳过抽帧/OCR/打分/精选/文字提取，只做 ASR + 笔记 + Mermaid 图，
    避免产生上千张截图文件。
  - 短视频 默认「截图 + 脑图」并存：保留抽帧图文，同时生成思维脑图补充结构性内容。
  - 均可用 --brain-map / --no-brain-map（控制是否跳过截图）、--mind-map / --no-mind-map（控制是否生成脑图）覆盖。

用法：
  python run_local_pipeline.py --video /path/to/video.mp4
  python run_local_pipeline.py --video /path/to/video.mp4 --title "自定义标题"
  python run_local_pipeline.py --video /path/to/video.mp4 --segment-minutes 25
  python run_local_pipeline.py --video /path/to/long_lecture.mp4 --parallel-asr --asr-workers 4
  python run_local_pipeline.py --video /path/to/short.mp4 --no-mind-map        # 短视频只截图不画脑图
  python run_local_pipeline.py --video /path/to/long.mp4 --no-brain-map        # 强制截图（长视频也做截图）
  python run_local_pipeline.py --video /path/to/long.mp4 --no-brain-map --mind-map  # 长视频也要截图+脑图

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
    s = re.sub(r"\s+", "_", s)
    return s[:limit].rstrip("_. ") or "untitled"


def run(cmd, cwd=None, env=None, step=""):
    print(f"\n{'=' * 62}")
    if step:
        print(f">> {step}")
    print(f"{'=' * 62}")
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env)
    if r.returncode != 0:
        print(f"\n[fail] 步骤失败：{step} (exit {r.returncode})", file=sys.stderr)
        sys.exit(r.returncode)


def get_video_duration(video_path: str, ffprobe_bin: str = "ffprobe") -> float:
    r = subprocess.run([ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", video_path], capture_output=True, text=True)
    return float(r.stdout.strip())


def _resolve_full_ffmpeg():
    """定位 WinGet 安装的「完整版」Gyan.FFmpeg（TRAE 等 IDE 自带精简版缺音频编码器）。

    用 glob 适配版本目录名（ffmpeg-8.0-full_build 等会变），找到返回其 bin 目录；
    否则返回 None（调用方回退到 PATH 上的 ffmpeg），保证 Mac/Linux 与未装完整版的
    Windows 也能正常抽取音频。
    """
    pkgs = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if pkgs.is_dir():
        matches = sorted(pkgs.glob("Gyan.FFmpeg_*/ffmpeg-*-full_build/bin"), reverse=True)
        for d in matches:
            if (d / "ffmpeg.exe").exists():
                return d
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser(description="本机视频转图文笔记流水线")
    ap.add_argument("--video", required=True, help="本地视频文件路径")
    ap.add_argument("--title", default=None, help="笔记标题（缺省用文件名）")
    ap.add_argument("--run-id", default=None,
                    help="运行目录 / 产物标识（缺省 local_<标题>；小红书传 xhs_<作品ID>）")
    ap.add_argument("--desc", default=None,
                    help="作品简介（缺省用「本地视频：文件名」；用于学科自动分类）")
    ap.add_argument("--context-file", default=None,
                    help="补充素材文本（如小红书作者正文），融入笔记提示词")
    ap.add_argument("--source-label", default="",
                    help="来源标注（如「小红书 · @作者」），覆盖笔记头部的本地视频来源行")
    ap.add_argument("--source-link", default="",
                    help="来源页链接，仅用于笔记头部展示（不用于时间戳跳转）")
    ap.add_argument("--source-url", default="",
                    help="原视频在线链接（如 B 站分享链接）。提供后笔记时间戳可点击跳转到原视频对应时间点")
    ap.add_argument("--interval", type=int, default=5, help="抽帧间隔（秒，默认 5）")
    ap.add_argument("--min-frames", type=int, default=5, help="最少精选帧数")
    ap.add_argument("--max-frames", type=int, default=12, help="精选基础上限")
    ap.add_argument("--hard-max-frames", type=int, default=30, help="精选绝对上限")
    ap.add_argument("--brain-map", dest="brain_map", action="store_true", default=None,
                    help="只做脑图：跳过抽帧/OCR/打分/精选/文字提取，只做 ASR + 笔记 + Mermaid 图"
                         "（默认长视频≥30min 自动启用）")
    ap.add_argument("--no-brain-map", dest="brain_map", action="store_false",
                    help="强制执行截图流程，即使长视频也做截图图文笔记")
    ap.add_argument("--mind-map", dest="mind_map", action="store_true", default=None,
                    help="生成思维脑图（默认全开；短视频为「截图+脑图」并存，长视频为只做脑图）")
    ap.add_argument("--no-mind-map", dest="mind_map", action="store_false",
                    help="不生成脑图，只做纯截图图文笔记（长视频会因无截图而无图，仅极端场景使用）")
    ap.add_argument("--segment-minutes", type=int, default=0,
                    help="长视频切块：每段约多少分钟（<=1 关闭切块，默认关闭）")
    ap.add_argument("--max-segments", type=int, default=12, help="长视频切块最大段数")
    ap.add_argument("--no-ima", action="store_true", help="跳过上传到 ima 知识库")
    ap.add_argument("--emit-brief", action="store_true",
                    help="Agent 原生模式：生成笔记简报后停止，由宿主 Agent 自带模型撰写笔记")
    ap.add_argument("--from-step", type=int, default=1, help="从第几步开始")
    ap.add_argument("--parallel-asr", dest="parallel_asr", action="store_true", default=None,
                    help="强制并行分块 ASR（长视频提速）；默认时长≥30min 自动启用")
    ap.add_argument("--no-parallel-asr", dest="parallel_asr", action="store_false",
                    help="关闭并行 ASR，强制单进程（与原版一致）")
    ap.add_argument("--asr-workers", type=int, default=None,
                    help="并行 ASR 进程数（默认 auto，根据 CPU/内存自适应）")
    ap.add_argument("--asr-chunk-minutes", type=int, default=None,
                    help="并行 ASR 每块分钟数（默认 auto，根据内存自适应）")
    ap.add_argument("--asr-model-size", type=str, default=None,
                    choices=["tiny", "base", "small"],
                    help="ASR 模型尺寸（默认 auto，根据内存自适应）")
    args = ap.parse_args()

    load_env()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"[error] 视频文件不存在：{video_path}", file=sys.stderr)
        sys.exit(1)

    title = args.title or video_path.stem
    bvid = args.run_id or f"local_{safe_name(title)}"
    page = 1
    run_dir = ROOT / "runs" / f"{bvid}_p{page}"
    scene_dir = run_dir / "scene"
    selected_dir = run_dir / "selected"
    final_dir = run_dir / "final"
    out_dir = run_dir / "output"
    img_dir = out_dir / "images"

    # 先解析 ffmpeg/ffprobe 路径（时长检测需要 ffprobe）
    full_ffmpeg_dir = _resolve_full_ffmpeg()
    if full_ffmpeg_dir is not None:
        ffmpeg_bin = str(full_ffmpeg_dir / "ffmpeg.exe")
        ffprobe_bin = str(full_ffmpeg_dir / "ffprobe.exe")
    else:
        ffmpeg_bin = "ffmpeg"
        ffprobe_bin = "ffprobe"

    video_ws = video_path
    duration = get_video_duration(str(video_ws), ffprobe_bin)
    print(f"[pipeline] 视频时长：{duration:.0f}s ({duration/60:.1f}min)")
    print(f"[pipeline] 标题：{title}")
    print(f"[pipeline] 工作目录：{run_dir}")

    # ---- 视觉模式：两个独立维度 ----
    #   skip_screenshots：跳过抽帧/OCR/打分/精选/文字提取（仅长视频，避免上千截图文件）
    #   mind_map         ：是否生成思维脑图（所有视频都生成；无截图时脑图是唯一视觉元素）
    # 长视频(≥30min) 默认只做脑图；短视频默认「截图 + 脑图」并存。
    # 两者都可用 --brain-map / --no-brain-map、--mind-map / --no-mind-map 覆盖。
    skip_screenshots = args.brain_map
    if skip_screenshots is None:
        skip_screenshots = duration >= 1800
    mind_map = args.mind_map
    if mind_map is None:
        mind_map = True  # 脑图对短视频也有价值，默认全开

    if args.brain_map is not None:
        print(f"[pipeline] 脑图模式={'强制启用' if args.brain_map else '强制关闭'}"
              f"（截图流程={'跳过' if skip_screenshots else '执行'}）")
    elif skip_screenshots:
        print(f"[pipeline] 视频 >30min，自动只做脑图（跳过截图流程：ASR + 笔记 + Mermaid 图）")
    else:
        print(f"[pipeline] 短视频模式：截图 + 脑图并存"
              f"（{'跳过' if skip_screenshots else '执行'}截图流程）")
    print(f"[pipeline] 思维脑图={'启用' if mind_map else '关闭'}")

    # 只做脑图时仅创建 output 目录；截图模式才建截图相关目录
    if skip_screenshots:
        for d in [run_dir, out_dir, img_dir]:
            d.mkdir(parents=True, exist_ok=True)
    else:
        for d in [run_dir, scene_dir, selected_dir, final_dir, out_dir, img_dir]:
            d.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    # 优先使用 WinGet 安装的「完整版」Gyan.FFmpeg（TRAE 等 IDE 自带精简版缺音频编码器）。
    # 找不到则回退 PATH 上的 ffmpeg（Windows/Mac/Linux 通用），不在别的机器上崩。
    if full_ffmpeg_dir is not None:
        env["PATH"] = str(full_ffmpeg_dir) + os.pathsep + env.get("PATH", "")
        if not ffmpeg_bin.startswith("C:"):
            ffmpeg_bin = str(full_ffmpeg_dir / "ffmpeg.exe")
        print(f"[pipeline] 使用完整版 ffmpeg：{ffmpeg_bin}")
    env["BILI_NOTES_WORKSPACE"] = str(run_dir)
    env["BILI_NOTES_FRAMES"] = str(run_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["LEARNED_TRASH_FILE"] = ""       # 本地视频禁用自进化黑名单，避免跨视频误杀
    env["HASH_THRESHOLD"] = "20"         # 适当提高哈希去重阈值，保留更多帧

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

            # ASR 转写：长视频自动并行分块（默认≥30min），可用 flag 强制启用/关闭
            use_parallel = args.parallel_asr if args.parallel_asr is not None else (duration >= 1800)
            if use_parallel:
                asr_cmd = [PY, str(SCRIPTS / "run_asr_parallel.py"), str(audio_wav),
                           str(sub_json), str(sub_txt)]
                if args.asr_workers is not None:
                    asr_cmd += ["--workers", str(args.asr_workers)]
                if args.asr_chunk_minutes is not None:
                    asr_cmd += ["--chunk-minutes", str(args.asr_chunk_minutes)]
                if args.asr_model_size is not None:
                    asr_cmd += ["--model-size", args.asr_model_size]
                print(f"  长视频（{duration / 60:.0f}min）→ 并行分块 ASR（内存自适应）")
            else:
                asr_cmd = [PY, str(SCRIPTS / "asr_subtitle.py"),
                           str(audio_wav), str(sub_json), str(sub_txt)]
                if args.asr_model_size is not None:
                    os.environ["ASR_MODEL_SIZE"] = args.asr_model_size
            subprocess.run(asr_cmd, check=True, env=env)
            print(f"  ASR 字幕已生成：{sub_json}")

            # 清理临时音频
            if audio_wav.exists():
                audio_wav.unlink()
                print(f"  临时音频已清理")
        else:
            print(f"  字幕已存在，跳过 ASR")

    # ---- 只做脑图时：跳过截图流程 ----
    if skip_screenshots:
        print(f"[pipeline] 跳过抽帧 → OCR → 打分 → 精选 → 文字提取（长视频只做脑图）")
        n_raw = n_sel = n_final = 0
        scores_json = run_dir / "vision_scores.json"
        extract_json = run_dir / "vision_extract.json"
    else:
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
                    if stream.time_base:
                        seek_ts = int(ts / stream.time_base)
                    else:
                        seek_ts = int(ts * 1_000_000)
                    container.seek(seek_ts, stream=stream)
                    for frame in container.decode(video=0):
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
               "--source-url", args.source_url,
               "--final-dir", final_dir,
               "--origin-map", selected_dir / "_origin_map.json",
               "--extract-json", extract_json,
               "--scores-json", scores_json,
               "--interval", str(args.interval),
               "--img-prefix", "images",
               "--output", note_md,
               "--subject", "general",
               "--desc", args.desc or f"本地视频：{video_path.name}",
               "--duration", str(int(duration)),
               "--comment-enabled", "0",
               "--stat-view", "0", "--stat-like", "0", "--stat-favorite", "0"]
        if mind_map:
            cmd += ["--mind-map"]
        else:
            cmd += ["--no-mind-map"]
        if args.context_file:
            cmd += ["--context-file", str(args.context_file)]
        if args.source_label:
            cmd += ["--source-label", args.source_label]
        if args.source_link:
            cmd += ["--source-link", args.source_link]
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

        # 提取 Mermaid 代码块 → 渲染 SVG → 宽高比后处理
        mermaid_dir = out_dir / "mermaid"
        mermaid_dir.mkdir(parents=True, exist_ok=True)
        run([PY, SCRIPTS / "extract_mermaid.py",
             "--note", note_md, "--mermaid-dir", mermaid_dir,
             "--img-prefix", "images"],
            env=env, step="  Mermaid 代码块提取")
        if list(mermaid_dir.glob("*.mmd")):
            run([PY, SCRIPTS / "render_mermaid.py",
                 "--mermaid-dir", mermaid_dir, "--images-dir", img_dir],
                env=env, step="  Mermaid 渲染")
            # 横向链式图 → 矩形布局（6+ 节点的 flowchart LR 自动转换）
            run([PY, SCRIPTS / "rectangular_layout.py",
                 "--mermaid-dir", mermaid_dir, "--images-dir", img_dir],
                env=env, step="  横向链式图 → 矩形布局")
        if list(img_dir.glob("*.svg")):
            run([PY, SCRIPTS / "svg_padder.py", "--dir", img_dir],
                env=env, step="  SVG 宽高比后处理")

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