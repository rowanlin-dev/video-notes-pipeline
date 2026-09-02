#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站视频 -> 图文笔记 -> 知识库  一键流水线
==========================================
串起来的六步：
  1. 抽帧 + 拉官方 AI 字幕      (scripts/extract_frames.py)
  2. OCR 预筛 + 感知哈希去重     (scripts/smart_select.py)
  3. 多模态视觉打分              (scripts/score_frames_concurrent.py --mode score)
  4. 按分数 + 主题多样性自动精选  (auto_select.py)
  5. 图内文字/公式/流程提取      (score_frames_concurrent.py --mode extract)
  6. 融合字幕生成 Markdown + PDF (md_note.py / md2pdf.py)

用法：
  python run_pipeline.py BV1xx411c7mD                       # 单P / 默认当前P
  python run_pipeline.py BV1xx411c7mD --page 2 --mode fixed --interval 20
  python run_pipeline.py BV1xx411c7mD --pages all           # 多P：转全部分P
  python run_pipeline.py BV1xx411c7mD --pages 1,3,5         # 多P：指定分P列表
  python run_pipeline.py BV1xx411c7mD --pages current       # 只转当前P（默认行为）
  python run_pipeline.py BV1xx411c7mD --from-step 3         # 断点续跑

多P 交互：未显式传 --pages 且检测到视频有多个分P时，
  - 在交互终端里会主动询问「转全部 / 只转当前P(P{--page}) / 列表」；
  - 非交互（如被 Agent 调用）默认只转当前P，并在日志提示用 --pages 指定。
"""
import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = str(ROOT / "venv" / "Scripts" / "python.exe")
if not Path(PY).exists():
    PY = sys.executable
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import fetch_comments as comments_mod  # 评论区抓取（WBI，无需登录）
import note_subject  # 学科自适应：模板 / 分类 / 字数预算


# ---------------------------------------------------------------- 工具
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


FFMPEG_CANDIDATES = [
    r"C:\ProgramData\chocolatey\bin",
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
]


def ensure_ffmpeg(env):
    """ffmpeg 常见于 chocolatey 等目录但未进 PATH，这里自动补上。"""
    if shutil.which("ffmpeg"):
        return env
    for d in FFMPEG_CANDIDATES:
        if Path(d, "ffmpeg.exe").exists():
            env["PATH"] = d + os.pathsep + env.get("PATH", "")
            print(f"[env] 已将 ffmpeg 注入 PATH: {d}")
            return env
    print("[warn] 未找到 ffmpeg，抽帧步骤可能失败。"
          "安装：choco install ffmpeg  或从 https://ffmpeg.org 下载后加入 PATH")
    return env


def run(cmd, cwd=None, env=None, step=""):
    print(f"\n{'=' * 62}\n>> {step}\n{'=' * 62}")
    print("$ " + " ".join(str(c) for c in cmd[:3]) + " ...")
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env)
    if r.returncode != 0:
        print(f"\n[fail] 步骤失败：{step} (exit {r.returncode})", file=sys.stderr)
        sys.exit(r.returncode)


def safe_name(s: str, limit=60) -> str:
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s[:limit].rstrip(" .") or "untitled"


def _http_get_json(url: str, params: dict) -> dict:
    """优先 requests，缺失时回退 urllib（仅用于读 B站 view 元数据）。"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"}
    try:
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=15)
        return r.json()
    except ImportError:
        import urllib.parse
        import urllib.request
        qs = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{qs}", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json as _json
            return _json.loads(resp.read().decode("utf-8"))


def fetch_view(bvid: str) -> dict:
    """取 B站 view 接口 data（含 title / pages[]）。失败返回空 dict。"""
    try:
        return _http_get_json("https://api.bilibili.com/x/web-interface/view",
                              {"bvid": bvid}).get("data") or {}
    except Exception as e:
        print(f"[warn] 获取视频信息失败：{e}")
        return {}


def page_title(data: dict, page: int) -> str:
    """根据 view data 拼出「标题 - 分P名」（分P名与总标题相同则只用总标题）。"""
    title = data.get("title", "")
    pages = data.get("pages") or []
    if 1 <= page <= len(pages):
        part = pages[page - 1].get("part", "")
        if part and part != title:
            title = f"{title} - {part}"
    return title


