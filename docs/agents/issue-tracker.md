# Issue tracker: GitHub

Issues 和 specs 保存到 `zhizhuotan8-cpu/TrendRadar-LLM` 的 GitHub Issues。

所有 `gh issue`、`gh label`、`gh repo` 命令必须显式指定：
`--repo zhizhuotan8-cpu/TrendRadar-LLM`。
对于使用仓库位置参数的命令（如 `gh repo view`），使用位置参数 `zhizhuotan8-cpu/TrendRadar-LLM`。

GitHub API 路径必须使用 `repos/zhizhuotan8-cpu/TrendRadar-LLM/...`。

创建多行正文时使用 `--body-file`。
子任务优先使用 GitHub 原生 sub-issues；不可用时使用父任务清单和 `Part of #<parent>`。
依赖优先使用原生 issue dependencies；不可用时在正文记录 `Blocked by: #<number>`。

关闭任务前先发表评论说明处理结果。
发布任务即创建 GitHub Issue；读取任务即读取对应 Issue。

PRs as a request surface: no.

## Wayfinding operations

Wayfinder 使用 `wayfinder:map` 保存地图，使用 `wayfinder:research`、
`wayfinder:prototype`、`wayfinder:grilling`、`wayfinder:task` 标记子任务。
