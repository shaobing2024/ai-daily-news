# AI 每日新闻 · 中文 AI 资讯聚合仪表盘

每日自动抓取多个**中文科技/AI 媒体 RSS**，聚合、分类、去重后生成单文件仪表盘。
纯静态 HTML（内联 CSS/JS，无外部资源），通过 **GitHub Pages 免费托管**，每 **6 小时**自动刷新。

## 功能特性

- 五大固定版块：模型发布/更新、产品发布/更新、行业动态、论文研究、技巧与观点（按关键词 + 来源自动归类）
- 全局连续编号（跨版块不重置，1 → N）
- 顶部 Hero：日期、总条数、五版块统计；中部 sticky 锚点导航；正文响应式卡片网格
- 每张卡片含：序号、来源 chip、≤60 字中文摘要（若 RSS 源提供，否则隐藏摘要行）、北京时间人话时间、原文跳转（`target="_blank" rel="noopener noreferrer"`）
- 跨源自动去重（同题多源只保留一条）

## 数据源（偏 AI 的 4 个，实测可用）

| 源 | RSS |
|---|---|
| 量子位 | `https://www.qbitai.com/feed` |
| 36氪 | `https://36kr.com/feed` |
| InfoQ 中文 | `https://www.infoq.cn/feed` |
| 爱范儿 | `https://www.ifanr.com/feed` |

> 抓取发生在构建时（CI runner 或你本地），因此不受浏览器跨域（CORS）限制。
> 想增减源：编辑 `build_daily.py` 顶部的 `SOURCES` 列表即可。

## 文件结构

| 文件 | 作用 |
|---|---|
| `build_daily.py` | 一键生成脚本：抓取多源 RSS → 关键词分类 → 去重 → 渲染 HTML（仅用 Python 标准库，无第三方依赖） |
| `.github/workflows/daily.yml` | GitHub Actions 定时工作流（每 6 小时：`0 */6 * * *` UTC） |
| `docs/index.html` | 生成的仪表盘，GitHub Pages 发布目录 |
| `ai_daily_dashboard.html` | 本地默认输出，内容与 `docs/index.html` 一致，供本地直接双击打开 |
| `RSS_SOURCES.md` | 中文 RSS 源实测清单（可用源、字段情况、不可用源及设计取舍） |
| `.gitignore` | 忽略本地记忆目录与临时抓取文件 |

## 本地运行

```bash
# 无需 pip install —— 仅用 Python 标准库（urllib）
python build_daily.py                                     # 输出 ai_daily_dashboard.html
AI_DAILY_OUTPUT=docs/index.html python build_daily.py     # 输出到 docs/ 供 Pages 使用
```

> Windows PowerShell 设置环境变量：
> ```powershell
> $env:AI_DAILY_OUTPUT = "docs/index.html"; python build_daily.py
> ```

## 部署到 GitHub Pages（免费 · 全自动）

1. **新建仓库**：在 GitHub 新建一个**公开（Public）**仓库，例如 `ai-daily`。
2. **推送代码**：本目录已 `git init` 并提交，添加远程后推送：
   ```bash
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```
3. **开启 Pages**：仓库 `Settings → Pages → Source: Deploy from a branch → Branch: main → 目录 /docs` → 保存。
4. **绑定自定义域名（可选）**：`docs/CNAME` 已写入 `news.xiaomaw.cn`；在域名 DNS 加 CNAME 记录（主机 `news` → `<你的用户名>.github.io.`），再于 Pages 填写自定义域名并勾选 `Enforce HTTPS`。
5. **访问站点**：`https://news.xiaomaw.cn/`（或 `https://<你的用户名>.github.io/<仓库名>/`），每 6 小时自动更新。

### 工作流说明

- `on.schedule` 的 cron 为 `0 */6 * * *`，这是 **UTC 时间**，即每 6 小时一次（北京时间 08 / 14 / 20 / 02 点）。
- 可在仓库 `Actions` 页面点击 `Run workflow` 手动立即刷新。
- 工作流声明了 `permissions: contents: write`，运行后会将新生成的 `docs/index.html` 提交回仓库，Pages 随之更新。
- 推送前会 `git pull --rebase`，避免设置自定义域名时与 GitHub 提交的 `CNAME` 冲突。

## 说明与注意

- **为什么是「快照」而非秒级实时**：纯静态站只能在「构建时」抓取 RSS 烘焙成 HTML。每 6 小时重生成一次，已贴近「实时感」；如需真·秒级实时需改为服务端动态渲染。
- **摘要字段**：爱范儿等源自带短摘要；36氪/钛媒体等源为全文 HTML（已去标签并截断到 60 字）；量子位/InfoQ 等源无 description，卡片自动隐藏摘要行。
- **定时延迟**：GitHub Actions 在高峰期调度可能延迟几分钟到几小时，对资讯聚合场景无影响。
- **保活**：仓库 60 天无提交，GitHub 会暂停定时工作流；本工作流每 6 小时自动提交一次，可自然保活。
- **本地抓取注意**：部分 RSS 源对同一 IP 频繁请求会限流并截断响应；正常部署在 GitHub Actions（独立 IP）不受此影响。脚本已做源间节流与一次重试。
