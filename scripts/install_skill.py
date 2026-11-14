#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本 skill 注册到 Agent 的用户级 skills 目录（WorkBuddy / Claude Code / 自定义）。

只装到仓库目录是不够的：Agent 只扫描自己的 skills 目录，看不到仓库里的 SKILL.md。
本脚本默认建立目录链接（Windows 用目录联接 Junction，macOS/Linux 用 symlink），
仓库更新后 Agent 直接读到最新内容，不用重复注册；链接不可用时自动退回复制模式。
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SKILL_NAME = "video-notes-pipeline"
REPO_ROOT = Path(__file__).resolve().parent.parent

# 复制模式要排除的目录/文件：大体积、含隐私、与 skill 运行无关
COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "venv", "runs", "models", "docs", "__pycache__", "*.pyc",
    ".env", "bilibili_cookies.txt", "exports", "_smoketest", "_deliver_anim",
    ".trae-html-share-packages", ".screenshots",
)

# (显示名, skills 目录)；仅当上一级目录存在（说明装了该 Agent）时才注册
AGENTS = [
    ("WorkBuddy", Path.home() / ".workbuddy" / "skills"),
    ("Claude Code", Path.home() / ".claude" / "skills"),
]


def read_version() -> str:
    try:
        return (REPO_ROOT / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def is_link(path: Path) -> bool:
    """symlink 与 Windows 目录联接都算链接。"""
    if path.is_symlink():
        return True
    try:
        return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def link_target(path: Path) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return ""


def run(cmd: list[str]) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def make_link(src: Path, dst: Path) -> bool:
    """优先目录联接/symlink；都失败返回 False，由调用方退回复制。"""
    if os.name == "nt":
        # Junction 不需要管理员权限，且对绝大多数程序透明
        ps = (
            "New-Item -ItemType Junction -Path '{}' -Target '{}' | Out-Null"
        ).format(dst, src)
        if run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]) and dst.exists():
            return True
        return False
    try:
        os.symlink(src, dst, target_is_directory=True)
        return True
    except OSError:
        return False


def backup_existing(dst: Path) -> Path | None:
    """已存在的是旧副本（例如 v1.1.0 手抄版）时改名备份，不直接删。

    备份必须移出 skills 目录：Agent 会扫描该目录下所有含 SKILL.md 的子目录，
    留在里面会被当成第二个同名 skill。
    """
    bak_dir = dst.parent.parent / "skill-backups"
    bak = bak_dir / "{}.bak.{}".format(dst.name, datetime.now().strftime("%Y%m%d-%H%M%S"))
    for _ in range(3):
        try:
            bak_dir.mkdir(parents=True, exist_ok=True)
            dst.rename(bak)
            return bak
        except OSError:
            time.sleep(0.4)
    return None


def install(dest_root: Path, copy_mode: bool) -> bool:
    dst = dest_root / SKILL_NAME
    dest_root.mkdir(parents=True, exist_ok=True)

    if dst.exists() or is_link(dst):
        if is_link(dst) and link_target(dst) == str(REPO_ROOT):
            print("  = 已注册且指向当前仓库，跳过：{}".format(dst))
            return True
        bak = backup_existing(dst)
        if bak is None:
            print("  × 已存在 {}，且无法改名备份（可能被 Agent 占用），请先关闭 Agent 再试".format(dst))
            return False
        print("  ! 已存在旧版本，备份为：{}".format(bak.name))

    ok = False
    if not copy_mode:
        ok = make_link(REPO_ROOT, dst)
        if not ok:
            print("  ! 目录链接创建失败（权限/文件系统限制），改用复制模式")

    if not ok:
        try:
            shutil.copytree(REPO_ROOT, dst, ignore=COPY_IGNORE)
            ok = True
        except OSError as exc:
            print("  × 复制失败：{}".format(exc))
            return False

    skill_md = dst / "SKILL.md"
    if not skill_md.is_file():
        print("  × 注册后找不到 SKILL.md：{}".format(skill_md))
        return False
    kind = "链接" if is_link(dst) else "复制"
    print("  √ [{1}] {0}  (v{2})".format(dst, kind, read_version()))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="把 video-notes-pipeline 注册到 Agent 的 skills 目录")
    ap.add_argument("--dest", action="append", metavar="DIR",
                    help="自定义 skills 父目录，可多次指定（用于其他 Agent）")
    ap.add_argument("--copy", action="store_true", help="强制复制而不是建链接")
    ap.add_argument("--list", action="store_true", help="只打印检测结果，不做任何改动")
    args = ap.parse_args()

    if args.dest:
        targets = [(d, Path(d).expanduser()) for d in args.dest]
    else:
        targets = [(name, p) for name, p in AGENTS if p.parent.exists()]

    print("仓库：{}".format(REPO_ROOT))
    if not targets:
        print("× 未检测到 WorkBuddy / Claude Code 的 skills 目录。")
        print("  可用 --dest 指定，例如：python scripts/install_skill.py --dest ~/.codex/skills")
        return 1
    if args.list:
        for name, p in targets:
            print("  - {}：{}".format(name, p))
        return 0

    failed = 0
    for name, root in targets:
        print("[{}] {}".format(name, root))
        if not install(root, args.copy):
            failed += 1

    if failed == 0:
        print("\n完成。请重启 Agent（WorkBuddy 重启后重新扫描 skills 目录），")
        print("之后直接在对话框说「总结这个 B站视频」即可触发本 skill。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
