# 贡献指南

感谢你对 Bilibili Video Notes 的关注！

## 提建议 / 报 Bug

1. 在 [Issues](https://github.com/rowanlin-dev/video-notes-pipeline/issues) 页面创建新 Issue
2. 描述你的建议或遇到的问题
3. 如果是 Bug，请附上错误信息和复现步骤

## 分支策略

本仓库只有一条长期分支 **`main`**（不设 `develop`），它始终处于可运行状态。`main` 已开启分支保护：

- 必须通过 Pull Request 合入，至少 1 个 approval
- 禁止 force push、禁止删除分支
- 合并前需要解决所有 review 评论
- 维护者（admin）保留紧急情况下的直推权限

因此外部贡献者**不能**直接向 `main` 推送，请按下面的 fork + PR 流程操作。

## 提交代码（fork + PR）

1. **Fork** 本仓库，克隆你自己的 fork：
   ```bash
   git clone https://github.com/<你的用户名>/video-notes-pipeline.git
   cd video-notes-pipeline
   git remote add upstream https://github.com/rowanlin-dev/video-notes-pipeline.git
   ```
2. **从最新 main 开分支**（分支名用 `<type>/<主题>`，与提交规范一致）：
   ```bash
   git fetch upstream
   git switch -c feat/xhs-note-cover upstream/main
   ```
   `type` 取值：`feat` 新功能 / `fix` 修复 / `docs` 文档 / `refactor` 重构 / `chore` 版本与依赖。
3. **提交**，一个提交只做一件事，标题格式 `<type>: <中文说明>`：
   ```bash
   git add <按文件精确暂存，不要 git add -A>
   git commit -m "fix: 修复 md2pdf 图片在 div 内不渲染"
   ```
4. **推送并开 PR**（目标分支选 `rowanlin-dev/video-notes-pipeline` 的 `main`）：
   ```bash
   git push origin feat/xhs-note-cover
   ```
   PR 描述写清：**改了什么、为什么改、怎么验证**（附运行命令或截图）。
5. **合并方式为 squash**，多条中间提交会被压成一条，所以不必在本地反复 rebase 整理历史。

> 分支保护生效后，PR 通过前不要 force push 到自己的分支以外的地方；需要同步上游时用 `git rebase upstream/main`，不要 merge 出一个交叉历史。

## 代码风格

- 保持简洁，避免冗余
- 新增脚本请在顶部添加清晰的 docstring
- 不要在代码中硬编码个人 API key 或 Cookie
- 修改后运行 `python -m py_compile scripts/*.py` 确认语法正确

## 改进笔记质量

如果你发现了更好的截图选择策略、更清晰的排版方式，或者任何能让笔记质量更高的方法，欢迎提交 PR！

## 需要注意的事项

- 不要将 `.env` 或 `bilibili_cookies.txt` 提交到 Git
- 不要提交视频文件、帧图片、字幕文件等大文件
- 不要在文档中写入个人路径或隐私信息
- 更新 README 和相关 Agent 文件（SKILL.md / CLAUDE.md / AGENTS.md）保持一致

## 联系方式
- **提建议/报Bug**：[GitHub Issues](https://github.com/rowanlin-dev/video-notes-pipeline/issues/new)
- **联系邮箱**：pluto_wangyi@126.com

欢迎提交 Issue 和 PR！
