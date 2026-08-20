# Bilibili Video Notes

从 B 站教育/讲课视频一键生成带截图、可点击时间戳的 **Markdown + PDF** 图文笔记，可选择性归档进 ima 知识库。

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
