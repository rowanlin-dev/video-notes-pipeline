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
