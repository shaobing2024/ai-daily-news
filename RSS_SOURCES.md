# 中文 AI / 科技媒体 RSS 源实测清单（2026-07-18）

> 用途：作为 `news.xiaomaw.cn` 静态晨报的数据源候选。抓取方式 = 构建时拉 RSS 烘焙成静态 HTML（纯标准库 urllib + 正则即可，无需 feedparser）。
> 实测环境：Windows + curl `--ssl-no-revoke`，与 `build_daily.py` 既有方案一致。

## ✅ 实测可用（HTTP 200 + 可解析 RSS/Atom）

| 源 | RSS 地址 | 每源条数 | 偏 AI? | 是否含摘要字段 | 摘要情况 |
|---|---|---|---|---|---|
| **量子位 QbitAI** | `https://www.qbitai.com/feed` | 10 | ★★★ 纯 AI | ❌ 无 | 卡片需隐藏摘要行或改用标题截断 |
| **36氪** | `https://36kr.com/feed` | 30 | ★★ 综合科技（有 AI 专栏） | ✅ 有 | 是**全文 HTML**（平均 2500 字），需去标签+截断到 60 字 |
| **爱范儿** | `https://www.ifanr.com/feed` | 20 | ★ 消费科技 | ✅ 有 | **现成 ~49 字短摘要**，最理想 |
| **钛媒体** | `https://www.tmtpost.com/rss.xml` | 12 | ★ 科技/商业 | ✅ 有 | 全文 HTML（平均 4400 字），需截断 |
| **InfoQ 中文** | `https://www.infoq.cn/feed` | 20 | ★★ 工程师向 | ❌ 无 | 无 description |
| **人人都是产品经理** | `https://www.woshipm.com/feed` | 15 | ★ 产品/商业 | ✅ 有 | 全文 HTML（平均 3300 字），需截断 |
| **少数派** | `https://sspai.com/feed` | 10 | ★ 效率工具 | ❌ 无 | 无 description |

> 机器之心英文站 `https://syncedreview.com/feed/`（10 条）可用，但为**英文内容**，不符合"国内"定位，默认排除。

## ❌ 实测不可用（首轮探测）

| 源 | 地址 | 结果 |
|---|---|---|
| 机器之心（中文） | `https://www.jiqizhixin.com/rss` | 302 跳转到 JS 页 `/data-service`，无 RSS |
| 智东西 | `https://www.zhidx.com/feed` | HTTP 500 |
| 新智元 | `https://www.newigner.com/feed` / `xzhiyuan.com/feed` | 连接失败（000） |
| 开源中国 | `https://www.oschina.net/rss` | 404 / 非 feed |
| 极客公园 | `https://www.geekpark.net/rss` | 本环境连接失败 |
| 虎嗅 | `https://www.huxiu.com/rss/1.xml` | 本环境连接失败 |
| 雷峰网 | `https://www.leiphone.com/rss/feed` | 404 |
| CSDN | `https://blog.csdn.net/feeds.xml` | 404 |
| 品玩 | `https://www.pingwest.com/rss` | 404 |
| aibase / 差评 / 大数据文摘 / AI财经社 | 各自 feed 路径 | 无 feed / 502 |
| RSSHub 公共实例 | `https://rsshub.app/...` | 本环境全部连接失败（000），不可依赖 |

## 对仪表盘设计的影响（待确认）

1. **摘要策略**：爱范儿有现成短摘要；36氪/钛媒体/人人是全文 HTML（去标签后截 60 字）；量子位/InfoQ/少数派无 description → 卡片**隐藏摘要行**（仍含标题/来源/时间/跳转）。
2. **五版块分类**：RSS 无现成"模型/产品/行业/论文/观点"标签，需 **关键词 + 来源映射** 自行编排（用户已确认"自己编排=分类筛选"，不加点评）。
3. **去重**：跨源同题按标题/链接去重。
4. **更新频率**：静态站 = 定时重生成；可做每天 1 次，或每 4 小时一次（贴近"实时"感）。
5. **解析实现**：沿用 `build_daily.py` 的 urllib + 正则；如需更稳可在 GitHub Actions 里 `pip install feedparser`（本地仍可用正则兜底）。

## 推荐起步源（国内 AI 向，优先）
量子位（AI 主轴）+ 36氪（行业/融资）+ 爱范儿（产品）+ 钛媒体 + InfoQ + 少数派 + 人人都是产品经理。
可全部纳入，再由关键词/来源做五版块归类与去重。
