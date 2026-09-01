---
name: video-notes-pipeline
version: 1.1.0
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

> 全流程模型免费档即可跑（智谱 GLM-4V-Flash 识图 / deepseek-chat 写正文）。

## 工作流程

由 `run_pipeline.py` 串起七步（失败可用 `--from-step` 断点续跑）：

1. 下载视频 + 官方 AI 字幕（`scripts/extract_frames.py`）
2. OCR 预筛 + 感知哈希去重（`scripts/smart_select.py`）
3. 多模态视觉打分（`scripts/score_frames_concurrent.py --mode score`）
4. 按分数 + 主题多样性**自动精选**（`auto_select.py`，无需人工挑选）
5. 图内文字/公式/流程提取（`score_frames_concurrent.py --mode extract`）
6. 融合字幕生成 **Markdown + PDF**（`md_note.py` / `md2pdf.py`）
7. （可选）上传到 ima 知识库（`to_ima.py`）

## 耗时预估（v1.0.2 新增）

**开始处理前先告知用户预估耗时**，避免用户干等。经验公式（2026-08 实测四个样本拟合）：

> **处理耗时 ≈ 5 + 0.56 × 视频分钟数**（分钟；下限约 6 分钟）

| 视频时长 | 预估处理耗时 | 主要时间去向 |
|---------|-------------|-------------|
| ≤5 分钟 | 约 6-8 分钟 | 固定开销为主（下载/抽帧/笔记/PDF/入库） |
| 10 分钟 | 约 10-12 分钟 | 下载 ~1min + ASR 转写 + 抽帧打分 |
| 20 分钟 | 约 15-18 分钟 | 随视频时长线性增长 |
| 30 分钟 | 约 20-25 分钟 | ASR 转写是大头（约 0.5-0.7×音频时长） |
| 60 分钟 | 约 35-40 分钟 | 建议 `--segment-minutes 25` 切块 |

**估算口径**：端到端 = 下载（dash 流,1-2 分钟）+ ASR 语音转文字（faster-whisper small CPU 约 0.5-0.7×音频时长）+ 抽帧打分 + 笔记生成 + PDF + 入库。流水线日志 `[pipeline] 全部完成，总耗时 Xs` 可回填校准。

**实测样本**：BV1B9TC66EHH（3.6 分钟）→ 约 6 分钟；BV1Wr1uBLEj5（10 分钟）→ 约 12 分钟；BV13z6JYJEd4（33 分钟）→ 约 23 分钟；BV1n7uj6MEyo（8 分钟）→ 约 9 分钟。

## ★ 硬性约束：永远不要「裁剪画面」去字幕

> 截图时若字幕挡住了 PPT 内容，**绝对不能用 ffmpeg `crop` 把画面底部（或任何区域）裁掉来「去掉字幕」**。
> 原因：① 字幕位置不固定，写死的 crop 区域迟早裁错；② PPT 是全屏，内容也在被裁区域里，一裁就把正文切掉，比字幕遮挡更严重。

正确两条路（都不裁切）：
- **A. 截图落在「字幕空挡」**：用带时间戳的字幕（官方或 ASR 都带 `from/to`）把截图时刻挪到两句字幕都不在屏上的空挡。
- **B. 无空挡就接受遮挡**：直接在 PPT 页代表时刻全帧截图，字幕挡住就挡吧——比裁掉内容好。

烧录硬字幕 PPT 视频用 `--slidegap`：把场景阈值从 0.04 提到 ~0.1，字幕闪变分值都 <0.1、真实翻页 ≥0.1，得到干净「一页一帧」，全程无 crop。连续旁白视频字幕首尾相接几乎无空挡时，按 B 接受遮挡即可。

## 安装（首次 / 跨平台，国内镜像兜底）

无论 Windows / macOS / Linux，**是否挂 VPN 都能装**：AI 先探测系统与网络，直连不稳就自动切国内镜像，有代理则直连更快。

```bash
# 1) 克隆（GitHub 直连不稳时加 ghproxy 前缀）
git clone https://ghproxy.net/https://github.com/rowanlin-dev/video-notes-pipeline.git
#   （前缀不通换 https://mirror.ghproxy.com/ 或 https://gitclone.com/github.com/...）

# 2) 装依赖（pip 永久切清华源，避免 PyPI 直连超时）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install -r scripts/requirements.txt

# 3) ffmpeg（抽帧必需，不依赖 chocolatey）
#    Windows：下便携版解压到 C:\ffmpeg，pipeline 自动识别 C:\ffmpeg\bin；或 winget install -e --id Gyan.FFmpeg
#    macOS：brew install ffmpeg   |   Ubuntu/Debian：sudo apt-get install ffmpeg
```

> 🪟 **Windows 不想敲命令**：直接双击仓库里的 `setup_windows.bat`，自动装 Python、拉仓库、切镜像、装 ffmpeg、预下载 ASR 模型，全程走国内源、零手动。

> ASR 模型（无官方字幕时兜底，国内用镜像）：
> `HF_ENDPOINT=https://hf-mirror.com huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small`

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

当用户提供 B 站视频链接并要求做笔记时，直接用 `run_pipeline.py` 一键跑。用户也可只说自然语言（如「帮我总结视频 BVXXXXXX」「这视频有点长，可以选用超出默认上限的截图进笔记」「帮我总结视频 BVXXXXXX 并入库 ima」），由 AI 映射到下方命令，无需记参数。

