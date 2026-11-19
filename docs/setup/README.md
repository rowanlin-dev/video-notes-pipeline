# 环境搭建与运行

> 管：从零把项目跑起来需要什么、配置在哪、常见故障怎么排。
> 什么时候读：新机器、换端点、换账号、跑不出 PDF 时。

---

## 1. 依赖

| 依赖 | 必需 | 用途 |
|:--|:--|:--|
| Python 3.9+ | ✅ | 全部脚本 |
| ffmpeg | ✅ | 抽帧、合流、转音频 |
| `scripts/requirements.txt` | ✅ | requests / faster-whisper / markdown 等 |
| Edge 或 Chrome | 推荐 | PDF 渲染 |
| `openai` SDK | 可选 | 有则走 SDK，无则走 requests |
| PyAV（`av`） | 本地视频可选 | 抽帧；缺失时走 ffmpeg |

安装：

```bash
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple
pip install -r scripts/requirements.txt
```

Windows 可直接双击 `setup_windows.bat`。

---

## 2. 配置

```bash
cp .env.example .env
```

至少填视觉 Key；写正文可用独立的文本 Key：

```ini
VISION_API_KEY=
VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
VISION_MODEL=glm-4v-flash

TEXT_API_KEY=
TEXT_BASE_URL=https://api.deepseek.com
TEXT_MODEL=deepseek-chat
```

B 站官方字幕需要登录态：

```bash
cp bilibili_cookies.txt.example bilibili_cookies.txt   # 填 SESSDATA
```

---

## 3. 安装自检

```bash
python scripts/doctor.py          # 含 1 秒音频真实转写
python scripts/doctor.py --live   # 追加 Key / Cookie 连通性
```

只有 `import` 通过不算装好：PyAV 与 faster-whisper 的破坏性变更、`markdown` 缺失都只在真实执行时暴露。

---

## 4. 一次最小运行

```bash
python run_pipeline.py BV13UsH6jE4H --pages 1 --emit-brief --no-ima
# 按 output/_brief.md 写 note.md 后：
python md2pdf.py --input runs/BV13UsH6jE4H_p1/output/note.md
```

不带 `--emit-brief` 且配置了 `TEXT_*` 时，流水线会直接生成 Markdown 与 PDF。

---

## 5. 数据与产物位置

| 内容 | 位置 | 是否入库 |
|:--|:--|:--|
| 视频、帧、字幕、笔记 | `runs/` | 否 |
| ASR 模型 | `models/` | 否 |
| 字体 | `fonts/` | 否 |
| 配置与 Cookie | `.env`、`*_cookies.txt` | 否 |
| 文档 | `docs/` | 是（个人区与复盘除外） |

---

## 6. 常见故障

| 症状 | 排查 |
|:--|:--|
| B 站 412 | 用 Cookie + API 链路；不要直接抓视频页 |
| 官方字幕为空或串台 | 删掉字幕文件，走本地 ASR |
| 423/429 限流 | 降低 `VISION_WORKERS`；`--from-step 3` 重跑 |
| 抽帧 0 帧 | 用 `--mode fixed --interval N`；或确认回退已写 `scene/` |
| PDF 中文豆腐块 | 用 TTF 字体 + weasyprint 兜底，检查 `get_fonts()` |
| `python` 指向错误解释器 | 用 `doctor.py` 打印路径，显式 `py -3.12` |
| 分类总是 general | 确认 `.env` 的 `TEXT_*` 可用；看日志是否有 `[warn]` |
| 篇幅告警 | 看简报区间与正文实际字数，先判断是压缩还是注水 |

---

## 7. 平台差异

- Windows：注意控制台编码与中文路径；`runs-dir` 建议纯英文。
- macOS/Linux：ffmpeg 用包管理器安装；字体走系统或 `fonts/`。
- 无浏览器环境：PDF 走 weasyprint，需要 TTF 中文字体。
