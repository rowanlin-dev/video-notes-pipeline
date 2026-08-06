# Video Notes Pipeline 📝

> **B站视频 → 图文笔记 → 知识库 一键流水线**
>
> 从B站教育/讲课视频自动生成**带截图、可点击时间戳**的 Markdown + PDF 笔记，
> 可选一键归档进 ima 知识库。全程模型免费档即可跑（智谱 GLM-4V-Flash / GLM-4-Flash）。
>
> 全流程：`下载视频+字幕 → 全覆盖抽帧 → OCR+哈希去重 → AI视觉打分精选 → 提取图中内容 → 融合生成MD/PDF →（可选）入 ima`

<p align="center">
  <img src="https://img.shields.io/badge/bilibili-1eabc9.svg?logo=bilibili&logoColor=white&style=flat-square" alt="Bilibili">
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg?logo=python&style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License">
</p>

## 目录

- [一键安装（复制粘贴给 AI）](#-%E4%B8%80%E9%94%AE%E5%AE%89%E8%A3%85%E5%A4%8D%E5%88%B6%E7%B2%98%E8%B4%B4%E7%BB%99-ai)
- [功能特点](#-%E5%8A%9F%E8%83%BD%E7%89%B9%E7%82%B9)
- [快速开始](#-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B)
- [⭐ 重点：.env 配置（含垃圾帧过滤）](#-%E9%87%8D%E7%82%B9env-%E9%85%8D%E7%BD%AE%E5%90%AB%E5%9E%83%E5%9C%BE%E5%B8%A7%E8%BF%87%E6%BB%A4)
- [日常使用](#-%E6%97%A5%E5%B8%B8%E4%BD%BF%E7%94%A8)
- [完整工作流](#-%E5%AE%8C%E6%95%B4%E5%B7%A5%E4%BD%9C%E6%B5%81)
- [🔧 技术实现](#-%E6%8A%80%E6%9C%AF%E5%AE%9E%E7%8E%B0)
- [📚 入 ima 知识库（可选）](#-%E5%85%A5-ima-%E7%9F%A5%E8%AF%86%E5%BA%93%E5%8F%AF%E9%80%89)
- [🛠️ 常见坑与对策（实战沉淀）](#常见坑与对策实战沉淀)
- [常见问题](#-%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98)
- [Agent 使用](#-agent-%E4%BD%BF%E7%94%A8)
- [目录结构](#-%E7%9B%AE%E5%BD%95%E7%BB%93%E6%9E%84)
- [依赖与许可证](#-%E4%BE%9D%E8%B5%96%E4%B8%8E%E8%AE%B8%E5%8F%AF%E8%AF%81)
- [反馈](#-%E5%8F%8D%E9%A6%88)

---

## ⚡ 一键安装（复制粘贴给 AI）

```
请帮我安装 video-notes-pipeline：

git clone https://github.com/rowanlin-dev/video-notes-pipeline.git
cd video-notes-pipeline
pip install -r scripts/requirements.txt

安装完成后，把根目录的 .env.example 复制为 .env 并填入 API Key，
配置好 bilibili_cookies.txt（可选但强烈建议），然后读 README.md 了解如何使用。
```

---

## ✨ 功能特点

- 🎬 **自动下载** B站视频和官方 AI 字幕
- 📸 **全覆盖抽帧**（场景切换检测 + 定时抽帧两种模式），不丢任何画面
- 🔍 **OCR + 感知哈希双重去重**，130 帧 → 30 帧左右，不丢有价值内容
- 🧠 **AI 视觉打分**，选出每个知识点最完整的一帧
- 🧹 **垃圾帧过滤**：自动剔除「求三连 / 片头广告 / 求赞」等无信息量帧（见下方重点配置）
- 🔗 **自动补充外部资料**：视频提到 GitHub / 博客 / 官网等来源时，自动抓取并补充权威说明到笔记（抓取前提示开代理，连不上则只补链接）
- 📝 **融合字幕 + 截图内容**生成 Markdown + PDF 笔记，每张图带可点击时间戳
- 📚 **可选一键入库 ima** 知识库，按内容自动归档到主题文件夹
- 🤖 **多 Agent 支持**：WorkBuddy（本仓库作者在用的环境）/ Hermes / Claude Code / Codex CLI

## 📊 效果对比

| 输入 | 输出 |
|------|------|
| 21 分钟 B站视频 | 7-12 张精选截图 + 完整知识点笔记（MD + PDF） |
| 130 帧原始截图 | 30 帧去重后 → 7-12 帧 AI 精选（已过滤垃圾帧） |
| AI 字幕文本 | 融合进结构化笔记，不照搬 |

---

## 🚀 快速开始

### 1. 克隆安装

```bash
git clone https://github.com/rowanlin-dev/video-notes-pipeline.git
cd video-notes-pipeline
pip install -r scripts/requirements.txt
```

> 推荐使用虚拟环境：`python -m venv venv && venv/Scripts/activate`（Windows）
> 或直接用仓库里的 `venv/Scripts/python.exe` 跑脚本。

### 2. 安装 FFmpeg

系统环境变量中需要可直接调用 `ffmpeg`（抽帧依赖）。

- **Windows**：`choco install ffmpeg`，或从 https://ffmpeg.org 下载后把 `bin` 加入 PATH。
- **macOS**：`brew install ffmpeg`
- **Ubuntu/Debian**：`sudo apt-get install ffmpeg`

### 3. 配置 API

```bash
cp .env.example .env
```

编辑 `.env`，把 `VISION_API_KEY=` 后面换成你的 Key（默认用智谱 GLM 免费档，不用改其他行）：

```ini
VISION_API_KEY=你的智谱API_Key
VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
VISION_MODEL=glm-4v-flash

TEXT_API_KEY=
TEXT_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
TEXT_MODEL=glm-4-flash
```

支持任何 OpenAI 兼容格式的多模态 API（智谱、通义千问、硅基流动、本地 vLLM 等）。
`.env.example` 末尾附了通义千问、硅基流动的示例，替换对应几行即可。

### 4. 配置 B 站 Cookie（强烈建议）

不配也能跑，但**不配基本拿不到官方 AI 字幕**，笔记质量会明显下降；配了还能下更高画质、降低风控概率。

```bash
cp bilibili_cookies.txt.example bilibili_cookies.txt
```

从浏览器 F12 → Application → Cookies → `https://www.bilibili.com` 复制 `SESSDATA` 的值，
替换文件里的 `YOUR_SESSDATA_HERE`。

> ⚠️ Cookie 有时效（通常约 1 个月），过期后需重新获取。

---

## ⭐ 重点：.env 配置（含垃圾帧过滤）

> 这一节是**最影响成品质量、却最容易被跳过**的配置，建议先读完再跑。
> 把根目录的 `.env.example` 复制为 `.env` 后，主要配置项如下：

| 配置项 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `VISION_API_KEY` | ✅ | - | 视觉模型 API Key（智谱/其它） |
| `VISION_BASE_URL` | - | 智谱 | 视觉模型接口地址 |
| `VISION_MODEL` | - | glm-4v-flash | 视觉模型名（打分 + 提取图中文字） |
| `TEXT_API_KEY` | - | 复用 VISION | 文本模型 API Key |
| `TEXT_BASE_URL` | - | 复用 VISION | 文本模型接口地址 |
| `TEXT_MODEL` | - | glm-4-flash | 文本模型名（写笔记正文 + 评论总结，纯文本任务） |
| `WORKERS` | - | 8 | 视觉调用并发数 |
| `TIMEOUT` | - | 120 | 单次视觉调用超时（秒） |
| `VISION_MAX_TOKENS` | - | 1024 | 视觉模型输出上限；智谱 flash 硬上限 1024 |

> **模型可切换**：`.env` 中 `VISION_*`（帧打分 / 识图，必须用视觉模型）与 `TEXT_*`（写笔记正文 + 评论总结，纯文本任务）是分开的。当前启用项写在前面、暂不用的写在「备用」注释块里——**所有 Key 都保留**，切换模型只需取消 / 加注释，不必重新申请 Key。本项目用 `deepseek-chat` 作文本模型（chat 档，非 pro），`glm-4v-flash` 作视觉模型。
>
> **📝 长文 / 长视频笔记强烈推荐用 Deepseek 写正文**：笔记正文由 `TEXT_MODEL` 生成。短笔记用 `glm-4-flash` 免费档即可；但**长文（尤其 3 小时访谈、1 小时+ 技术实操这类切块后单段仍有数千字、整篇破万字）务必把 `TEXT_MODEL` 切到 `deepseek-chat` 或更强的长上下文模型**——Deepseek 中文长文写作更稳、上下文更长，`glm-4-flash` 在超长输入下更易截断或发散。本项目 `.env` 已默认将 `TEXT_*` 指向 `deepseek-chat`。
| `IMA_KB_ID` | - | - | 默认入库知识库 ID；留空则不入库，需用 `--route`/`--kb-id` |
| `AD_KEYWORDS` | - | 见 `.env.example` | **字幕广告段过滤**，命中即跳过该时间段抽帧 |
| `AD_CONTEXT_SECONDS` | - | 20 | 广告关键词命中后向前后扩展的秒数 |
| `FRAME_TYPE_TRASH` | - | `meme,blackscreen,ad,face` | AI 识别的低价值画面类型，直接剔除 |
| `FRAME_TRASH_KEYWORDS` | - | 见 `.env.example` | **垃圾帧黑名单**，逗号分隔，支持正则 |
| `FRAME_MIN_SCORE` | - | 3 | 入选帧最低 AI 分数 |
| `SKIP_HEAD_SECONDS` | - | 0 | 跳过片头 N 秒，去掉求三连/片头动画 |
| `LEARNED_TRASH_FILE` | - | `trash_learned.json` | 自进化黑名单文件路径 |

### 🧹 垃圾帧过滤（强烈建议先配）

视频里的「一键三连」「完整资料 免费领取」「扫码加微信」「黑屏字幕」「表情包」「讲师大头」
本质都是**没有信息量的帧**，混入笔记纯属噪音。本工具用四层机制把它们挡在门外：

**① 字幕广告段过滤（从源头拦截）** — 下载字幕后扫描 `AD_KEYWORDS`，命中即视为广告/卖课段，
向前后扩展 `AD_CONTEXT_SECONDS` 秒后**抽帧时直接跳过**。避免截到 "扣 666 领资料""加小助理" 等画面。

```ini
AD_KEYWORDS=资料,领取,免费,加微信,小助理,扣666,扣个666,点赞关注,一键三连,求赞,课程,训练营,私教,咨询,优惠,报名,付费,会员,专栏,扫码,进群,福利
AD_CONTEXT_SECONDS=20
```

**② 规则黑名单 + AI 类型过滤（零成本）** — `.env` 里加：

```ini
FRAME_TYPE_TRASH=meme,blackscreen,ad,face
FRAME_TRASH_KEYWORDS=白嫖,一键三连,求赞,点赞关注,记得投币,关注,三连,投币,点赞,资料,领取,免费,加微信,小助理,扣666,扣个666,课程,训练营,私教,咨询,优惠,报名,付费,会员,专栏,扫码,进群,福利,面试题,完整资料
FRAME_MIN_SCORE=3
SKIP_HEAD_SECONDS=10          # 跳过片头 10 秒，直接去掉求三连/片头动画
```

- 命中帧的 theme / keywords / OCR 文字含黑名单词即剔除；`FRAME_MIN_SCORE` 低于该分也不入选。
- AI 会给每帧输出 `type`（diagram/slide/code_ui/demo/meme/blackscreen/ad/face/other），
  `FRAME_TYPE_TRASH` 中的类型直接剔除。
- 关键词**支持正则**，例如 `求?赞|三?连` 可同时命中「求赞」「三连」「求三连」。
- 临时对某视频生效：`python run_pipeline.py <BV> --skip-head 10`

**③ OCR 二次校验** — `auto_select.py` 会用 OCR 再读候选帧，图中文字命中广告词直接剔除，
拦截 "资料页""免费领取" 等视觉模型可能误判为 slide 的帧。

**④ 自进化黑名单（治本）** — 发现漏网垃圾帧后：

```bash
python learn_trash.py runs/BV1AaN162EsX_p1 --frame frame_0002.jpg
```

系统会读取该帧的 theme/keywords/图中文字，追加到 `trash_learned.json`；
下次跑任意视频，`auto_select.py` 自动加载并剔除同类帧。加 `--delete` 可同时从当前 run 删掉该帧。

> 如果一个视频确实只有口播 + 表情包 + 黑屏字幕，过滤后可能得到 **0 张配图**。
> 此时会自动生成**纯文字笔记**并正常入库，不会硬塞无意义截图。

---

## 💡 日常使用

```bash
# 最常用：一条命令搞定（生成 MD + PDF，未配知识库则跳过入库）
python run_pipeline.py BV1xx411c7mD

# 指定分P
python run_pipeline.py BV1xx411c7mD --page 3

# 只处理某个时间段
python run_pipeline.py BV1xx411c7mD --start 5:00 --end 25:00

# 纯口播视频（画面变化少）用定时抽帧
python run_pipeline.py BV1xx411c7mD --mode fixed --interval 60

# 跳过片头 10 秒（去掉 UP 主求三连/片头动画）
python run_pipeline.py BV1xx411c7mD --skip-head 10

# 想要更多配图
python run_pipeline.py BV1xx411c7mD --max-frames 20

# 按内容自动归档进 ima（推荐，最省事）
python run_pipeline.py BV1xx411c7mD --route
```

### 断点续跑

某一步失败了不用从头再来（视频和帧已缓存）：

```bash
# 从第 4 步（自动精选）继续
python run_pipeline.py BV1xx411c7mD --from-step 4

# 只重新生成笔记（改了 prompt 或想换模型时用）
python run_pipeline.py BV1xx411c7mD --from-step 6
```

---

## 📖 完整工作流

```
原始帧（场景切换/定时全覆盖）
  ↓ 字幕广告段过滤（AD_KEYWORDS / AD_CONTEXT_SECONDS）
  ↓ OCR 预筛：去掉空白/面部帧
  ↓ 哈希去重（视觉结构相似归为一组）→ 约 30 帧
  ↓ 垃圾帧过滤（FRAME_TYPE_TRASH / FRAME_TRASH_KEYWORDS / SKIP_HEAD_SECONDS / OCR 二次校验 / 自进化黑名单）
  ↓ AI 视觉打分（1-10 分，输出 type + has_educational_visual）
  ↓ 自动精选（分数 + 主题多样性）→ 7-12 帧（也可能 0 帧）
  ↓ AI 提取图中文字/公式/表格/概念
  ↓ 融合字幕 + 图中内容生成 Markdown + PDF（0 帧时生成纯文字笔记）
  ↓ （可选）上传 ima 知识库
```

`run_pipeline.py` 内部串起 7 步（失败可 `--from-step` 续跑）：

1. **抽帧 + 拉字幕**：`scripts/extract_frames.py`
2. **OCR 预筛 + 去重**：`scripts/smart_select.py`
3. **视觉打分**：`scripts/score_frames_concurrent.py --mode score`
4. **自动精选**：`auto_select.py`（含类型黑名单 / 关键词 / OCR 二次校验 / 自进化黑名单）
5. **提取图中内容**：`scripts/score_frames_concurrent.py --mode extract`
6. **生成 MD + PDF**：`md_note.py` / `md2pdf.py`（无浏览器时 PDF 用 `scripts/gen_full_note.py` 走 weasyprint + TTF 兜底，见下方「常见坑与对策 §3」）
7. **上传 ima（可选）**：`to_ima.py`

### 产出在哪

```
runs/BV1xx411c7mD_p1/
├── BV1xx411c7mD_p1_subtitles.txt    字幕全文
├── scene/                            原始抽帧（全部）
├── selected/                         去重 + 过滤后
├── final/                            精选帧
├── vision_scores.json                每帧打分明细
├── vision_extract.json               每帧提取出的图中文字
├── result.json                       本次运行摘要
└── output/
    ├── 视频标题.md                   ← Markdown 笔记（可编辑）
    ├── 视频标题.pdf                  ← PDF（图片内嵌，用来入 ima）
    └── images/                       笔记引用的配图
```

> `.md` 方便自己改、方便版本管理；`.pdf` 图片是内嵌的，传进 ima 后截图不会丢。

---

## 🔧 技术实现

本节说明视频与字幕的获取方式，以及常见的下载拦截问题（更偏实现细节，普通用户可跳过）。

### 视频下载

底层使用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 调用 B站播放页地址进行下载：

```bash
python -m yt_dlp "https://www.bilibili.com/video/<BV>?p=<分P>" \
  -f "bestvideo[height<=720]+bestaudio/best[height<=720]" \
  --user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124" \
  --referer "https://www.bilibili.com/" \
  --retries 5 --fragment-retries 5
```

要点：

- **画质上限 720p**，自动合并视频与音轨。
- 请求头带 Chrome `User-Agent` 与 `Referer`——不加极易被 B站风控拦截成 HTTP 412。
- **可选 Cookie**：若根目录存在 `bilibili_cookies.txt`（Netscape 格式），会自动带上，可提升画质并获取官方 AI 字幕；不配置也能运行。
- 支持时间段裁剪（`--start` / `--end`），只下载指定区间，避免重复下载整段。

### 字幕获取

与下载相互独立，走 B站开放 API（无需登录）：

- **视频元信息**：`GET https://api.bilibili.com/x/web-interface/view?bvid=<BV>` 取分P、cid、标题。
- **字幕列表**：`GET https://api.bilibili.com/x/player/wbi/v2?bvid=<BV>&cid=<cid>`；携带 `SESSDATA`（由 Cookie 解析）时更易拿到官方 AI 字幕。
- 字幕 JSON 转为带时间戳的 `.txt`（如 `[00:25] 内容`），供后续提取关键因果句。

### 关于 412 / WAF 风控

B站对访问 `www.bilibili.com` 视频页的出口 IP 有 WAF 风控：

- **典型诱因**：开启 VPN/代理（海外 IP 必被拦）、或短时间请求过密。
- 元信息/字幕走 `api.bilibili.com`，通常不受影响，因此会出现「**能查到标题却下不了视频**」——这是 412 的典型表现，并非脚本故障。
- 处理顺序：① 配置 Cookie（登录态更稳）② 关闭 VPN/代理 ③ 降低 `WORKERS` 或稍后重试。
- VPN 属于环境层变量，代码无法绕过，需手动关闭。

---

## 📚 入 ima 知识库（可选）

> 把笔记直接归档进**腾讯 ima 知识库**，省去手动下载再上传。
> 这是**可选功能**，依赖本机已安装的 ima WorkBuddy skill，不影响核心笔记生成。

> **💡 选用哪种 ima 接入方式？**
> - **用 WorkBuddy**：直接用 WorkBuddy 自带的 **ima 连接器**最好 —— 连接器管理页一键「信任/连接」即可，功能最全、持续更新，无需手动装 skill。
> - **非 WorkBuddy 环境**（Hermes、Claude Desktop、Cursor、Cline 等任意 MCP 客户端）：推荐安装腾讯官方 **ima-skill** → https://ima.qq.com/agent-interface ，按页面指引部署后，即可获得与 WorkBuddy 内置连接器一致的 ima 能力（知识库 + 笔记的读写搜）。

### 前置条件

ima 自动入库依赖腾讯 ima 的 WorkBuddy skill：`~/.workbuddy/skills/ima-skills`
（Windows：`C:\Users\<用户名>\.workbuddy\skills\ima-skills`）。
该 skill 提供 `ima_api.cjs`、`preflight-check.cjs`、`cos-upload.cjs` 等脚本，
**不属于本仓库代码**，需在 WorkBuddy 连接器管理页安装并「信任」。

配置步骤：

1. 打开 WorkBuddy → 连接器管理 → 找到 ima 连接器 → 点击「信任/连接」。
2. 按 ima skill 提示填写 `Client ID` 和 `API Key`（通常写到
   `~/.config/ima/client_id` 和 `~/.config/ima/api_key`）。
3. 验证凭证有效：
   ```bash
   python to_ima.py --list-kb
   ```
   能列出知识库即配置成功。

### 三种入库方式

**方式 A：按内容自动归档（推荐，最省事）**

```bash
python run_pipeline.py BV1xx411c7mD --route
```

系统会读笔记标题 + 大纲，自动选择最匹配的知识库，并自动创建/复用 2-6 字的中文主题文件夹
（如「多租户」「Vue3」），把 PDF 上传进去。

**方式 B：指定固定知识库**

在 `.env` 里填：

```ini
IMA_KB_ID=你的知识库ID
```

获取方法：`python to_ima.py --list-kb`，然后正常运行 `python run_pipeline.py BV1xx411c7mD`。

**方式 C：命令行临时指定**

```bash
python run_pipeline.py BV1xx411c7mD --kb-name "全栈开发知识库" --folder-id folder_xxx
```

### 验证上传链路（不污染知识库）

```bash
python to_ima.py --pdf runs/BVxxx_p1/output/xxx.pdf --route --verify
```

`--verify` 会跑完 查重 → 建媒体 → COS 上传，但**不调用 add_knowledge**，知识库不留任何条目，适合测试。

### 跳过 ima 入库

```bash
python run_pipeline.py BV1xx411c7mD --no-ima
```

---

## 🛠️ 常见坑与对策（实战沉淀）

### 1. B站 412 风控：下载失败，但能查到标题

`www.bilibili.com` 视频页直下可能被 IP 级 412 拦截，但 `api.bilibili.com`（元信息/字幕）通常正常，于是出现「能查到标题却下不了视频」。已验证的绕过链路：

- 用 `bilibili_cookies.txt`（Netscape 格式）逐行解析成 `Cookie:` header
- 调 playurl API 拿 dash 流：视频轨选 720p（id=64），音频轨选 bandwidth 最大
- `curl --http1.1` 下载 m4s 分片，`ffmpeg -i video -i audio -c copy` 合并成 mp4
- 合并出的 mp4 放在 `runs/<BV>_p<N>/` 下，pipeline 会跳过下载直接复用

### 2. 官方 AI 字幕缺失或串台（内容与视频无关）

`player/v2` 返回的字幕 `subtitle_url` 可能为空（需 wbi 签名），且 AI 字幕有串台前科（如行车导航语音）。对策：**先抽查字幕内容与标题主题是否一致**；不一致或缺失则删掉 `*_subtitles.{json,txt}`，用本机 ASR 兜底：

```bash
pip install faster-whisper
ffmpeg -y -i <video>.mp4 -vn -ar 16000 -ac 1 /tmp/audio_16k.wav
# 国内需镜像 + 禁用 xet 下载模型
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
  huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small
# ASR：WhisperModel(..., device="cpu", compute_type="int8")，transcribe(language="zh")
python scripts/asr_subtitle.py /tmp/audio_16k.wav runs/<BV>_p<N>/<BV>_p<N>_subtitles.json
```

- faster-whisper small CPU 约 3-5 分钟/8 分钟音频
- 字幕 JSON 格式：`{"body": [{"from": 秒, "to": 秒, "content": "..."}]}`，TXT 每行 `[MMmSSs] 文本`
- **ASR 错词用 deepseek-chat 术语级修正**：`python scripts/fix_subtitles.py <字幕JSON> --video-topic <主题> --extra-terms "poster man→Postman, moke→mock"`（术语表要显式写进 prompt，否则 LLM 保守不改）
- 修正后 `--from-step 6` 重新生成笔记

### 3. PDF 中文豆腐块（本机无 Chrome/Edge）

`md2pdf.py` 默认依赖 Chrome/Edge 渲染。无浏览器时用 weasyprint + TTF 中文字体：

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

---

## ❓ 常见问题

**Q：提示 412 / 请求被拦截**

B站 WAF 风控，按序排查：① 先配 cookie（`set_cookie.py`）——未登录最易被拦；② 关掉 VPN/代理；
③ 等几分钟，或把 `WORKERS` 降到 4。「能查到标题却下不了视频」是 412 典型表现，不是脚本坏了。

**Q：没有字幕**

不是所有视频都有官方 AI 字幕。没有时笔记仅根据截图生成，质量会下降；配好 `SESSDATA` 后重试。

**Q：笔记里混进了求点赞/三连的片头帧**

见上方「⭐ 重点：.env 配置」里的**垃圾帧过滤**，加 `FRAME_TRASH_KEYWORDS` 或 `--skip-head` 即可；
反复出现的漏网帧用 `learn_trash.py` 写进自进化黑名单。

**Q：想换模型**

改 `.env` 里对应几行即可，任何 OpenAI 兼容接口都支持；`.env.example` 末尾附了通义千问、硅基流动示例。

**Q：时间戳链接想在新标签页打开**

已默认给时间戳链接加上 `target="_blank" rel="noopener noreferrer"`，点击 `▶ 12:34` 会在新标签页跳到 B站对应时间点。

**Q：中文路径报错**

项目本身支持中文路径，但遇到 ffmpeg 相关怪错误时，把项目挪到纯英文路径下再试。

---

## 🤖 Agent 使用

### WorkBuddy（本仓库作者在用的环境）

- 直接在本项目目录里和 Agent 对话，让它执行 `python run_pipeline.py <BV号>` 即可；Agent 会按
  `SKILL.md` 的流程跑完整条流水线。
- 想一句话触发：把本项目封装为 WorkBuddy 用户级 skill（放到
  `~/.workbuddy/skills/video-notes-pipeline/`），之后直接在对话框说「总结这个 B站视频」。
- ima 自动入库依赖 WorkBuddy 的 ima 连接器：需先在连接器管理里信任 / 连接 ima，
  再运行带 `--route` 的流水线（见上方「📚 入 ima 知识库」）。

### Hermes Agent

直接读取 `SKILL.md`，按里面的流程执行。

### Claude Code

`CLAUDE.md` 会被自动加载为项目指令。

### Codex CLI

`AGENTS.md` 会被自动加载为项目指令。

---

## 📁 目录结构

```
video-notes-pipeline/
├── README.md
├── 使用说明.md            # 详细中文上手指南（本地个人使用，已 .gitignore 不入库）
├── LICENSE                # MIT（含三方出处声明）
├── .gitignore
├── pyproject.toml         # 项目元数据 / 依赖声明
├── SKILL.md / CLAUDE.md / AGENTS.md / CONTRIBUTING.md   # Agent 指令 / 贡献指南
├── run_pipeline.py        # 一键流水线入口（--pages / --comments / --no-video / 操作类参数）
├── md_note.py             # 融合字幕生成 Markdown（学科自适应模板 + 切块生成）
├── md2pdf.py              # Markdown -> PDF
├── auto_select.py         # 按分数+主题自动精选（含垃圾帧过滤、帧数自适应）
├── learn_trash.py         # 自进化黑名单
├── to_ima.py              # 入 ima 知识库（可选）
├── set_cookie.py          # 写入 B站 SESSDATA
├── .env.example           # ← 配置模板（复制为 .env）
├── bilibili_cookies.txt.example
├── scripts/
│   ├── extract_frames.py          # 下载 + 抽帧（scene 检测/定时、长视频降级、--no-video）
│   ├── smart_select.py            # OCR 预筛 + 感知哈希去重
│   ├── score_frames_concurrent.py # 多模态视觉打分 + 图内文字提取
│   ├── asr_subtitle.py            # 本地 faster-whisper ASR 兜底（字幕缺失/串台）
│   ├── fix_subtitles.py           # deepseek 术语级修正 ASR 错词
│   ├── apply_subtitles.py         # 字幕写回/校验
│   ├── gen_full_note.py           # weasyprint + TTF 中文 PDF（无浏览器兜底）
│   ├── note_subject.py            # 学科分类 + 字数预算（四学科模板）
│   ├── fetch_comments.py          # B站评论抓取（WBI 免登录，off/list/top/summary）
│   ├── extract_key_sentences.py
│   ├── verify_docx.py
│   ├── clean_markdown_bold.py
│   ├── verify_checklist.py
│   └── requirements.txt
├── templates/
│   ├── docx_note_v2.py
│   ├── env.example
│   └── checklist.json
└── runs/                  # 运行产物（已被 .gitignore 忽略，勿提交）
```

---

## 📄 许可证

本项目是 [asdhabdua/bilibili-video-notes-skill](https://github.com/asdhabdua/bilibili-video-notes-skill) 的**衍生作品**，整体采用 **MIT License**。

- ✅ 允许：自由使用、修改、分发（含商业用途），只需保留版权与许可证声明。
- ❌ 禁止：移除原作者版权 / 许可证声明。

完整法律文本见 [LICENSE](./LICENSE)。

### 归属与致谢（均 MIT）

- **[asdhabdua/bilibili-video-notes-skill](https://github.com/asdhabdua/bilibili-video-notes-skill)**（MIT）— 原始基座：视频下载、OCR 去重、AI 视觉打分、笔记生成。
- **[DiTingAI/diting-ai-bilibili-video-to-text-notes](https://github.com/DiTingAI/diting-ai-bilibili-video-to-text-notes)**（© 2026 DiTing, MIT）— 多 P / 百 P 合集批量、结构化输出（大纲 / QA / 思维导图）功能参考，从0实现。
- **[Rimagination/bili-note](https://github.com/Rimagination/bili-note)**（MIT）— 完整材料归档、评论抓取、写前预算（按信息量动态控制笔记长度）思路参考，从0实现。

> 注：实际集成上述项目的代码时，会将其版权声明一并加入 [LICENSE](./LICENSE)。

### ✨ 本项目相对上游的增强（原创 / 显著优化）

在 asdhabdua 基座之上，本项目新增或显著增强了以下能力（均为本项目原创，非来自上游）：

- **四层垃圾帧过滤**：字幕广告段跳过 → Vision 类型分类（diagram/code/meme/blackscreen/ad…）→ auto_select 类型黑名单 + 评分 + OCR 二次校验 → 自进化黑名单（`learn_trash.py`），剔除表情包 / 广告 / 黑屏等无信息量帧。
- **ima 知识库自动入库**：`to_ima.py` 支持 `--route` 按内容自动归档进 ima 对应知识库 / 文件夹。
- **外部资料源主动抓取**：视频 / 字幕 / 帧提到 GitHub 仓库、博客、官网等外部权威资料时，默认主动抓取并补充进笔记（抓取前提示开代理，连不上只补链接、不阻塞）。
- **单视频多主题拆分**：一个视频含多个产品 / 主题时，按时间戳拆分并分别成篇（如 ClickDeck / Lens 拆分示例）。
- **多 P 交互询问（已实现）**：`run_pipeline.py` 新增 `--pages all|current|<列表>`。未显式指定且检测到视频含多个分 P 时，交互终端会主动询问「转全部 / 只转当前 P / 指定列表」，默认只转当前 P（契合「一集一集不同内容，只有整套合集才全转」）；非交互环境（如被 Agent 调用）默认当前 P 并在日志提示用 `--pages` 指定。每个分 P 独立 `runs/` 目录，互不污染。
- **可选评论模式（已实现）**：`run_pipeline.py` 新增 `--comments off|list|top|summary`（默认 off）。设计取舍：学习类视频评论参考意义小，仅社会 / 哲学类才有价值，故默认关闭、完全可选。`list`=按点赞排序的评论列表；`top`=高赞评论；`summary`=LLM 垃圾过滤（广告 / 引流 / 灌水）+ 按「纠错 / 补充 / 实战经验 / 争议观点」精选 10~20 条 + 评论区整体情绪 / 讨论趋势 / 高频关键词总结，作为「💬 评论区精选」章节附于笔记末尾。评论抓取走 B站 WBI 签名接口、**无需登录 cookie**（思路参考 Rimagination/bili-note，MIT）。**自适应输出**：`summary` 按当前 `VISION_MODEL` 的 token 上限自动切换——弱模型（≤1024，如 glm-4v-flash）只回编号 + 类型标签、原文由代码回填（稳）；强模型（gpt-4o / deepseek-chat 等）额外为每条精选附加一句模型点评、并在顶层给出综合论述，输出更优。
- **学科自适应笔记模板（已实现）**：`md_note.py` 按视频学科自动选结构。分类由 `scripts/note_subject.py` 的 `classify_subject()` 用文本模型归桶——`tech`（编程/技术：背景→原理→代码/API→避坑）、`humanities`（人文/访谈：人物→金句→思辨脉络→启示）、`social_philosophy`（社会/哲学/心理：议题→多方观点→论据→争议→启发）、`general`（科普/通识：是什么→为什么→怎么做）。每个桶有专属行文侧重点（如访谈保留说话人金句、观点类客观呈现多方立场）。字数按信息密度动态控制（`compute_note_budget`，移植自 Rimagination write_note_budget）：`600 + 时长×35 + 字幕×0.025 + 证据帧×8 + 评论×3`，clamp 到 [1200,45000]，再乘播放质量乘数（1.0~1.5），避免短视频注水、长视频被截。碎片式学习分支暂缓。
- **操作流程类视频参数（已实现）**：`--threshold`（默认 0.04）和 `--merge-gap`（默认 5.0）从 `run_pipeline.py` 透传给 scene 检测。默认配置适合长视频/课件；操作流程视频（PS/剪辑/代码实操）画面高频小幅变化，建议 `--threshold 0.02 --merge-gap 1.5` 让相邻步骤不被合并、关键操作帧不被漏掉。已用「PS修胡渣」教程（5min 竖屏、313 个场景变化点）端到端验证：scene 检测 → 52 帧 → OCR+哈希去重 → 视觉打分 → 精选 14 帧 → 图内文字提取 → 切块笔记，正文 12567 字、14 帧精准覆盖"应用图像/缩放值 2/补偿值 128"等关键操作界面，图文时间戳对齐。
- **精选帧数自适应（已实现）**：`--max-frames`（默认 12）是**基础上限而非硬墙**——候选帧多（操作步骤多）时按 `候选数×0.6` 自动放宽，并受 `--hard-max-frames`（默认 40，可用 `FRAME_HARD_MAX` 环境变量覆盖）绝对兜底，防止候选极多时失控（每帧消耗 2 次视觉模型调用）。主题多样性去重（关键词 Jaccard 相似度）在放宽后继续兜底，只保留信息独立的步骤帧。实测候选 24 帧 → 自动放宽至 14。
- **长视频专项（已实现）**：针对 1 小时以上的长视频做了两端加固。① **纯字幕模式 `--no-video`**：访谈 / 口播类无需配图，跳过视频下载与抽帧，仅用官方字幕生成纯文字笔记（也彻底规避长视频下载超时）。② **切块生成**：视频时长 > 阈值时 `md_note.py` 自动按时间切片（默认每 25 分钟一段，最多 12 段），每段取自身字幕切片 + 该段帧，按学科模板独立生成一节（`## 第N段` 章节，内部 `###` 小节），最后用一次轻量调用合成全局「内容概要」置于最前，插图全局统一编号——避免把数小时字幕 + 全部帧一次性塞爆模型上下文。③ **下载韧性**：`extract_frames.py` 长视频（>60min）自动降分辨率（720p→480p）减小体积；下载增加断点续传（`--continue`）+ 重试循环（最多 4 次，指数退避），应对 B站 mcdn CDN 偶发超时。此外，**长文笔记务必把文本模型切到 Deepseek**（见上文「模型可切换」说明）——长视频切块后单段仍数千字、整篇常破万，`glm-4-flash` 等免费档在超长上下文下易截断或发散，本项目 `.env` 已默认 `TEXT_MODEL=deepseek-chat`。

### 依赖许可证

本项目直接依赖的开源组件及其许可证如下：

| 依赖 | 许可证 |
|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense |
| [ffmpeg](https://ffmpeg.org/) | LGPL/GPL |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Apache-2.0 |
| [ImageHash](https://github.com/JohannesBuchner/imagehash) | BSD |
| [python-docx](https://github.com/python-openxml/python-docx) | MIT |
| [requests](https://github.com/psf/requests) | Apache-2.0 |
| [python-markdown](https://github.com/Python-Markdown/markdown) | BSD |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD |

本仓库仅通过 pip/独立二进制形式调用上述依赖，未嵌入或修改其源码。各依赖仍保留原有许可证，相关许可证文本见对应官方仓库。

> 注意：若后续将 RapidOCR、requests 等 Apache-2.0 依赖的源码直接合并到本仓库中，需改用与 Apache-2.0 兼容的许可证（如 GPL-3.0）。

## 🙏 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 视频下载
- [RapidOCR](https://github.com/RapidAI/RapidOCR) - OCR 文字识别
- [ImageHash](https://github.com/JohannesBuchner/imagehash) - 感知哈希
- [python-docx](https://github.com/python-openxml/python-docx) - DOCX 生成
- [智谱 AI](https://open.bigmodel.cn/) - 免费视觉/文本模型（GLM-4V-Flash / GLM-4-Flash）

## 📬 反馈

- **提建议/报 Bug**：[GitHub Issues](https://github.com/rowanlin-dev/video-notes-pipeline/issues/new)
- **功能请求**：[GitHub Discussions](https://github.com/rowanlin-dev/video-notes-pipeline/discussions)

欢迎提交 Issue 和 PR！如果觉得有用的话欢迎点一下星标哟🤗
