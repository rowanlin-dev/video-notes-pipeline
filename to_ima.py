#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把生成的图文笔记 PDF 上传到 ima 知识库（自动入库最后一步）
=========================================================
两种入库方式：

1) 显式指定（默认，最可控）
   python to_ima.py --pdf xxx.pdf --kb-id <id>
   python to_ima.py --pdf xxx.pdf --kb-name "全栈开发知识库" --folder-id folder_xxx

2) 按内容自动归档（--route）
   用免费文本模型（glm-4-flash）读笔记标题+开头，判断该归入哪个已有知识库，
   并按主题自动建/选文件夹，再上传。适合批量无人值守。
   python to_ima.py --pdf xxx.pdf --md xxx.md --route
   （--md 省略时自动找同名的 .md）

链路（与 ima-skills knowledge-base 模块一致）：
  preflight-check.cjs → check_repeated_names → create_media
  → cos-upload.cjs → add_knowledge

其它：
  --verify   只验证上传链路（跑到 COS 上传为止，不调 add_knowledge，不污染知识库）
  --list-kb  列出可添加的知识库
"""
import os
import re
import sys
import json
import shutil
import argparse
import subprocess
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------- 路径定位
def find_node() -> str:
    managed = r"C:\Users\12629\.workbuddy\binaries\node\versions\22.22.2\node.exe"
    if Path(managed).exists():
        return managed
    on_path = shutil.which("node")
    if on_path:
        return on_path
    raise RuntimeError("找不到 node，请安装 Node.js 或检查路径")


def find_ima_skill_dir() -> Path:
    candidates = [
        os.getenv("IMA_SKILL_DIR"),
        r"C:\Users\12629\.workbuddy\skills\ima-skills",
        Path.home() / ".workbuddy/skills/ima-skills",
        Path.home() / ".config/workbuddy/skills/ima-skills",
    ]
    for c in candidates:
        if c and Path(c).exists() and (Path(c) / "ima_api.cjs").exists():
            return Path(c)
    raise RuntimeError("找不到 ima-skills（请确认已安装 ima-skills skill）")


def load_env():
    """把脚本同目录的 .env 读进进程环境（不覆盖已有变量）。"""
    f = Path(__file__).resolve().parent / ".env"
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


# ---------------------------------------------------------------- 调用封装
def run_node(node: str, script: Path, args: list, step: str) -> str:
    cmd = [node, str(script), *args]
    print(f"\n>> {step}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"[fail] {step} (exit {r.returncode})")
        if r.stderr.strip():
            print(r.stderr.strip())
        if r.stdout.strip():
            print(r.stdout.strip())
        sys.exit(r.returncode)
    return r.stdout.strip()


def ima_api(node: str, skill_dir: Path, api_path: str, body: dict, step: str) -> dict:
    """调用 ima_api.cjs，返回解析后的 data（出错直接退出）。"""
    script = skill_dir / "ima_api.cjs"
    cmd = [node, str(script), api_path, json.dumps(body, ensure_ascii=False)]
    print(f"\n>> {step}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"[fail] {step} (exit {r.returncode})")
        print((r.stderr or r.stdout).strip())
        sys.exit(r.returncode)
    try:
        resp = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"[fail] {step}：响应不是合法 JSON")
        print(r.stdout[:500])
        sys.exit(1)
    if resp.get("code", 0) != 0:
        print(f"[fail] {step}：{resp.get('msg')}")
        sys.exit(1)
    return resp.get("data", {})


# ---------------------------------------------------------------- 子流程
def preflight(node: str, skill_dir: Path, pdf: Path) -> dict:
    script = skill_dir / "knowledge-base" / "scripts" / "preflight-check.cjs"
    out = run_node(node, script, ["--file", str(pdf)], "preflight 类型/大小检查")
    info = json.loads(out)
    if not info.get("pass"):
        print(f"[reject] 文件被拒绝：{info.get('reason')}")
        sys.exit(1)
    return info


def check_repeated(node, skill_dir, file_name, media_type, kb_id, folder_id):
    body = {
        "params": [{"name": file_name, "media_type": media_type}],
        "knowledge_base_id": kb_id,
    }
    if folder_id:
        body["folder_id"] = folder_id
    data = ima_api(node, skill_dir, "openapi/wiki/v1/check_repeated_names",
                   body, "检查同名文件")
    for item in data.get("results", []):
        if item.get("name") == file_name and item.get("is_repeated"):
            return True
    return False


def create_media(node, skill_dir, pf, kb_id, folder_id):
    body = {
        "file_name": pf["file_name"],
        "file_size": pf["file_size"],
        "content_type": pf["content_type"],
        "knowledge_base_id": kb_id,
        "file_ext": pf["file_ext"],
    }
    if folder_id:
        body["folder_id"] = folder_id
    data = ima_api(node, skill_dir, "openapi/wiki/v1/create_media",
                   body, "创建媒体（获取 COS 凭证）")
    cred = data.get("cos_credential", {})
    if not cred.get("cos_key"):
        print("[fail] create_media 未返回 cos_credential", file=sys.stderr)
        sys.exit(1)
    return data.get("media_id"), cred


def cos_upload(node, skill_dir, pdf, cred, content_type):
    script = skill_dir / "knowledge-base" / "scripts" / "cos-upload.cjs"
    args = [
        "--file", str(pdf),
        "--secret-id", cred["secret_id"],
        "--secret-key", cred["secret_key"],
        "--token", cred["token"],
        "--bucket", cred["bucket_name"],
        "--region", cred["region"],
        "--cos-key", cred["cos_key"],
        "--content-type", content_type,
        "--start-time", str(cred.get("start_time", "")),
        "--expired-time", str(cred.get("expired_time", "")),
        "--timeout", "300000",
    ]
    run_node(node, script, args, "COS 上传文件")


def add_knowledge(node, skill_dir, pf, media_id, cred, media_type, kb_id, folder_id):
    body = {
        "media_type": media_type,
        "media_id": media_id,
        "title": pf["file_name"],          # GATE 2：title 必须等于 file_name
        "knowledge_base_id": kb_id,
        "file_info": {
            "cos_key": cred["cos_key"],
            "file_size": pf["file_size"],
            "file_name": pf["file_name"],
        },
    }
    if folder_id:
        body["folder_id"] = folder_id
    ima_api(node, skill_dir, "openapi/wiki/v1/add_knowledge", body, "添加到知识库")
    return True


def resolve_kb(node: str, skill_dir: Path, kb_id: str, kb_name: str) -> str:
    """返回知识库 id；kb_name 时通过 get_addable_knowledge_base_list 模糊匹配。"""
    if kb_id:
        return kb_id
    if not kb_name:
        print("[error] 未指定目标知识库，请用 --kb-id / --kb-name / --route，"
              "或 --list-kb 查看。", file=sys.stderr)
        sys.exit(1)
    data = ima_api(node, skill_dir, "openapi/wiki/v1/get_addable_knowledge_base_list",
                   {"cursor": "", "limit": 50}, "查询可添加的知识库")
    found = None
    for kb in data.get("addable_knowledge_base_list", []):
        if kb.get("name") == kb_name or kb_name in kb.get("name", ""):
            found = kb["id"]
            break
    if not found:
        names = "、".join(k.get("name", "?") for k in data.get("addable_knowledge_base_list", []))
        print(f"[error] 未找到名为「{kb_name}」的知识库。可选：{names}", file=sys.stderr)
        sys.exit(1)
    return found


def resolve_or_create_folder(node, skill_dir, kb_id, folder_name, create=True):
    """在知识库里按名找文件夹；找不到就新建（根级）。返回 folder_id 或 None。
    create=False 时只查不建（用于 --verify，避免留下空文件夹副作用）。"""
    if not folder_name:
        return None
    # 1) 先查是否已有同名文件夹
    data = ima_api(node, skill_dir, "openapi/wiki/v1/search_knowledge",
                   {"query": folder_name, "knowledge_base_id": kb_id, "cursor": ""},
                   f"查找文件夹「{folder_name}」")
    for item in data.get("info_list", []):
        if str(item.get("media_id", "")).startswith("folder_") and item.get("title") == folder_name:
            print(f"[ok] 复用已有文件夹「{folder_name}」")
            return item["media_id"]
    # 2) 没有则新建（根级，parent = kb_id）
    if not create:
        print(f"[verify] 跳过新建文件夹「{folder_name}」（--verify 模式不创建）")
        return None
    data = ima_api(node, skill_dir, "openapi/wiki/v1/create_folder",
                   {"knowledge_base_id": kb_id, "parent_folder_id": kb_id, "name": folder_name},
                   f"新建文件夹「{folder_name}」")
    fid = data.get("media_id")
    if not fid:
        print("[warn] 创建文件夹失败，将上传到根目录")
        return None
    return fid


# ---------------------------------------------------------------- 内容归档（--route）
CLASSIFY_PROMPT = """你是一个知识库归档助手。下面是一篇从视频自动生成的图文笔记。
请判断它最应该归入哪个已有知识库，并给出一个合适的「主题文件夹」名称。