def resolve_pages(bvid: str, data: dict, args) -> list:
    """解析要处理的分P列表。多P 且未指定 --pages 时交互询问，默认当前P。"""
    pages = data.get("pages") or []
    n_pages = len(pages)

    spec = (args.pages or "").strip().lower()
    if spec:
        if spec == "all":
            return list(range(1, n_pages + 1)) if n_pages else [args.page]
        if spec == "current":
            return [args.page]
        # 数字列表：1,3,5 或 "1 3 5"
        nums = sorted({int(x) for x in re.split(r"[,\s]+", spec) if x.strip().isdigit()})
        if nums:
            print(f"[pages] 按 --pages 指定处理分P：{nums}")
            return nums
        print(f"[warn] --pages 参数无法解析：{args.pages!r}，回退到当前P (P{args.page})")
        return [args.page]

    # 未指定 --pages
    if n_pages > 1:
        if sys.stdin.isatty():
            ans = input(
                f"\n[询问] 检测到该视频有 {n_pages} 个分P。"
                f"转全部还是只转当前分P(P{args.page})？\n"
                f"  输入 current(默认) / all / 数字列表如 1,3,5："
            ).strip().lower()
            if ans in ("all", "a"):
                return list(range(1, n_pages + 1))
            if ans and re.fullmatch(r"[\d,\s]+", ans):
                nums = sorted({int(x) for x in re.split(r"[,\s]+", ans) if x.strip().isdigit()})
                if nums:
                    return nums
            return [args.page]
        # 非交互：默认当前P，提示可用 --pages
        print(f"[info] 检测到 {n_pages} 个分P，但未指定 --pages，"
              f"默认只转当前P(P{args.page})。如需全部请加 --pages all")
        return [args.page]

    return [args.page]