```bash
# 单 P / 默认当前 P
python run_pipeline.py BV1xx411c7mD

# 课件/PPT 类（默认 scene 场景检测即可）
python run_pipeline.py BV1xx411c7mD --mode fixed --interval 20

# 烧录字幕的 PPT 视频（字幕合成在画面里、无独立字幕轨）：用 slidegap 抽帧，避开字幕遮挡、不裁剪
python run_pipeline.py BV1xx411c7mD --slidegap

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
- **烧录硬字幕 PPT 视频用 `--slidegap`**：字幕合成在画面里、无独立字幕轨，抽帧落在翻页空挡、避开字幕遮挡；**禁止用 ffmpeg `crop` 裁掉字幕区域（会一起裁掉内容）**，无空挡就接受遮挡
- **选帧全自动**：`auto_select.py` 按分数 + 主题多样性精选到 `final/`，无需人工 `cp` 挑选帧
- **所有视觉分析走 `score_frames_concurrent.py`**（score / extract 两种模式），不要串行逐帧调用
- **模型分离**：识图用 `VISION_*`，写正文用 `TEXT_*`；长文 / 切块笔记 `TEXT_MODEL` 推荐 `deepseek-chat`（glm-4-flash 长文易截断）
- **输出 Markdown + PDF**，用 Markdown 语法（非 DOCX，不要用 `run.bold`）
- **字幕时间戳格式为 `MMmSSs`**（如 `186m00s`，分钟可超 60），不是 `MM:SS`
- **每个视频/分P 有独立 `runs/<BV>_p<N>/` 目录**，禁止多视频共用
- 帧目录、工作目录保持纯英文路径

## 常见坑与对策（实战沉淀）

### 1. B站 412 风控：下载失败

视频页直下可能被 IP 级 412 拦截，但 `api.bilibili.com` 通常正常。绕过链路（已验证）：

- 用 `bilibili_cookies.txt`（Netscape 格式）逐行解析成 `Cookie:` header
- 调 playurl API 拿 dash 流：视频轨选 720p（id=64），音频轨选 bandwidth 最大
- `curl --http1.1` 下载 m4s 分片，`ffmpeg -i video -i audio -c copy` 合并成 mp4
- 合并出的 mp4 放在 `runs/<BV>_p<N>/` 下，pipeline 会跳过下载直接复用

### 2. 官方 AI 字幕缺失或串台（内容与视频无关）

`player/v2` 返回的字幕 `subtitle_url` 可能为空（需 wbi 签名），且 AI 字幕有串台前科（如行车导航语音）。对策：**先抽查字幕内容与标题主题是否一致**；不一致或缺失则删掉 `*_subtitles.{json,txt}`，用本机语音转文字（ASR，Automatic Speech Recognition，自动语音识别——把视频里说的话转成文字字幕）兜底：

```bash
# 安装 + 取音频轨（16kHz 单声道）
pip install faster-whisper
ffmpeg -y -i <video>.mp4 -vn -ar 16000 -ac 1 /tmp/audio_16k.wav
# 下载模型（国内需镜像 + 禁用 xet）
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
  huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small
# 语音转文字(ASR)：WhisperModel(..., device="cpu", compute_type="int8")，transcribe(language="zh")
python scripts/asr_subtitle.py /tmp/audio_16k.wav runs/<BV>_p<N>/<BV>_p<N>_subtitles.json
```

- faster-whisper small CPU 约 3-5 分钟/8 分钟音频（无 GPU 也能跑）
- 字幕 JSON 格式：`{"body": [{"from": 秒, "to": 秒, "content": "..."}]}`，TXT 每行 `[MMmSSs] 文本`
- **语音转文字(ASR)错词用 deepseek-chat 术语级修正**：`python scripts/fix_subtitles.py <字幕JSON> --video-topic <主题> --extra-terms "poster man→Postman, moke→mock"`（术语表要显式写进 prompt，否则 LLM 保守不改）
- 修正后 `--from-step 6` 重新生成笔记

### 3. PDF 中文豆腐块（本机无 Chrome/Edge / 其他无浏览器环境）

md2pdf 默认调用系统 Edge/Chrome 渲染（Windows 10 自带 Edge，无需额外装）；无浏览器环境才用 weasyprint + TTF 中文字体兜底（`weasyprint`/`pymupdf` 已移入 `scripts/requirements-optional.txt`，非默认依赖）：

- ⚠️ **必须用 TTF 版字体**（TrueType 轮廓）：OTF(CFF) 版会被 fontconfig 拒加载。可用 `https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf`（约 16MB 可变字体，URL 需编码 `%5B` `%5D`）
- 生成：`python scripts/gen_full_note.py <笔记.md> [标题] [字体.ttf]`（内部：md_to_html → 注入 `@font-face` → weasyprint `FontConfiguration` 出 PDF）
- 验证：`pymupdf` 读 PDF，检查 `get_fonts()` 含 Noto Sans SC 且 `get_text()` 中文正常

### 4. 智谱 API 429 限流（并发打分/提取）

`score_frames_concurrent.py` 并发高时易 429。对策：

- 降低并发重跑：`--workers 2 --max-retries 5 --resume`
- ⚠️ resume 按文件名跳过，**失败帧也带 error 会被跳过**——最稳妥是清空输出 JSON 后对整个目录重打分
- ⚠️ **打分对象是 `selected/` 而非 `scene/`**：scene/ 帧名带时间戳（`frame_0001_00m00s.jpg`），selected/ 是纯编号（`frame_0001.jpg`），scores JSON 的 key 必须与 auto_select 输入的 selected/ 一致

### 5. deepseek 批量修正字幕的行号陷阱

分批让 LLM 修正字幕时，每批 LLM 会重新编号（续编行号），超出批内校验被丢弃、只回写第一批。对策：**不依赖 LLM 回传行号**，改为按输出顺序拼接 + 只提取 `[时间戳] 文本` 行；每轮从原始 JSON 重建输入保证幂等（见 `scripts/fix_subtitles.py`）。

## 依赖

```bash
pip install -r scripts/requirements.txt
```

需要 `ffmpeg`（见上方安装）。