可选知识库（必须从中严格选一个，绝不能新建知识库）：
{kb_list}

笔记标题：
{title}

笔记大纲（## 标题）：
{outline}

笔记开头：
{head}

要求：
- kb 字段必须严格等于上面列表中的某一个名字（一字不差）。
- folder 字段填一个 2-6 字的中文主题文件夹名，反映这篇笔记的核心技术主题。
  例如：多租户、SaaS架构、Vue3、React、Node后端、微服务、数据库、AI工具、提示词、微信开发。
  如果笔记主题非常宽泛、无法用一个明确技术主题概括，才允许 folder 填空字符串 ""。
- reason 用一句话说明归类理由。

只输出一个 JSON 对象，不要代码块、不要任何解释文字：
{{"kb": "上面列表里的某个名字", "folder": "主题文件夹名或空串", "reason": "理由"}}"""


def _normalize_keys(d: dict) -> dict:
    alias = {"知识库": "kb", "库": "kb", "文件夹": "folder", "目录": "folder",
             "理由": "reason", "原因": "reason"}
    out = {}
    for k, v in d.items():
        ek = alias.get(k, k)
        if ek not in out:
            out[ek] = v
    return out


def call_llm(prompt: str, api_key: str, base_url: str, model: str, timeout: int = 120) -> str:
    import urllib.request
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}",
                  "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def classify(md_path: Path, kb_names: list, api_key: str, base_url: str, model: str):
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    lines = [l for l in text.splitlines() if l.strip()]
    title = next((l.lstrip("#").strip() for l in lines if l.startswith("#")), lines[0] if lines else "(无标题)")
    # 提取大纲：所有 ## / ### 标题，最多 15 行
    outline_lines = []
    for l in lines:
        if l.startswith("## ") or l.startswith("### "):
            outline_lines.append(l.lstrip("#").strip())
        if len(outline_lines) >= 15:
            break
    outline = "\n".join(f"- {x}" for x in outline_lines) or "（无明确大纲）"
    head = text[:2000]
    kb_list = "\n".join(f"- {n}" for n in kb_names)
    prompt = CLASSIFY_PROMPT.format(kb_list=kb_list, title=title, outline=outline, head=head)
    raw = call_llm(prompt, api_key, base_url, model)
    raw = re.sub(r"^```[a-zA-Z]*\n", "", raw.strip())
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    try:
        obj = _normalize_keys(json.loads(raw))
    except json.JSONDecodeError:
        print(f"[warn] 归档模型返回无法解析：{raw[:200]}，将归入第一个知识库")
        return kb_names[0], "", "解析失败，回退"
    kb = obj.get("kb") or ""
    folder = (obj.get("folder") or "").strip()
    # 清理 folder：去掉书名号、括号、多余空格，限制长度
    folder = re.sub(r"[《》【】\[\]()（）]", "", folder).strip()
    folder = folder.replace(" ", "").replace("、", "")
    if len(folder) > 12:
        folder = folder[:12]
    # 校验 kb 必须在列表内，否则取最相近的
    if kb not in kb_names:
        kb = next((n for n in kb_names if n in kb or kb in n), kb_names[0])
    return kb, folder, obj.get("reason", "")


# ---------------------------------------------------------------- 核心上传
def upload_to_kb(node, skill_dir, pdf, kb_id, folder_id, verify):
    pf = preflight(node, skill_dir, pdf)
    print(f"[ok] {pf['file_name']} | media_type={pf['media_type']} "
          f"| {pf['file_size']} 字节 | {pf['content_type']}")
    if check_repeated(node, skill_dir, pf["file_name"], pf["media_type"], kb_id, folder_id):
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d%H%M%S")
        stem, ext = os.path.splitext(pf["file_name"])
        pf["file_name"] = f"{stem}_{ts}{ext}"
        print(f"[warn] 知识库已存在同名文件，已重命名为：{pf['file_name']}")
    media_id, cred = create_media(node, skill_dir, pf, kb_id, folder_id)
    print(f"[ok] media_id={media_id}")
    cos_upload(node, skill_dir, pdf, cred, pf["content_type"])
    if verify:
        print("\n[verify] 链路验证完成（已上传到 COS，但未调 add_knowledge，知识库不会留下条目）。"
              "去掉 --verify 即可正式入库。")
        return
    add_knowledge(node, skill_dir, pf, media_id, cred, pf["media_type"], kb_id, folder_id)
    print(f"\n[done] 已添加到知识库 ✅  ({pf['file_name']})")


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="上传图文笔记 PDF 到 ima 知识库")
    ap.add_argument("--pdf", help="要上传的 PDF 路径")
    ap.add_argument("--md", help="对应的 Markdown 笔记（--route 归档分类用；省略则找同名 .md）")
    ap.add_argument("--kb-id", help="目标知识库 ID（显式指定，优先于 --route）")
    ap.add_argument("--kb-name", help="目标知识库名称（按名称模糊匹配）")
    ap.add_argument("--folder-id", help="知识库内文件夹 ID（显式指定时用）")
    ap.add_argument("--route", action="store_true",
                    help="按笔记内容自动归档：选知识库 + 自动建/选主题文件夹")
    ap.add_argument("--verify", action="store_true",
                    help="只验证上传链路（preflight+重名+create_media+COS），不调 add_knowledge")
    ap.add_argument("--list-kb", action="store_true", help="列出可添加的知识库后退出")
    args = ap.parse_args()

    load_env()
    node = find_node()
    skill_dir = find_ima_skill_dir()
    print(f"[ima] skill dir: {skill_dir}")
    print(f"[ima] node: {node}")

    # 仅列出知识库
    if args.list_kb:
        data = ima_api(node, skill_dir, "openapi/wiki/v1/get_addable_knowledge_base_list",
                       {"cursor": "", "limit": 50}, "查询可添加的知识库")
        kbs = data.get("addable_knowledge_base_list", [])
        print(f"\n可添加的知识库（共 {len(kbs)} 个）：")
        for i, kb in enumerate(kbs, 1):
            print(f"  {i}. {kb.get('name')}   (id={kb.get('id')})")
        return

    if not args.pdf:
        print("[error] 请提供 --pdf（要上传的 PDF 路径）", file=sys.stderr)
        sys.exit(1)
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"[error] 文件不存在：{pdf}", file=sys.stderr)
        sys.exit(1)

    # ---- 决定目标知识库 + 文件夹
    kb_id = None
    folder_id = None

    if args.kb_id or args.kb_name:
        kb_id = resolve_kb(node, skill_dir, args.kb_id, args.kb_name)
        folder_id = args.folder_id
        print(f"[target] 显式指定知识库 id={kb_id}" + (f" 文件夹={folder_id}" if folder_id else ""))

    elif args.route:
        if not args.md:
            args.md = pdf.with_suffix(".md")
        md = Path(args.md)
        if not md.exists():
            print(f"[error] --route 需要笔记文本，找不到：{md}", file=sys.stderr)
            sys.exit(1)
        data = ima_api(node, skill_dir, "openapi/wiki/v1/get_addable_knowledge_base_list",
                       {"cursor": "", "limit": 50}, "获取知识库列表用于归档")
        kbs = data.get("addable_knowledge_base_list", [])
        if not kbs:
            print("[error] 没有可添加的知识库", file=sys.stderr)
            sys.exit(1)
        kb_names = [kb["name"] for kb in kbs]
        kb_id_map = {kb["name"]: kb["id"] for kb in kbs}
        api_key = os.getenv("TEXT_API_KEY") or os.getenv("VISION_API_KEY", "")
        base_url = os.getenv("TEXT_BASE_URL") or os.getenv("VISION_BASE_URL",
                                                           "https://open.bigmodel.cn/api/paas/v4/")
        model = os.getenv("TEXT_MODEL", "glm-4-flash")
        if not api_key:
            print("[error] 缺少 API Key（.env 里 TEXT_API_KEY / VISION_API_KEY），无法做内容归档",
                  file=sys.stderr)
            sys.exit(1)
        kb_name, folder_name, reason = classify(md, kb_names, api_key, base_url, model)
        kb_id = kb_id_map.get(kb_name, kbs[0]["id"])
        print(f"[route] 归档判断：知识库「{kb_name}」 / 主题文件夹「{folder_name or '根目录'}」— {reason}")
        if folder_name:
            folder_id = resolve_or_create_folder(node, skill_dir, kb_id, folder_name, create=not args.verify)

    else:
        kb_id = os.getenv("IMA_KB_ID")
        if not kb_id:
            print("[info] 未指定目标知识库（--kb-id/--kb-name/--route 或 .env 的 IMA_KB_ID），"
                  "跳过 ima 上传。\n       --list-kb 查看可用知识库；--route 按内容自动归档。")
            return
        print(f"[target] 使用 .env 默认知识库 id={kb_id}")

    # ---- 上传
    upload_to_kb(node, skill_dir, pdf, kb_id, folder_id, args.verify)


if __name__ == "__main__":
    main()