# ---------------------------------------------------------------- 单P处理
def process_page(bvid: str, page: int, args, data: dict, comment_block: str = "", subject: str = "general"):
    """执行单个分P 的 Step1~7，目录按分P 隔离。"""
    run_dir = Path(args.runs_dir) / f"{bvid}_p{page}"
    run_dir.mkdir(parents=True, exist_ok=True)
    frames_root = run_dir
    scene_dir = run_dir / "scene"
    selected_dir = run_dir / "selected"
    final_dir = run_dir / "final"
    out_dir = run_dir / "output"
    img_dir = out_dir / "images"

    # cookie（有则带上，能拿到更高画质和官方字幕）
    for c in (ROOT / "bilibili_cookies.txt",):
        if c.exists():
            shutil.copy2(c, run_dir / "bilibili_cookies.txt")

    env = os.environ.copy()
    env["BILI_NOTES_WORKSPACE"] = str(run_dir)
    env["BILI_NOTES_FRAMES"] = str(frames_root)
    env["PYTHONIOENCODING"] = "utf-8"
    env = ensure_ffmpeg(env)

    title = args.title or page_title(data, page) or f"{bvid}_P{page}"
    desc = data.get("desc", "") or ""
    stat = data.get("stat") or {}
    duration = data.get("duration", 0) or 0
    print(f"\n{'#' * 64}\n[pipeline] {bvid} 分P {page} / 共 "
          f"{len(data.get('pages') or [page])}\n[pipeline] 标题：{title}\n"
          f"[pipeline] 学科分类：{subject}\n"
          f"[pipeline] 工作目录：{run_dir}\n{'#' * 64}")

    scores_json = run_dir / "vision_scores.json"
    extract_json = run_dir / "vision_extract.json"
    sub_txt = run_dir / f"{bvid}_p{page}_subtitles.txt"

    # ---- Step 1 抽帧 + 字幕
    if args.from_step <= 1 <= args.to_step:
        emode = "slidegap" if args.slidegap else args.mode
        cmd = [PY, SCRIPTS / "extract_frames.py", bvid,
               "--page", page, "--mode", emode,
               "--subtitle", "--workspace", run_dir, "--frames", frames_root]
        if args.mode == "fixed":
            cmd += ["--interval", args.interval]
        elif emode == "scene":
            # 操作流程类视频（PS/剪辑/代码实操）画面频繁小幅变化：
            # 阈值更低更敏感、合并窗口更短不吞相邻步骤，避免漏掉关键步骤帧
            cmd += ["--threshold", str(args.threshold), "--merge-gap", str(args.merge_gap)]
        elif emode == "slidegap":
            # PPT 翻页视频：阈值 0.1 过滤字幕闪变噪声（只留真实翻页大变化），
            # 合并窗口 1.5s 避免多页被并成一簇。绝不裁剪画面去字幕。
            cmd += ["--threshold", "0.1", "--merge-gap", "1.5"]
        # 命令行 --start 优先级最高；否则用 --skip-head；否则读 .env 的 SKIP_HEAD_SECONDS
        start_time = args.start
        if not start_time:
            skip_head = args.skip_head
            if skip_head is None:
                skip_head = int(os.getenv("SKIP_HEAD_SECONDS", "0") or 0)
            if skip_head > 0:
                start_time = f"{skip_head // 60}:{skip_head % 60:02d}"
        if start_time:
            cmd += ["--start", start_time]
        if args.end:
            cmd += ["--end", args.end]
        if args.no_video:
            cmd += ["--no-video"]
        # 广告/卖课关键词（从 .env 读取后传给抽帧脚本）
        ad_kw = os.getenv("AD_KEYWORDS", "")
        if ad_kw:
            cmd += ["--ad-keywords", ad_kw]
        ad_ctx = os.getenv("AD_CONTEXT_SECONDS", "")
        if ad_ctx:
            cmd += ["--ad-context", ad_ctx]
        run(cmd, env=env, step=f"Step 1/7  [P{page}] 抽帧 + 下载官方AI字幕")

    n_raw = len(list(scene_dir.glob("frame_*.jpg"))) if scene_dir.exists() else 0
    print(f"[pipeline] 原始帧：{n_raw}")

    # ---- Step 2 OCR 预筛 + 去重
    if not args.no_video and args.from_step <= 2 <= args.to_step:
        run([PY, SCRIPTS / "smart_select.py", scene_dir,
             "--output-dir", selected_dir, "--workspace", run_dir],
            env=env, step=f"Step 2/7  [P{page}] OCR预筛 + 感知哈希去重")

    n_sel = len(list(selected_dir.glob("frame_*.jpg"))) if (selected_dir.exists() and not args.no_video) else 0
    print(f"[pipeline] 去重后：{n_sel}")

    # ---- Step 3 视觉打分
    if not args.no_video and args.from_step <= 3 <= args.to_step:
        run([PY, SCRIPTS / "score_frames_concurrent.py",
             "--frames", selected_dir, "--output", scores_json, "--mode", "score"],
            env=env, step=f"Step 3/7  [P{page}] 多模态视觉打分")

    # ---- Step 4 自动精选
    if not args.no_video and args.from_step <= 4 <= args.to_step:
        select_cmd = [PY, ROOT / "auto_select.py",
                      "--scores", scores_json, "--selected-dir", selected_dir,
                      "--final-dir", final_dir,
                      "--min", args.min_frames, "--max", args.max_frames,
                      "--hard-max", args.hard_max_frames]
        trash_kw = os.getenv("FRAME_TRASH_KEYWORDS")
        if trash_kw:
            select_cmd += ["--trash-keywords", trash_kw]
        select_cmd += ["--min-score", os.getenv("FRAME_MIN_SCORE", "3")]
        learned_trash = os.getenv("LEARNED_TRASH_FILE") or str(ROOT / "trash_learned.json")
        select_cmd += ["--learned-trash", learned_trash]
        type_trash = os.getenv("FRAME_TYPE_TRASH", "")
        if type_trash:
            select_cmd += ["--type-trash", type_trash]
        run(select_cmd, env=env, step=f"Step 4/7  [P{page}] 按分数+主题多样性自动精选")

    # ---- Step 5 图内文字提取
    n_final = len(list(final_dir.glob("*.jpg"))) if final_dir.exists() else 0
    if args.no_video:
        print("[pipeline] --no-video：跳过全部抽帧步骤，将生成纯文字笔记")
    elif args.from_step <= 5 <= args.to_step and n_final > 0:
        try:
            run([PY, SCRIPTS / "score_frames_concurrent.py",
                 "--frames", final_dir, "--output", extract_json, "--mode", "extract"],
                env=env, step=f"Step 5/7  [P{page}] 提取图中文字/公式/流程")
        except SystemExit as e:
            # 图内文字提取是增强项：部分帧视觉调用失败（如内容过密被截断）不应中断整条流水线，
            # 缺提取的帧会在 Step 6 降级为说明文字。
            if e.code not in (0, None):
                print(f"[warn] 图内文字提取部分失败（exit {e.code}），继续生成笔记"
                      f"（缺提取的帧将降级为说明文字）")
    elif n_final == 0:
        print("[warn] 没有入选帧，跳过图内文字提取，将生成纯文字笔记")

    # ---- Step 6 生成 Markdown + PDF
    if args.from_step <= 6 <= args.to_step:
        img_dir.mkdir(parents=True, exist_ok=True)
        for f in final_dir.glob("*.jpg"):
            shutil.copy2(f, img_dir / f.name)

        note_md = out_dir / f"{safe_name(title)}.md"
        cmd = [PY, ROOT / "md_note.py",
               "--bvid", bvid, "--page", page, "--title", title,
               "--final-dir", final_dir,
               "--origin-map", selected_dir / "_origin_map.json",
               "--extract-json", extract_json,
               "--scores-json", scores_json,
               "--interval", args.interval,
               "--img-prefix", "images",
               "--output", note_md,
               "--subject", subject,
               "--desc", desc,
               "--duration", str(duration),
               "--comment-enabled", "1" if comment_block else "0",
               "--stat-view", str(stat.get("view", 0)),
               "--stat-like", str(stat.get("like", 0)),
               "--stat-favorite", str(stat.get("favorite", 0))]
        if args.segment_minutes and args.segment_minutes > 1:
            cmd += ["--segment-minutes", str(args.segment_minutes),
                    "--max-segments", str(args.max_segments)]
        if sub_txt.exists():
            cmd += ["--subtitle", sub_txt]
        # Agent 原生模式：把评论区一并写入简报，由宿主 Agent 撰写时参考
        if args.emit_brief:
            cmd += ["--emit-brief"]
            if comment_block:
                cb_path = run_dir / "_comments_block.txt"
                cb_path.write_text(comment_block, encoding="utf-8")
                cmd += ["--comment-block", str(cb_path)]
        run(cmd, env=env, step=f"Step 6/7  [P{page}] " +
            ("导出 Agent 原生模式简报" if args.emit_brief else "融合字幕生成 Markdown 笔记"))

        # Agent 原生模式：导出简报后停止，由宿主 Agent 自带模型撰写笔记
        if args.emit_brief:
            brief = note_md.with_name("_brief.md")
            print(f"\n{'=' * 62}")
            print(f"[Agent 模式] 已导出简报：{brief}")
            print(f"  请宿主 Agent 按简报撰写 {note_md}（含图文穿插），再运行：")
            print(f"    python md2pdf.py --input {note_md}")
            print(f"{'=' * 62}")
            json.dump({"bvid": bvid, "page": page, "title": title,
                       "agent_mode": True, "brief": str(brief),
                       "markdown": str(note_md), "pdf": None,
                       "images_dir": str(img_dir), "ima_status": "skipped",
                       "comments": args.comments, "comments_appended": False,
                       "raw_frames": n_raw, "selected": n_sel,
                       "final": len(list(final_dir.glob("*.jpg")))},
                      open(run_dir / "result.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            return

        # 评论区区块：追加进笔记（在转 PDF 之前，保证 PDF 含评论）
        if comment_block:
            with open(note_md, "a", encoding="utf-8") as _f:
                _f.write("\n\n" + comment_block)
            print("[pipeline] 已追加评论区区块到笔记")

        if not args.no_pdf:
            run([PY, ROOT / "md2pdf.py", "--input", note_md],
                env=env, step="Step 6b   转 PDF（供知识库入库）")

        print(f"\n{'=' * 62}")
        print(f"完成 P{page}，耗时 {time.time() - t0:.0f}s")
        print(f"  Markdown : {note_md}")
        pdf = note_md.with_suffix(".pdf")
        if pdf.exists():
            print(f"  PDF      : {pdf}")
        print(f"  配图     : {img_dir}")
        print(f"{'=' * 62}")

        # ---- Step 7 上传到 ima 知识库（可选）
        ima_status = "skipped"
        if not args.no_ima and pdf.exists():
            to_ima = ROOT / "to_ima.py"
            has_target = args.kb_id or args.kb_name or args.route or os.getenv("IMA_KB_ID")
            if has_target:
                ima_cmd = [PY, to_ima, "--pdf", str(pdf)]
                if args.route:
                    ima_cmd += ["--route", "--md", str(note_md)]
                elif args.kb_id:
                    ima_cmd += ["--kb-id", args.kb_id]
                elif args.kb_name:
                    ima_cmd += ["--kb-name", args.kb_name]
                else:
                    ima_cmd += ["--kb-id", os.getenv("IMA_KB_ID")]
                if args.folder_id and not args.route:
                    ima_cmd += ["--folder-id", args.folder_id]
                try:
                    run(ima_cmd, env=env, step=f"Step 7/7  [P{page}] 上传到 ima 知识库")
                    ima_status = "uploaded"
                except SystemExit:
                    ima_status = "failed"
                    print("[warn] ima 上传失败，MD/PDF 已生成，可单独运行 to_ima.py 重试")
            else:
                ima_status = "no-kb"
                print("[info] 未指定目标知识库（--kb-id/--kb-name/--route 或 .env 的 IMA_KB_ID），"
                      "跳过 ima 上传。\n       查看可用知识库：python to_ima.py --list-kb"
                      "\n       按内容自动归档：python run_pipeline.py <BV> --route")

        json.dump({"bvid": bvid, "page": page, "title": title,
                   "markdown": str(note_md), "pdf": str(pdf) if pdf.exists() else None,
                   "images_dir": str(img_dir), "ima_status": ima_status,
                   "comments": args.comments, "comments_appended": bool(comment_block),
                   "raw_frames": n_raw, "selected": n_sel,
                   "final": len(list(final_dir.glob("*.jpg")))},
                  open(run_dir / "result.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 主流程
def main():
    global t0
    ap = argparse.ArgumentParser(description="B站视频转图文笔记流水线")
    ap.add_argument("bvid", help="B站 BV 号")
    ap.add_argument("--page", type=int, default=1,
                    help="默认/当前分P（多P 未指定 --pages 时处理此P）")
    ap.add_argument("--pages", default=None,
                    help="多P 选择：all / current / 逗号列表如 1,3,5（默认 current）")
    ap.add_argument("--mode", choices=["scene", "fixed"], default="scene",
                    help="scene=场景切换检测(默认，适合课件/PPT)，fixed=定时抽帧")
    ap.add_argument("--interval", type=int, default=30, help="fixed 模式抽帧间隔（秒）")
    ap.add_argument("--threshold", type=float, default=0.04,
                    help="scene 模式场景变化灵敏度（越低越敏感；操作流程视频建议 0.02）")
    ap.add_argument("--merge-gap", type=float, default=5.0,
                    help="scene 模式聚类合并窗口秒数（操作流程视频建议 1.5~2，避免相邻步骤被合并）")
    ap.add_argument("--slidegap", action="store_true",
                    help="字幕感知 PPT 抽帧：截图落在两句字幕之间的空挡，字幕不遮挡 PPT（纯PPT视频推荐）。绝不裁剪画面去字幕。")
    ap.add_argument("--start", default=None, help="起始时间 MM:SS")
    ap.add_argument("--end", default=None, help="结束时间 MM:SS")
    ap.add_argument("--skip-head", type=int, default=None,
                    help="跳过片头 N 秒（去求三连/片头动画），等效 --start 0:N")
    ap.add_argument("--min-frames", type=int, default=7, help="最少精选帧数")
    ap.add_argument("--max-frames", type=int, default=12,
                    help="精选基础上限：候选帧少时取此值；操作步骤多（候选多）时按候选数×0.6 自动放宽")
    ap.add_argument("--hard-max-frames", type=int, default=40,
                    help="精选绝对上限（默认 40），防止候选极多时失控；每帧消耗 2 次视觉模型调用")
    ap.add_argument("--runs-dir", default=str(ROOT / "runs"))
    ap.add_argument("--from-step", type=int, default=1, help="从第几步开始（断点续跑）")
    ap.add_argument("--to-step", type=int, default=6)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--no-video", action="store_true",
                    help="仅下载字幕、不下载视频也不抽帧（访谈/口播类，生成纯文字笔记）")
    ap.add_argument("--segment-minutes", type=int, default=25,
                    help="长视频切块生成：每段约多少分钟（默认 25；<=1 关闭切块）")
    ap.add_argument("--max-segments", type=int, default=12,
                    help="长视频切块最大段数（默认 12）")
    ap.add_argument("--title", default=None, help="手动指定标题，跳过 API 获取")
    ap.add_argument("--no-ima", action="store_true", help="跳过上传到 ima 知识库")
    ap.add_argument("--emit-brief", action="store_true",
                    help="Agent 原生模式：生成笔记简报后停止，由宿主 Agent 自带模型撰写笔记")
    ap.add_argument("--comments", choices=["off", "list", "top", "summary"], default="off",
                    help="评论区（默认 off；学习类价值低，社会/哲学类才有参考意义）："
                         "list=评论列表 / top=高赞评论 / summary=情绪趋势+精选（LLM）")
    ap.add_argument("--kb-id", default=None, help="目标 ima 知识库 ID（也可在 .env 设 IMA_KB_ID）")
    ap.add_argument("--kb-name", default=None, help="目标 ima 知识库名称（按名称模糊匹配）")
    ap.add_argument("--folder-id", default=None, help="知识库内文件夹 ID（省略=根目录）")
    ap.add_argument("--route", action="store_true",
                    help="按笔记内容自动归档：选知识库 + 自动建/选主题文件夹")
    args = ap.parse_args()

    load_env()
    t0 = time.time()

    if not os.getenv("VISION_API_KEY"):
        print("[error] 未配置 VISION_API_KEY，请先填写 .env", file=sys.stderr)
        sys.exit(1)

    data = fetch_view(args.bvid)
    pages_to_do = resolve_pages(args.bvid, data, args)

    # 学科自适应：整视频分类一次，各分P 共用（失败回退 general）
    tk = os.getenv("TEXT_API_KEY") or os.getenv("VISION_API_KEY", "")
    tb = os.getenv("TEXT_BASE_URL") or os.getenv("VISION_BASE_URL", "")
    tm = os.getenv("TEXT_MODEL") or "glm-4-flash"
    _title = data.get("title") or args.bvid
    _desc = data.get("desc") or ""
    subject = note_subject.classify_subject(_title, _desc, "", tk, tb, tm)
    print(f"[pipeline] 学科分类：{subject}")

    # 评论区区块：按视频（bvid）抓取一次，供各分P 共用
    comment_block = ""
    if args.comments != "off":
        try:
            comment_block = comments_mod.fetch_and_format(args.bvid, args.comments)
        except Exception as e:
            print(f"[warn] 评论抓取失败，跳过：{e}", file=sys.stderr)
            comment_block = ""

    print(f"\n[pipeline] 将处理分P：{pages_to_do}  评论模式：{args.comments}")
    results = []
    for p in pages_to_do:
        try:
            process_page(args.bvid, p, args, data, comment_block, subject=subject)
            results.append((p, "ok"))
        except SystemExit as e:
            if e.code in (0, None):
                results.append((p, "ok"))
            else:
                print(f"\n[error] 分P {p} 处理失败（exit {e.code}），继续下一分P")
                results.append((p, f"failed:{e.code}"))

    print(f"\n{'=' * 62}")
    print(f"[pipeline] 全部完成，总耗时 {time.time() - t0:.0f}s")
    for p, st in results:
        print(f"  P{p}: {st}")
    print(f"{'=' * 62}")


if __name__ == "__main__":
    main()
