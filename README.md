# AI 晨报仪表盘 · AI HOT Daily Dashboard

每日自动生成的 AI 资讯晨报单文件仪表盘，数据源为 [AI HOT](https://aihot.virxact.com)。

纯静态 HTML（内联 CSS/JS，无外部资源），通过 **GitHub Pages 免费托管**，每天**北京时间 09:00** 自动刷新。

## 功能特性

- 五大固定版块：模型发布/更新、产品发布/更新、行业动态、论文研究、技巧与观点
- 全局连续编号（跨版块不重置，1 → N）
- 顶部 Hero：日期、总条数、五版块统计；中部 sticky 锚点导航；正文响应式卡片网格
- 每张卡片含：序号、来源 chip、≤60 字中文摘要（悬停看全文）、北京时间人话时间、原文跳转（`target="_blank" rel="noopener noreferrer"`）
- 当日日报未生成时自动回退到最近一期，并在标题旁标注「当日未生成 · 回退最近一期」

## 文件结构

| 文件 | 作用 |
|---|---|
| `build_daily.py` | 一键生成脚本：抓取日报 → 补全每条发布时间 → 渲染 HTML（仅用 Python 标准库，无第三方依赖） |
| `.github/workflows/daily.yml` | GitHub Actions 定时工作流（每天 UTC 01:00 = 北京 09:00） |
| `docs/index.html` | 生成的仪表盘，GitHub Pages 发布目录 |
| `ai_daily_dashboard.html` | 本地默认输出，内容与 `docs/index.html` 一致，供本地直接双击打开 |
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
4. **访问站点**：`https://<你的用户名>.github.io/<仓库名>/`，每天 09:00（北京时间）前后自动更新。

### 工作流说明

- `on.schedule` 的 cron 为 `0 1 * * *`，这是 **UTC 时间**，对应**北京时间 09:00**。
- 可在仓库 `Actions` 页面点击 `Run workflow` 手动立即刷新。
- 工作流声明了 `permissions: contents: write`，运行后会将新生成的 `docs/index.html` 提交回仓库，Pages 随之更新。

## 说明与注意

- **为什么是「快照」而非实时**：AI HOT 接口未返回 CORS 头，浏览器端 `fetch` 会被拦截，无法做纯前端实时抓取。因此由服务端/CI 先抓取再生成静态 HTML——抓取发生在服务器（CI runner 或你本地），不受跨域限制。
- **回退机制**：若某天 09:00 当日日报尚未生成，脚本自动取最近一期，并在标题旁标注，不会中断流程。
- **定时延迟**：GitHub Actions 在高峰期调度可能延迟几分钟到几小时，对晨报场景无影响。
- **保活**：仓库 60 天无提交，GitHub 会暂停定时工作流；本工作流每天自动提交一次，可自然保活。
