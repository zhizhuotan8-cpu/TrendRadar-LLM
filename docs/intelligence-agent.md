# 大模型情报 Agent：运行与部署

领域功能使用独立 SQLite 数据库，原有热榜/RSS 历史库保持不变。入口为
`python -m trendradar.intelligence`，配置见 `config/intelligence.yaml`。

## 环境

使用 Python 3.12 或更新版本，在仓库根目录执行：

```powershell
uv sync --frozen
uv pip install pytest
.venv\Scripts\python.exe -m pytest tests -q
```

当前工作树已建好 `.venv`（Python 3.12.16）。不要使用原 F 盘 Python 3.11 环境运行本功能。
工作树的 uv 可执行文件为 `.tools\bin\uv.exe`。依赖以 `uv.lock` 为准，直接解析最新间接依赖曾导致 MCP/Pydantic 不兼容。

服务端读取以下环境变量；不要把密钥写入 YAML、网页、报告或 Git：

| 变量 | 用途 |
| --- | --- |
| `AI_API_KEY` | 模型服务密钥 |
| `AI_MODEL` | LiteLLM 模型名，如 `deepseek/deepseek-chat` |
| `AI_API_BASE` | 可选兼容接口地址 |
| `JINA_API_KEY` | 正文读取服务密钥；本次匿名访问返回 401 |
| `BRAVE_SEARCH_API_KEY` | 网页追问的联网搜索密钥 |
| `FEISHU_WEBHOOK_URL` | 飞书机器人地址 |
| `HTTPS_PROXY` | 可选网络代理，如本机已运行的代理地址 |

模型和搜索请求仅发生在服务端。[Brave API 文档](https://api-dashboard.search.brave.com/api-reference/web/search/get)
定义的 GET 接口和请求头用于搜索适配器；搜索摘要不作为已读正文证据。

## 手动运行与自动调度

```powershell
# 采集、读正文、分析、保存报告，不发送消息
.venv\Scripts\python.exe -m trendradar.intelligence daily

# 同时发送已经保存的简报
.venv\Scripts\python.exe -m trendradar.intelligence daily --send

# 长期运行，每日北京时间 09:00 起执行，开启飞书发送
.venv\Scripts\python.exe -m trendradar.intelligence daemon --send

# 在另一个终端启动本机网页
.venv\Scripts\python.exe -m trendradar.intelligence serve
```

网页默认地址 `http://127.0.0.1:8765`。`/reports` 查看归档，首页追问；会话历史存于 SQLite。
网页没有多用户认证，只绑定回环地址，不能直接用端口转发暴露公网。

daemon 每 60 秒检查一次北京时间，09:00 后启动采集与分析，实际送达取决于网络与生成耗时，
不是精确到秒的送达保证。进程未运行或电脑休眠时无法执行；恢复后当天 09:00 之后会补跑。
生产部署应由系统服务管理 daemon 和网页进程，并设置工作目录为仓库根目录。
一次只允许一个每日运行 worker；文件锁避免重复启动。网页可以同时运行。

配置 `feeds` 支持 RSS/Atom/JSON Feed，`source_kind` 为 official/community/personal/unknown。
`hotlists` 可填 `id` 和 `source_kind`，使用已有 NewsNow 适配器；默认关闭综合热榜。
正文阅读和分析过程中不会根据来源页面中的指令执行工具。

## 报告、投递与恢复

- 数据库默认 `output/intelligence/domain.db`，当前 schema 版本 5；启动自动事务迁移。
- 网页 HTML 保存在数据库及 `output/intelligence/reports/YYYY-MM-DD.html`。
- `last-run.json` 保存最近一次运行预算及未解决问题。
- 同日已经生成的报告保持不变；重试发送复用该报告，不生成新版本。
- 同一事件版本只进入一个报告；未入选的版本仍保留供下一日报告使用。
- 只有成功发送的报告才计入 `covered_versions()`；失败不会推进覆盖记录。
- 发送结果为 `uncertain` 时，可能是部分批次已经送达、响应丢失或请求失败；不会自动重发。
- worker 启动后将上次中断的 `sending` 状态改为 `uncertain`。

确认需要重发后，以下命令仅发送已保存报告，不依赖模型服务：

```powershell
.venv\Scripts\python.exe -m trendradar.intelligence retry --retry-uncertain
```

该命令可能重复发送已到达飞书的内容，外部 webhook 无法保证严格 exactly-once。
备份时停止 worker 和网页，复制 SQLite 文件；迁移前建议备份，不能用旧代码打开更高版本数据库。

## 预算与信息不足

每日运行和每次追问各有独立 Budget，失败调用也计数，调用前检查限额并传入剩余超时。
模型禁用隐藏重试和 fallback。输出 token 统计是预留上限，不是实际计费量或金额承诺。
正文读取含节流等待，HTTP 超时由底层网络库执行；预算不能中断不遵守超时的第三方实现。

预算耗尽保留已完成记录并披露限制。聊天仅展示来源 ID、快照 ID 与逐字引文匹配的结论；
不存在的引用被拒绝。引文匹配不能证明语义推理一定正确。

事件关联依赖模型生成的具体事件/变化标识，低于 0.85 置信度不自动合并；
重复或漏合并仍需真实样本评估。候选事件上限 50，聊天本地检索上限 100 个近期正文快照，
长正文按节选分析。简报按工程价值 1–5 分排序，最多 10 项，不凑条目。

## 验证记录（2026-11-09）

在本机 HTTPS 代理下的公开来源检查：

| 来源 | HTTP | RSS 解析条数 | 用时 |
| --- | --- | --- | --- |
| OpenAI news/rss.xml | 200 | 1368 | 3.19 秒 |
| Hugging Face blog/feed.xml | 200 | 900 | 1.98 秒 |
| arXiv cs.AI | 200 | 397 | 11.88 秒 |

补充来源检查：Simon Willison Atom 返回 200、解析 30 项；阮一峰 Atom 返回 200、解析 3 项。
量子位和开源中国 RSS 在本次网络环境返回 403，未放入默认配置。
默认每源最多 2 项，5 个来源最多 10 个候选，避免前两个来源占满 12 次模型调用预算。
中文综合工程来源仍需经过领域筛选，并不保证每期都提供大模型领域的新信息。

各取一篇测试 Jina 正文读取，均为 HTTP 401：

- `https://openai.com/index/partnering-with-hacktron`
- `https://huggingface.co/blog/amazon/higher-order-pruning-experts`
- `https://arxiv.org/abs/2611.08572`

当前执行环境未提供 AI、Brave、飞书或 Jina 凭据，因此**尚未完成真实模型质量、联网追问、
飞书实际投递和真实流量预算校准**。默认预算是初始值，不能当作校准结论。
离线测试覆盖采集到报告的流水线、迁移、引用校验、预算、HTTP 网页、失败恢复和飞书适配。

具备凭据后，应保存一组中英文新闻、教程、开源项目及论文样本，人工标注重复事件、不同发布及
实质后续变化，记录误合并/漏合并、重要信息召回、价值排序和引用有效性，再调整预算与置信阈值。
Issue #1 在这些外部验收完成前不能认定整体完成。
