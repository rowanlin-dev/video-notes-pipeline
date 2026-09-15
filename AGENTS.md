# Bilibili Video Notes（工具入口 · v1.3.0）

从 B 站教育/讲课视频一键生成带截图、可点击时间戳的 **Markdown + PDF** 图文笔记，可选择性归档进 ima 知识库。

> 当前版本 **v1.3.0**，与 `SKILL.md` 保持同步；改 SKILL.md 时本文件一并更新。端点自动更新器（`update_skill.py`）白名单已含本文件。

完整说明见 **SKILL.md**（本仓库的主要交付物）。本文是给 AI 代理/协作者的快速上手。

## 工作流程

由 `run_pipeline.py` 串起七步（失败可用 `--from-step` 断点续跑）：

1. 下载视频 + 官方 AI 字幕（`scripts/extract_frames.py`）
2. OCR 预筛 + 感知哈希去重（`scripts/smart_select.py`）
3. 多模态视觉打分（`scripts/score_frames_concurrent.py --mode score`）
4. 按分数 + 主题多样性自动精选（`auto_select.py`）
5. 图内文字/公式/流程提取（`score_frames_concurrent.py --mode extract`）
6. 融合字幕生成 Markdown + PDF（`md_note.py` / `md2pdf.py`）
7. （可选）上传 ima 知识库（`to_ima.py`）

## 使用方法

```bash
# 一键跑（默认当前 P）
python run_pipeline.py BV1xx411c7mD

# 操作类视频（代码实操/剪辑）：低阈值
python run_pipeline.py BV1hD42137sx --threshold 0.02 --merge-gap 1.5

# 断点续跑
python run_pipeline.py BV1xx411c7mD --from-step 4
```

输出在 `runs/<BV>_p<N>/output/`。更多参数见 SKILL.md。

## 本地视频

当用户提供**本地视频文件**（非 B 站链接）并要求做笔记时，用 `run_local_pipeline.py` 一键跑（无需 Cookie / 网络）：

```bash
python run_local_pipeline.py --video /path/to/video.mp4
python run_local_pipeline.py --video /path/to/video.mp4 --title "自定义标题"
python run_local_pipeline.py --video /path/to/video.mp4 --segment-minutes 25   # 长视频切块
```

流程：提取音频 → 本地 ASR（faster-whisper）转文字 → 定时抽帧（PyAV）→ OCR 去重 → 视觉打分 → 自动精选 → 生成 MD + PDF →（可选）入 ima。
与 B 站差异：默认禁用自进化黑名单、哈希去重阈值 20、输出在 `runs/local_<标题>_p1/output/`。
依赖：额外 `pip install av`。

**脑图图文模式**：时长 ≥30min 自动启用（跳过抽帧/OCR/打分/精选/文字提取），只做 ASR + 纯文本笔记 + Mermaid 图，避免大量截图文件（100+MB/上千文件）。可用 `--brain-map` 强制启用，或 `--no-brain-map` 强制关闭。短视频不受影响。

**Mermaid 图后处理流水线**：`render_mermaid.py` → `rectangular_layout.py`（横向链式图→矩形布局）→ `svg_padder.py`（宽高比调整）。`rectangular_layout.py` 自动检测 6+ 节点的 `flowchart LR` 线性链，转换为矩形布局（上下各 2 个、左右均匀分布），避免横向过长。

**长视频并行 ASR**：时长 ≥30min 自动切分 + 多进程并行（`scripts/run_asr_parallel.py`），合并结果同单进程；可用 `--parallel-asr` / `--no-parallel-asr` 覆盖，`--asr-workers N`（默认 auto）、`--asr-chunk-minutes M`（默认 auto）、`--asr-model-size SIZE`（默认 auto）调参。**内存自适应**：自动检测 CPU 核数和可用内存，选择模型尺寸（tiny/base/small）、并行进程数和分块大小，保留 4GB 系统余量。**自动 VAD 检测**：默认先跑第一块计算字幕密度，密集（>8条/分钟）→ 无VAD快速模式，稀疏 → 保持VAD。引擎变体：`asr_subtitle.py`（VAD 默认）/ `asr_fast.py`（关 VAD 快转）/ `asr_ct2.py`（直连 CTranslate2 绕 MKL）/ `run_asr_direct.py`（单进程无分块，调试/短音频）。详见 SKILL.md「ASR 音频转文本」节。

## Agent 原生模式（免外部 LLM）

若宿主 Agent 自带模型，可省掉 skill 内置 LLM：在命令后加 `--emit-brief`，脚本导出 `output/_brief.md`（素材 + 写作规范）后停下；Agent 按简报写 `note.md`，再 `python md2pdf.py --input <note.md>` 渲染。无需 `TEXT_API_KEY`。默认行为不变。详见 SKILL.md。

## 耗时预估

