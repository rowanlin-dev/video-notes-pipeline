---
name: bilibili-video-notes
description: "从 B 站教育/讲课视频一键生成带截图、可点击时间戳的 Markdown + PDF 图文笔记，可选归档进 ima 知识库。下载视频+字幕→场景检测抽帧→OCR去重→AI视觉打分→自动精选→提取图中内容→融合生成 MD/PDF→(可选)入 ima。"
tags: [bilibili, video, notes, OCR, vision, subtitles, markdown, pdf, ima]
triggers:
  - bilibili视频笔记
  - 视频笔记
  - 从视频做笔记
  - video notes
  - 把b站视频做成笔记
---

# Bilibili Video Notes

从 B 站教育/讲课视频一键生成带截图、可点击时间戳的 **Markdown + PDF** 图文笔记，可选择性一键归档进 ima 知识库。

> 全流程模型免费档即可跑（智谱 GLM-4V-Flash 识图 / GLM-4-Flash 写正文，长文推荐 deepseek-chat）。

## 工作流程

由 `run_pipeline.py` 串起六步（每步失败不影响后续，断点可续跑）：

1. 下载视频 + 官方 AI 字幕（`scripts/extract_frames.py`）
2. OCR 预筛 + 感知哈希去重（`scripts/smart_select.py`）
3. 多模态视觉打分（`scripts/score_frames_concurrent.py --mode score`）
4. 按分数 + 主题多样性**自动精选**（`auto_select.py`，无需人工挑选）
5. 图内文字/公式/流程提取（`score_frames_concurrent.py --mode extract`）
6. 融合字幕生成 **Markdown + PDF**（`md_note.py` / `md2pdf.py`）
7. （可选）上传到 ima 知识库（`to_ima.py`）

## 安装

```bash
git clone https://github.com/rowanlin-dev/video-notes-pipeline.git
cd video-notes-pipeline
pip install -r scripts/requirements.txt
```

系统需安装 `ffmpeg`（抽帧依赖）：

- Windows：`choco install ffmpeg` 或从 https://ffmpeg.org 下载后把 `bin` 加入 PATH
- macOS：`brew install ffmpeg`
- Ubuntu/Debian：`sudo apt-get install ffmpeg`

## 配置

```bash
cp .env.example .env
```

编辑 `.env` 至少填 `VISION_API_KEY`（识图用）。写正文用独立的 `TEXT_*`：

```ini
VISION_API_KEY=你的智谱API_Key
VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
VISION_MODEL=glm-4v-flash

TEXT_API_KEY=
TEXT_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
TEXT_MODEL=glm-4-flash
```

支持任意 OpenAI 兼容多模态 API（智谱、通义千问、硅基流动、本地 vLLM 等）。

配置 B 站 Cookie（强烈建议，否则基本拿不到官方 AI 字幕）：

```bash
cp bilibili_cookies.txt.example bilibili_cookies.txt
# 填入 SESSDATA
```

## 使用方法

当用户提供 B 站视频链接并要求做笔记时，直接用 `run_pipeline.py` 一键跑：

```bash
# 单 P / 默认当前 P
python run_pipeline.py BV1xx411c7mD

# 课件/PPT 类（默认 scene 场景检测即可）
python run_pipeline.py BV1xx411c7mD --mode fixed --interval 20

# 操作类视频（PS/剪辑/代码实操）：画面频繁小幅变化，
# 阈值更低更敏感、合并窗口更短，避免相邻步骤被合并
python run_pipeline.py BV1hD42137sx --threshold 0.02 --merge-gap 1.5

# 访谈/口播类：只下字幕不抽帧，生成纯文字笔记
python run_pipeline.py BV1zNoVB1EWb --no-video

# 长视频：切块生成（默认每段约 25 分钟，最多 12 段）
python run_pipeline.py BV1xx411c7mD --segment-minutes 25 --max-segments 12

# 社会/哲学类顺带抓评论区（学习类价值低，默认 off）
python run_pipeline.py BV1xx411c7mD --comments top

# 多 P：转全部 / 指定分P列表
python run_pipeline.py BV1xx411c7mD --pages all
python run_pipeline.py BV1xx411c7mD --pages 1,3,5

# 断点续跑（从某步开始）
python run_pipeline.py BV1xx411c7mD --from-step 3

# 生成后归档进 ima 知识库
python run_pipeline.py BV1xx411c7mD --kb-id <知识库ID>
python run_pipeline.py BV1xx411c7mD --route          # 按内容自动归档到主题文件夹
```

输出在 `runs/<BV>_p<N>/output/`：`*.md`（笔记）、`*.pdf`（供知识库入库）、`images/`（配图）。每分P 含 `result.json` 汇总。

## 笔记写作标准

- 以顶级学者身份，融会贯通字幕和截图
- 追求知识完整性，宁可多写不可遗漏
- 保留所有重要细节、公式、定义、例题、做题技巧
- 解释 WHY，不只是 WHAT
- **每张配图带可点击时间戳**，与视频位置对齐
- 截图只补充字幕没讲的考点，不抄非考点内容
- 学科自适应：按标题/简介自动分类（tech / humanities / social_philosophy / general），套用对应模板与字数预算，不要硬编码学科

## 关键规则

- **抽帧默认 `--mode scene`**（场景切换检测，适合课件/PPT），不要用旧的 `--mode cover` 全覆盖；操作类改用 `--threshold 0.02 --merge-gap 1.5`
- **选帧全自动**：`auto_select.py` 按分数 + 主题多样性精选到 `final/`，无需人工 `cp` 挑选帧
- **所有视觉分析走 `score_frames_concurrent.py`**（score / extract 两种模式），不要串行逐帧调用
- **模型分离**：识图用 `VISION_*`，写正文用 `TEXT_*`；长文 / 切块笔记 `TEXT_MODEL` 推荐 `deepseek-chat`（glm-4-flash 长文易截断）
- **输出 Markdown + PDF**，用 Markdown 语法（非 DOCX，不要用 `run.bold`）
- **字幕时间戳格式为 `MMmSSs`**（如 `186m00s`，分钟可超 60），不是 `MM:SS`
- **每个视频/分P 有独立 `runs/<BV>_p<N>/` 目录**，禁止多视频共用
- 帧目录、工作目录保持纯英文路径

## 依赖

```bash
pip install -r scripts/requirements.txt
```

需要 `ffmpeg`（见上方安装）。
