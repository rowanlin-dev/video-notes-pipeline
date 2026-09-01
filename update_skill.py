#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_skill.py — video-notes-pipeline 安全自动更新器

用途：
    已经把本 skill 下载到本地的「端点」（任意 AI 工具 / 机器），运行本脚本即可
    检查 GitHub 上是否有更新的版本；若有，只刷新「上游核心文件」，
    绝不触碰「本地优化文件」（.env / user_config / *.local.* / bilibili_cookies.txt 等）。

用法：
    python update_skill.py            # 发现新版本 → 备份并刷新上游文件（非交互）
    python update_skill.py --check    # 只检查，不修改任何文件
    python update_skill.py --auto     # 静默自动模式，供端点「加载时」调用（无网则仅警告并退出）

安全原则（不影响到端的本地优化）：
    1. 只覆盖 UPSTREAM_FILES 允许列表内的文件；列表外的文件一律不动。
    2. 覆盖前先把旧文件备份到 .skill_backup/<时间戳>/，可随时回滚。
    3. 本地优化文件（见 PROTECTED_PATTERNS）永远不被读取 / 写入 / 删除。
    4. 无网络或远程不可达 → 仅警告，exit 0，不影响端点正常使用。

版本号来源：version.txt（优先）；SKILL.md frontmatter 的 version: 作为回退。
"""
import argparse
import datetime
import fnmatch
import os
import re
import shutil
import sys
import urllib.request
import urllib.error

REPO = "rowanlin-dev/video-notes-pipeline"
BRANCH = "main"
HERE = os.path.dirname(os.path.abspath(__file__))

# 允许被更新的「上游核心文件」白名单。
# 新增需要分发的文件时，请同步加到这里（避免误删 / 误覆盖本地文件）。
UPSTREAM_FILES = [
    "SKILL.md",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "requirements.txt",
    "requirements-optional.txt",
    "setup_windows.bat",
    "scripts/run_pipeline.py",
    "scripts/extract_frames.py",
    "scripts/smart_select.py",
    "scripts/score_frames_concurrent.py",
    "scripts/auto_select.py",
    "scripts/md_note.py",
    "scripts/md2pdf.py",
    "scripts/asr_subtitle.py",
    "scripts/fix_subtitles.py",
    "scripts/gen_full_note.py",
    "scripts/to_ima.py",
    "scripts/learn_trash.py",
    "scripts/set_cookie.py",
    "scripts/weasyprint_pdf.py",
]

# 本地优化文件：更新器永远不碰（端点可放心在这里放自己的密钥 / 配置 / 微调）。
PROTECTED_PATTERNS = [
    ".env", ".env.*",
    "user_config*", "*.local.*", "local_overrides*",
    ".skill_backup", "__pycache__", "*.pyc",
    "runs", "output", "venv", ".venv",
    "bilibili_cookies.txt",
]

VERSION_FILE = "version.txt"


def local_version():
    p = os.path.join(HERE, VERSION_FILE)
    if os.path.exists(p):
        try:
            return open(p, encoding="utf-8").read().strip()
        except Exception:
            pass
    sp = os.path.join(HERE, "SKILL.md")
    if os.path.exists(sp):
        m = re.search(r"^version:\s*([\d.]+)", open(sp, encoding="utf-8").read(), re.M)
        if m:
            return m.group(1)
    return "0.0.0"


def version_tuple(v):
    parts = re.findall(r"\d+", v)
    nums = [int(x) for x in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "vnp-update-skill/1.1.1"})
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def remote_version():
    candidates = [
        f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{VERSION_FILE}",
        f"https://ghproxy.net/https://raw.githubusercontent.com/{REPO}/{BRANCH}/{VERSION_FILE}",
        f"https://raw.gitmirror.com/{REPO}/{BRANCH}/{VERSION_FILE}",
    ]
    for url in candidates:
        try:
            data = _http_get(url)
            if data:
                v = data.strip()
                if re.match(r"^\d+\.\d+\.\d+$", v):
                    return v, url
        except Exception:
            continue
    return None, None


def _raw_url(path):
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path}"


def _mirror_url(path):
    return f"https://ghproxy.net/https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path}"


def download_upstream(path):
    for url in (_raw_url(path), _mirror_url(path)):
        try:
            return _http_get(url)
        except Exception:
            continue
    return None


def is_protected(rel):
    name = os.path.basename(rel)
    for pat in PROTECTED_PATTERNS:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
    return False


def backup_and_write(rel, content):
    dst = os.path.join(HERE, rel)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if os.path.exists(dst):
        bak_dir = os.path.join(HERE, ".skill_backup", stamp)
        os.makedirs(bak_dir, exist_ok=True)
        shutil.copy2(dst, os.path.join(bak_dir, rel.replace("/", "_")))
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return dst


def main():
    ap = argparse.ArgumentParser(description="video-notes-pipeline 安全自动更新器")
    ap.add_argument("--check", action="store_true", help="只检查，不修改任何文件")
    ap.add_argument("--auto", action="store_true", help="静默自动模式（供端点加载时调用）")
    args = ap.parse_args()

    lv = local_version()
    rv, src = remote_version()
    if not rv:
        print("[update_skill] 无法连接 GitHub（可能无网络 / 被墙）。跳过更新，不影响使用。")
        return 0
    if version_tuple(rv) <= version_tuple(lv):
        print(f"[update_skill] 已是最新（本地 {lv} / 远程 {rv}）。")
        return 0

    print(f"[update_skill] 发现新版本：本地 {lv} -> 远程 {rv}（来源 {src}）")
    if args.check:
        print("[update_skill] --check 模式：未修改文件。去掉 --check 再运行以应用更新。")
        return 0

    updated, skipped = [], []
    for rel in UPSTREAM_FILES:
        if is_protected(rel):
            skipped.append(rel)
            continue
        content = download_upstream(rel)
        if content is None:
            skipped.append(rel + " (下载失败)")
            continue
        backup_and_write(rel, content)
        updated.append(rel)

    # 本地 version.txt 同步为远程版本（它不在 UPSTREAM_FILES 内，但应当更新）
    backup_and_write(VERSION_FILE, rv + "\n")

    print(f"[update_skill] 已刷新 {len(updated)} 个上游文件；"
          f"本地优化文件（.env / user_config / *.local.* 等）原样保留，未被触碰。")
    if skipped:
        print(f"[update_skill] 跳过：{', '.join(skipped)}")
    print(f"[update_skill] 被覆盖的旧文件备份在 .skill_backup/ 。版本 {lv} -> {rv}。")

    # 若端点的 SKILL.md 想自动触发检查，可在此输出提示（不强制）
    print("[update_skill] 下次端点加载时，可运行 `python update_skill.py --auto` 静默保新。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