开始处理前**先按视频时长告知用户预估耗时**（经验公式，v1.0.2，详见 SKILL.md）：

> **处理耗时 ≈ 5 + 0.56 × 视频分钟数**（分钟；下限约 6 分钟）

| 视频时长 | 预估处理耗时 | 主要时间去向 |
|---------|-------------|-------------|
| ≤5 分钟 | 约 6-8 分钟 | 固定开销为主（下载/抽帧/笔记/PDF/入库） |
| 10 分钟 | 约 10-12 分钟 | 下载 ~1min + ASR 转写 + 抽帧打分 |
| 30 分钟 | 约 20-25 分钟 | ASR 转写是大头（约 0.5-0.7×音频时长） |
| 60 分钟 | 约 35-40 分钟 | 建议 `--segment-minutes 25` 切块 |

实测样本：3.6 分钟→约 6 分钟；10 分钟→约 12 分钟；33 分钟→约 23 分钟。

## 脑图模式（长视频专用）

>30 分钟的长视频或用户明确要求时，切换为**脑图图文模式**，不依赖截图/OCR/视觉打分。

流程：ASR 字幕 → 写笔记（标题作为时间节点索引）→ 评估需补充脑图的内容 → 生成 Mermaid 图 → 渲染为 SVG → 横向链式图转矩形布局 → SVG 宽高比后处理 → 嵌入 Markdown → PDF

### 脑图生成规则

| 内容类型 | 脑图类型 | 说明 |
|---------|---------|------|
| 全局结构 / 多分支大纲 | `mindmap` | 整视频大纲，**放全文开头（# 标题下方，所有小节之前）**。**禁用 `flowchart` 替代** |
| 流程步骤 | `flowchart LR` / `flowchart TD` | Vibe Coding SOP、STAR-L 法则 |
| 时间演进 | `timeline` | AI 编程三阶段 |
| 系统架构 | `flowchart TD`（含 subgraph） | 全站架构设计 |
| 能力层级 | `flowchart LR` | 开发者能力层级 |
| **分类/集合展示** | `flowchart TD` + 子图 `direction LR` | 类型系统、功能模块、技术栈分类，子图内 `---` 并列，子图间 `-->` 演进 |
| 时间线图 | 手写 SVG Gantt | 1小时交付 SOP |

> **重要**：全局大纲/多分支结构必须使用 `mindmap` 语法（树形发散），不要用 `flowchart` 替代。`flowchart` 的有向箭头和方框样式不适合展现多分支聚合结构，效果不如 mindmap 的树形发散美观。
>
> **分类/集合图布局关键**：`flowchart TD` 父图中，子图内即使写了 `direction LR`，如果节点之间没有连线（`---`/`-->`），仍会堆叠成纵向。必须用连线连接节点，`direction LR` 才能生效。子图内并列元素用 `---`（无箭头），子图间用 `-->`（有箭头）。详见 SKILL.md。
>
> **Mermaid 代码块放置规范**：全局大纲 mindmap 放在文章最开头（`#` 标题下方，所有小节之前）；各小节 mindmap 放在该小节标题（`##`/`###`）下方，作为该节概述；Mermaid 代码块必须紧跟标题之后，不要堆在段落末尾或文末。prompt 配置在 `md_note.py` 的 `_NO_FRAME_NOTE` 常量中。

**不生成脑图的情况**：纯文字概念说明、简单列举、无流程/层级/架构/时间线关系的段落。

### 渲染工具

```bash
# 从 .mmd 文件渲染为 SVG（mermaid.ink API）
python scripts/render_mermaid.py --mermaid-dir runs/xxx/output/mermaid

# API 失败时：打开 templates/mermaid-render.html 在浏览器中查看
# 加载 .mmd 文件 → 渲染 → 批量导出 SVG

# 甘特图：根据 JSON 配置动态生成 SVG（自动计算标签区宽度）
python scripts/generate_gantt.py --config gantt_config.json --output images/gantt.svg
```

## 环境注意

- `pip install -r scripts/requirements.txt`（含 faster-whisper / weasyprint 兜底依赖）
- 需要系统 `ffmpeg`
- `.env`（API key）与 `bilibili_cookies.txt`（SESSDATA）不进仓库，复制 `.env.example` / `bilibili_cookies.txt.example` 填写
- `models/`、`fonts/`、`runs/` 为本地产物，已 gitignore

## 常见坑

- B站 412 风控：playurl API + `curl --http1.1` 绕过（见 SKILL.md）
- 官方 AI 字幕串台/缺失：本地语音转文字（ASR，自动语音识别）兜底——`scripts/asr_subtitle.py` 用 faster-whisper 把音轨转成字幕
- PDF 中文豆腐块：weasyprint + TTF 字体（`scripts/gen_full_note.py`）
- 智谱 429：`--workers 2 --resume` 低并发重打
