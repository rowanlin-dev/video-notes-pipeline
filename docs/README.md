# 项目文档入口

> 管：这份仓库的工程文档放在哪、该读哪篇。
> 什么时候读：接手 / 改流水线 / 调提示词 / 发版 / 排查线上问题时。

> 30 秒版：**要改代码看 `designs/engineering-standards/`，要看这次改了什么看 `designs/feature-designs/`，要调参数看 `api/`，要看历史看 `changelogs/`，要跑起来看 `setup/`。**

---

## 1. 这个项目的特点（决定文档怎么裁剪）

`video-notes-pipeline` 是一个**单体 Python 流水线 + AI Skill**，不是前后端分离的 Web 系统：

- 对外交付物是 `SKILL.md`（产品说明书）与三个 CLI 入口，不是 HTTP 接口；
- 核心风险不在“模块耦合”，而在**提示词、字数预算、外部模型降级、帧选择质量**；
- 素材含第三方视频与字幕，**不能随仓库公开**；
- 仓库公开且鼓励共建，因此工程决策必须可追溯，但个人复盘与原始素材必须隔离。

所以本目录**采用母版的五类文档划分，但不照搬 12 篇工程规范**：
与前后端联调、UI 文案、分支模型相关的条款合并到 `CONTRIBUTING.md` 与本目录的 6 篇里，
代码风格单独保留一篇（`06`），因为它是公开协作的底线，不能只靠提交指南里四行字。
只在必要时保留出处。裁剪理由见 `designs/engineering-standards/README.md`。

---

## 2. 我该看哪份

| 我想知道 | 去看 |
|:--|:--|
| 现在还剩什么没做 | `designs/README.md` 的任务台账 |
| 这次改了什么、为什么 | `designs/feature-designs/2026-11-19-篇幅预算与分类修复/` |
| 永远要遵守的流水线规矩 | `designs/engineering-standards/README.md` |
| 字数/受众/分类怎么算 | `designs/engineering-standards/02-笔记篇幅预算.md`、`03-学科分类与受众适配.md` |
| CLI 参数与产物契约 | `api/README.md` |
| 历史上改过什么 | `changelogs/` |
| 怎么装、怎么跑、怎么排错 | `setup/README.md` |
| 某块子系统怎么维护 | `designs/module-docs/` |
| 产品用法与完整参数 | 根目录 `SKILL.md`（唯一产品说明） |

---

## 3. 目录地图

```
docs/
├── README.md                     ← 本文件
├── designs/
│   ├── README.md                 ← 索引 + 任务台账（唯一真相源）
│   ├── engineering-standards/    ← 6 篇长期约束（裁剪版）
│   ├── feature-designs/          ← 迭代：计划、方案、实验
│   └── module-docs/              ← 核心模块维护手册
├── api/                          ← CLI / 产物 / 环境变量契约
├── changelogs/                   ← 一次发版一个文件 + 索引
├── setup/                        ← 从零跑起来
├── retro/                        ← 复盘（不入库，见 §5）
└── personal-docs/                ← 个人区（不入库，AI 不必读）
```

---

## 4. 三条硬规则

1. **计划与实际分离**：动手前写在 `feature-designs/<迭代>/01`、`02`；上线后写 `changelogs/`，不把“打算做”写进变更记录。
2. **同一内容只留一处**：产品用法只在 `SKILL.md`；工程细节只在 `docs/`。两处冲突时以各自领域的唯一来源为准，另一处改成指针。
3. **变更记录标注 `[影响文档]`**：改代码后逐条核对受影响的文档是否现存且最新。

---

## 5. 公开与私有边界

本仓库公开，但以下内容**不随仓库发布**（已在根 `.gitignore` 中）：

| 内容 | 原因 |
|:--|:--|
| `.env`、`bilibili_cookies.txt`、`xiaohongshu_cookies.txt` | 密钥与登录态 |
| `runs/`、`*.mp4`、`*.pdf`、`*.html` | 第三方视频、截图、字幕与生成物，有版权与体积问题 |
| `models/`、`fonts/` | 大文件，按需下载 |
| `docs/retro/` | 个人成果叙事，不面向社区 |
| `docs/personal-docs/` | 个人笔记，明确宣告 AI 与协作方不必读 |
| `user_config*`、`*.local.*`、`.skill_backup/` | 端点本地优化与备份 |

可以公开、并且应当公开的：`SKILL.md`、`docs/` 下除上述两类外的全部文档、`scripts/`、测试与 `CONTRIBUTING.md`。

> 实验记录中引用真实视频时，只写标题、BV 号、时间点与结论；**不要贴字幕全文或截图**。
