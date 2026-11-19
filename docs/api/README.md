# CLI 与产物契约

> 管：三个入口脚本的参数、产出文件、环境变量和退出语义。
> 什么时候读：接 CI、写自动化、改参数或排查“为什么没产出”时。

---

## 1. 入口与参数

### `run_pipeline.py`（B 站）

| 参数 | 说明 |
|:--|:--|
| `<BV号>` | 必填，如 `BV13UsH6jE4H` |
| `--pages all\|1,3,5` | 多 P 选择；单 P 用 `--pages 1` |
| `--mode scene\|fixed` | 抽帧模式，默认 `scene` |
| `--interval N` | 固定间隔秒数（`fixed` 或回退用） |
| `--threshold` / `--merge-gap` | 场景灵敏度与合并窗口，操作类视频可调低 |
| `--slidegap` | 烧录字幕的 PPT 视频，提高场景阈值避开字幕 |
| `--segment-minutes` / `--max-segments` | 长视频切块 |
| `--from-step N` | 断点续跑 |
| `--emit-brief` | 只导出简报，不调用外部文本模型 |
| `--no-video` | 只下字幕，生成纯文字笔记 |
| `--source-url` | 让时间戳可跳转 |
| `--runs-dir` | 自定义输出根目录 |
| `--no-ima` / `--kb-id` / `--route` | 知识库归档开关 |

### `run_local_pipeline.py`（本地视频）

`--video`、`--title`、`--segment-minutes`、`--source-url`、`--emit-brief`、
`--asr-model-size`、`--asr-workers`、`--asr-chunk-minutes`、`--parallel-asr/--no-parallel-asr`。

### `run_xhs_pipeline.py`（小红书）

`<作品链接>`、`--title`、`--interval`、`--emit-brief`、`--redownload`。

---

## 2. 环境变量

| 变量 | 作用 |
|:--|:--|
| `VISION_API_KEY/BASE_URL/MODEL` | 帧打分与图内文字提取 |
| `TEXT_API_KEY/BASE_URL/MODEL` | 分类与写正文 |
| `VISION_WORKERS` / `VISION_MAX_RETRIES` | 视觉并发与重试 |
| `ASR_MODEL_SIZE` / `ASR_WORKERS` / `ASR_CHUNK_MINUTES` | ASR 资源控制 |
| `HF_ENDPOINT` / `HF_HUB_DISABLE_XET` | 模型下载镜像 |
| `IMA_KB_ID` | 知识库默认 ID |
| `XHS_COOKIE` | 小红书登录态（也可用 cookie 文件） |

---

## 3. 产物契约

```
runs/<id>_p<N>/
├── scene/ selected/ final/
└── output/
    ├── <标题>.md / <标题>.pdf
    ├── images/          截图 + Mermaid SVG
    ├── mermaid/*.mmd
    ├── _brief.md / _brief.json
    └── result.json
```

**不变量**

- `final/` 中每张图在正文恰好出现一次；
- 图号全篇连续唯一；
- 图注时间点必须能在原视频定位；
- PDF 由 Markdown 渲染，不单独维护。

---

## 4. `_brief.json` 关键字段

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `subject` / `subject_label` | string | 学科桶与中文名 |
| `audience` / `audience_label` | string | 受众水平与说明 |
| `target_range` | [int, int] | 篇幅区间（下限、上限） |
| `target_chars` | int | 区间中点，仅为兼容旧调用 |
| `frames[]` | array | 文件名、时间点、跳转链接、主题、图中文字、`extract_error` |
| `failed_extract` | string[] | 图内文字提取失败的帧 |
| `segments[]` | array | 长视频分段素材与分段区间 |

---

## 5. 退出语义

| 情况 | 行为 |
|:--|:--|
| 单 P 成功 | 0 |
| 某 P 失败但其他成功 | 非 0，日志标出失败分 P |
| 部分帧打分/提取失败 | 0，告警并继续 |
| 全部帧失败 | 非 0 |
| 无文本 Key 且未加 `--emit-brief` | 失败并提示两种恢复方式 |

---

## 6. 兼容性

- `compute_note_budget` 返回元组是 v1.6.3 的破坏性变更；外部脚本需按 `(lo, hi)` 解包。
- `_brief.json` 保留 `target_chars` 作为区间中点，旧读取方不会崩。
- `classify_subject` 仍可用；新代码应使用 `classify_profile`。
