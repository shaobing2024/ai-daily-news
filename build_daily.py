# -*- coding: utf-8 -*-
"""
build_daily.py — 一键生成「中文 AI 新闻聚合」晨报仪表盘（单文件 HTML）

流程：
  1. 抓取多个中文科技/AI 媒体 RSS（构建时拉取，烘焙成静态 HTML）。
  2. 解析每条：标题、原文链接、发布时间（转北京时间）、摘要（若有）。
  3. 按关键词 + 来源规则归入五大固定版块（模型/产品/行业/论文/观点）。
  4. 跨源去重，版块内按时间倒序，全局连续编号。
  5. 生成单文件 HTML（内联 CSS/JS，无外部资源，响应式）：含 Hero 统计、
     锚点导航、响应式卡片网格、Open Graph 分享标签与 emoji favicon。

数据源（偏 AI 的 5 个，实测可用）：量子位 / IT之家 / InfoQ 中文 / 爱范儿 / 开源中国。
用法：
  python build_daily.py
  AI_DAILY_OUTPUT=docs/index.html python build_daily.py   # 输出到 docs/ 供 GitHub Pages
输出：默认与本脚本同目录的 ai_daily_dashboard.html；可用 AI_DAILY_OUTPUT 覆盖。
"""
import json
import io
import os
import re
import gzip
import time
import html
import ssl
import email.utils
import datetime
import urllib.request
import urllib.error
import urllib.parse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
_out = os.environ.get("AI_DAILY_OUTPUT")
if _out:
    OUT_HTML = _out if os.path.isabs(_out) else os.path.join(HERE, _out)
else:
    OUT_HTML = os.path.join(HERE, "ai_daily_dashboard.html")

# 偏 AI 的 5 个中文源（2026-07-18 实测 HTTP 200 + 可解析）
SOURCES = [
    ("量子位", "https://www.qbitai.com/feed"),
    ("IT之家", "https://www.ithome.com/rss/"),
    ("InfoQ 中文", "https://www.infoq.cn/feed"),
    ("爱范儿", "https://www.ifanr.com/feed"),
    ("开源中国", "https://www.oschina.net/news/rss"),
]

# 五大固定版块（顺序即展示顺序，亦为全局编号顺序）
SECTIONS = ["模型发布/更新", "产品发布/更新", "行业动态", "论文研究", "技巧与观点"]

# 关键词分类（命中即归入对应版块；都不中 → 行业动态）
KW_MODEL = ["模型", "大模型", "llm", "gpt", "开源", "训练", "参数", "预训练", "微调",
            "蒸馏", "多模态", "基座", "推理模型", "agent模型", "基座模型", "涌现"]
KW_PAPER = ["论文", "研究", "arxiv", "期刊", "实验", "算法", "基准", "评测", "数据集",
            "nature", "science", "icml", "neurips", "iclr", "综述", "突破", "基准测试"]
KW_TIPS = ["教程", "怎么", "如何", "技巧", "指南", "实战", "盘点", "观点", "思考", "建议",
           "经验", "解读", "一文", "速通", "入门", "为什么", "怎么看", "干货", "方法", "聊聊"]
KW_PRODUCT = ["产品", "app", "应用", "工具", "功能", "上线", "公测", "内测", "插件", "助手",
              "智能体", "agent", "机器人", "设备", "手机", "软件", "平台", "服务", "小程序"]

# AI 相关性硬过滤：只保留含 AI 专属词的条目。注意——这里绝不能使用上面分类用的泛词
# （产品/应用/工具/手机/软件/平台…），否则会把手机、App 等非 AI 新闻误放行。
# 英文词做词边界匹配，避免 agent 误中 management、ai 误中 openai 内部等。
KW_AI = [
    # 通用 / 概念
    "ai", "aigc", "agi", "人工智能", "生成式", "生成式ai", "智能体", "agent", "agentic",
    "大模型", "llm", "多模态", "基座模型", "推理模型", "开源模型", "预训练", "微调",
    "对齐", "rlhf", "涌现", "蒸馏", "参数", "transformer", "扩散模型", "提示词", "prompt",
    "rag", "向量", "具身", "算力", "机器学习", "深度学习", "神经网络",
    # 模型 / 产品名
    "gpt", "chatgpt", "claude", "gemini", "llama", "mistral", "qwen", "deepseek",
    "kimi", "glm", "文心", "通义", "豆包", "百川", "智谱", "混元", "copilot",
    "midjourney", "sora", "stable diffusion", "文生图", "文生视频", "数字人",
    # 公司与芯片
    "openai", "anthropic", "deepmind", "xai", "英伟达", "nvidia", "昇腾", "h100", "h200", "a100",
    "百度智能云", "阿里通义", "腾讯混元", "月之暗面",
]
_AI_LATIN = [k for k in KW_AI if re.fullmatch(r"[A-Za-z0-9.+]+", k)]
_AI_CJK = [k for k in KW_AI if k not in _AI_LATIN]
_AI_PATTERNS = [r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])" for k in _AI_LATIN]


# 标题排除：特定聚合/栏目类文章（整条丢弃，不进版块）。
# 如 IT之家的「IT早报」、爱范儿的「早报｜…」每日汇总，内容杂、非单条新闻，故不收录。
# 关键词用「早报」即可同时覆盖上述两类早报栏目。
TITLE_EXCLUDE = ["早报"]


def is_ai_related(text):
    t = (text or "").lower()
    for k in _AI_CJK:
        if k in t:
            return True
    for p in _AI_PATTERNS:
        if re.search(p, t):
            return True
    # agent 兼容复合词（如 ReActAgent），但排除 management / engagement 等非 AI 词
    if "agent" in t and not any(b in t for b in ("management", "engagement", "embed", "percentage")):
        return True
    return False


# ----------------------------------------------------------------------------
# 网络层
# ----------------------------------------------------------------------------
def fetch_text(url):
    # 显式声明不压缩，避免 urllib 不自动解 gzip/br 导致拿到乱码
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            raw = r.read()
            charset = r.headers.get_content_charset()
            encoding = r.headers.get("Content-Encoding", "")
    except urllib.error.URLError as e:
        # Windows schannel 偶发证书吊销检查失败，退化为不校验（仅抓取公开 RSS）
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            ctx2 = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=25, context=ctx2) as r:
                raw = r.read()
                charset = r.headers.get_content_charset()
                encoding = r.headers.get("Content-Encoding", "")
        else:
            raise
    if "gzip" in encoding.lower():
        raw = gzip.decompress(raw)
    for enc in [charset, "utf-8", "gbk", "gb18030"]:
        if enc:
            try:
                return raw.decode(enc)
            except Exception:
                pass
    return raw.decode("utf-8", "replace")


# ----------------------------------------------------------------------------
# RSS 解析
# ----------------------------------------------------------------------------
def _strip_tags(s):
    if not s:
        return ""
    # 先剥 CDATA 包裹（若有），再解码 HTML 实体（部分源如 InfoQ 把整段 HTML
    # 用 &lt; &gt; &#39; 转义后塞进 description），否则标签无法被正确剥离。
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _field(block, tags):
    for t in tags:
        m = re.search(rf"<{t}\b[^>]*>(.*?)</{t}>", block, re.S | re.I)
        if m:
            v = _strip_tags(m.group(1))
            if v:
                return v
    return ""


def _link_of(block):
    # Atom: <link href="..." rel="alternate">
    for l in re.findall(r"<link\b[^>]*>", block, re.I):
        href = re.search(r'href="([^"]+)"', l)
        rel = re.search(r'rel="([^"]+)"', l)
        if href and (not rel or "alternate" in rel.group(1) or "self" not in rel.group(1)):
            return href.group(1)
    # RSS: <link>url</link>
    m = re.search(r"<link[^>]*>([^<]+)</link>", block, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # guid
    g = _field(block, ["guid"])
    if g:
        return g
    return ""


def _parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        return None


def parse_feed(source, text):
    items = []
    for block in re.findall(r"<item[ >].*?</item>|<entry[ >].*?</entry>", text, re.S | re.I):
        title = _field(block, ["title"])
        link = _link_of(block)
        if not title or not link:
            continue
        desc = _field(block, ["description", "content:encoded", "summary", "content"]) or None
        pub = _parse_date(_field(block, ["pubDate", "published", "updated", "dc:date"]))
        items.append({
            "title": title,
            "link": link,
            "summary": desc,            # 可能为 None（量子位/InfoQ/少数派 无 description）
            "publishedAt": pub,
            "source": source,
        })
    return items


# ----------------------------------------------------------------------------
# 分类 + 去重 + 分组
# ----------------------------------------------------------------------------
def classify(text):
    t = (text or "").lower()
    if any(k in t for k in KW_MODEL):
        return "模型发布/更新"
    if any(k in t for k in KW_PAPER):
        return "论文研究"
    if any(k in t for k in KW_TIPS):
        return "技巧与观点"
    if any(k in t for k in KW_PRODUCT):
        return "产品发布/更新"
    return "行业动态"


def build_data():
    all_items = []
    for idx, (name, url) in enumerate(SOURCES):
        if idx > 0:
            time.sleep(1.5)  # 源间节流，避免被 RSS 服务端限流导致响应被截断
        text = None
        last_err = None
        for attempt in range(2):  # 一次重试，规避偶发网络抖动
            try:
                text = fetch_text(url)
                break
            except Exception as e:
                last_err = e
        if not text:
            print(f"  [跳过] {name} 抓取失败: {last_err}")
            continue
        try:
            its = parse_feed(name, text)
            all_items.extend(its)
            print(f"  抓取 {name}: {len(its)} 条")
        except Exception as e:
            print(f"  [跳过] {name} 解析失败: {e}")

    # 跨源去重（按标题归一化）
    seen, unique = set(), []
    for it in all_items:
        key = re.sub(r"[\s\W_]+", "", it["title"]).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(it)

    # AI 相关性过滤：与 AI 无关的整条丢弃（不进任何版块）
    before = len(unique)
    unique = [it for it in unique if is_ai_related(it["title"] + " " + (it["summary"] or ""))]
    if before - len(unique):
        print(f"  AI 过滤: 丢弃 {before - len(unique)} 条非 AI 相关")

    # 标题排除：丢弃特定聚合/栏目类文章（如 IT之家的「IT早报」每日汇总，内容杂且不单列）
    before = len(unique)
    unique = [it for it in unique if not any(x in it["title"] for x in TITLE_EXCLUDE)]
    if before - len(unique):
        print(f"  标题排除: 丢弃 {before - len(unique)} 条（{', '.join(TITLE_EXCLUDE)} 等）")

    groups = {s: [] for s in SECTIONS}
    for it in unique:
        sec = classify(it["title"] + " " + (it["summary"] or ""))
        groups[sec].append(it)
    # 版块内按发布时间倒序（无时间排最后）
    for s in groups:
        groups[s].sort(key=lambda x: x["publishedAt"] or "", reverse=True)

    sections = []
    for s in SECTIONS:
        items = [{
            "title": it["title"],
            "summary": it["summary"] or "",
            "sourceName": it["source"],
            "sourceUrl": it["link"],
            "publishedAt": it["publishedAt"],
        } for it in groups[s]]
        sections.append({"label": s, "items": items})

    bj_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    data = {
        "date": bj_now.strftime("%Y-%m-%d"),
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "attribution": {"source": "中文科技媒体 RSS 聚合"},
        "sourceList": [n for n, _ in SOURCES],
        "lead": "",
        "isFallback": False,
        "sections": sections,
    }
    return data


# ----------------------------------------------------------------------------
# 渲染层
# ----------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__OG_TITLE__</title>
<meta name="description" content="__OG_DESC__">
<meta property="og:title" content="__OG_TITLE__">
<meta property="og:description" content="__OG_DESC__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="小马AI 每日新闻">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%23ffffff'/><path d='M16 5c6.075 0 11 4.925 11 11s-4.925 11-11 11S5 22.075 5 16 9.925 5 16 5z' fill='none' stroke='%231b1d1f' stroke-width='2'/><path d='M9 22V11l7 8 7-8v11' fill='none' stroke='%231b1d1f' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>">
<style>
  :root{
    --bg:#f4f5f2;
    --panel:#ffffff;
    --ink:#1b1d1f;
    --muted:#737670;
    --line:#e6e7e2;
    --hair:#d8d9d3;
    --brand:#2f6f8f;
    --shadow:0 1px 2px rgba(20,28,24,.04),0 8px 24px rgba(20,28,24,.05);
    /* 低饱和、无红无紫的编辑式配色 */
    --c1:#3a6b7e;  /* 模型发布/更新 · 青蓝 */
    --c2:#5a7d5a;  /* 产品发布/更新 · 苔绿 */
    --c3:#9c7b3f;  /* 行业动态 · 赭石 */
    --c4:#2f7a72;  /* 论文研究 · 青绿 */
    --c5:#6b7a5e;  /* 技巧与观点 · 橄榄 */
    --serif:"Songti SC","STSong","Noto Serif CJK SC","Source Han Serif SC","SimSun",Georgia,"Times New Roman",serif;
    --sans:"PingFang SC","Microsoft YaHei","Hiragino Sans GB",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box;}
  html{scroll-behavior:smooth;}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:var(--sans); line-height:1.65; -webkit-font-smoothing:antialiased;
    text-rendering:optimizeLegibility;
  }
  .wrap{max-width:1120px; margin:0 auto; padding:0 20px 72px;}

  /* —— 报头 / Masthead —— */
  .hero{
    background:var(--panel); color:var(--ink);
    border-bottom:1px solid var(--line);
    border-top:3px solid var(--brand);
    padding:52px 20px 40px; margin-bottom:0;
    text-align:center;
  }
  .hero-inner{max-width:760px; margin:0 auto;}
  .masthead{display:flex; flex-direction:column; align-items:center;}
  .logo{
    font-family:var(--serif); font-weight:700; font-size:30px; letter-spacing:.04em;
    color:var(--ink); margin-bottom:14px; line-height:1; padding-bottom:12px;
    border-bottom:2px solid var(--brand);
  }
  .kicker{
    font-size:12px; letter-spacing:.22em; text-transform:uppercase;
    color:var(--muted); margin:0 0 10px; font-weight:600;
  }
  .hero h1{
    margin:0; font-family:var(--serif); font-weight:700;
    font-size:clamp(30px,4.8vw,44px); line-height:1.1; letter-spacing:.01em;
  }
  .tagline{
    margin:12px 0 0; color:var(--muted); font-size:14.5px; font-weight:400;
  }
  .hero-date{
    margin:8px 0 0; font-size:12.5px; color:var(--muted); letter-spacing:.02em;
  }
  .badge-fallback{display:inline-block; margin-left:8px; font-size:11px; font-weight:700;
    background:#fdf3e7; color:#9c7b3f; border:1px solid #ecd9b8; padding:2px 8px; border-radius:999px; vertical-align:middle;}

  /* 报头统计条：居中、无彩色块 */
  .stat-row{
    display:flex; justify-content:center; flex-wrap:wrap;
    gap:14px 42px; margin-top:28px; padding-top:22px;
    border-top:1px solid var(--hair); width:100%;
  }
  .stat{background:none; border:none; padding:0; min-width:auto; flex:0 0 auto; text-align:center;}
  .stat .num{font-family:var(--serif); font-size:clamp(26px,3.4vw,34px); font-weight:700; line-height:1; color:var(--ink);}
  .stat .lbl{font-size:12.5px; color:var(--muted); margin-top:7px; letter-spacing:.02em;}
  .stat.total .num{font-size:clamp(30px,4vw,42px); color:var(--brand);}

  .hero-meta{
    margin:26px 0 0; font-size:13px; color:var(--muted); letter-spacing:.02em; line-height:1.7;
  }
  .hero-meta a{color:var(--brand); text-decoration:none;}
  .hero-meta a:hover{text-decoration:underline;}

  .lead{
    background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--brand);
    border-radius:3px; padding:16px 18px; margin:24px 0 0; box-shadow:var(--shadow);
    font-size:14.5px; color:#3a4036; line-height:1.75;
  }
  .lead .lead-tag{display:block; font-size:11.5px; font-weight:700; color:var(--brand); letter-spacing:.1em; margin-bottom:6px; text-transform:uppercase;}

  /* —— 导航 —— */
  .nav{
    position:sticky; top:0; z-index:20; background:rgba(255,255,255,.92);
    border:1px solid var(--line); border-radius:3px;
    display:flex; flex-wrap:wrap; gap:7px; padding:9px 11px; margin:24px 0 30px; box-shadow:var(--shadow);
  }
  .nav a{
    text-decoration:none; color:var(--ink); font-size:13px; font-weight:600;
    padding:6px 12px; border-radius:3px; border:1px solid transparent; background:transparent; transition:.15s; white-space:nowrap;
  }
  .nav a:hover{background:#f3f4f0; border-color:var(--line);}
  .nav a .cnt{color:var(--muted); font-weight:700; margin-left:6px;}

  .section{margin-bottom:42px; scroll-margin-top:74px;}
  .section-head{display:flex; align-items:baseline; gap:12px; margin:0 0 18px; padding-bottom:11px; border-bottom:1px solid var(--ink);}
  .section-head .bar{width:4px; height:22px; border-radius:2px; background:var(--accent);}
  .section-head h2{margin:0; font-family:var(--serif); font-size:clamp(19px,2.4vw,23px); font-weight:700; letter-spacing:.01em;}
  .section-head .count{margin-left:auto; color:var(--muted); font-size:13.5px; font-weight:600;}

  .grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:16px;}
  .card{
    background:var(--panel); border:1px solid var(--line); border-radius:3px; padding:18px 18px 16px;
    box-shadow:var(--shadow); position:relative; display:flex; flex-direction:column; transition:.15s ease; border-top:2px solid var(--accent,#ccc);
  }
  .card:hover{background:#fcfcf9; border-color:var(--hair);}
  .card .top{display:flex; align-items:center; gap:10px; margin-bottom:11px;}
  .badge{
    flex:0 0 auto; width:28px; height:28px; border-radius:3px; background:var(--accent,#2f6f8f);
    color:#fff; font-weight:700; font-size:13px; font-family:var(--serif); display:flex; align-items:center; justify-content:center;
  }
  .chip{
    margin-left:auto; font-size:11.5px; font-weight:600; color:var(--accent,#2f6f8f);
    background:color-mix(in srgb,var(--accent,#2f6f8f) 9%,#fff);
    border:1px solid color-mix(in srgb,var(--accent,#2f6f8f) 22%,#fff);
    padding:3px 10px; border-radius:3px; max-width:62%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }
  .card h3{margin:2px 0 9px; font-size:15.5px; font-weight:700; line-height:1.5;}
  .card h3 a{color:inherit; text-decoration:none;}
  .card h3 a:hover{color:var(--accent,#2f6f8f); text-decoration:underline;}
  .card .summary{font-size:13px; color:#52584e; margin:0 0 14px; flex:1 1 auto; line-height:1.65;}
  .card .foot{display:flex; align-items:center; justify-content:space-between; gap:10px; margin-top:auto; padding-top:11px; border-top:1px solid var(--line);}
  .card .time{font-size:12px; color:var(--muted); display:flex; align-items:center; gap:5px;}
  .card .time svg{flex:0 0 auto; opacity:.6;}
  .card .link{font-size:13px; font-weight:700; color:var(--accent,#2f6f8f); text-decoration:none; display:inline-flex; align-items:center; gap:4px;}
  .card .link:hover{text-decoration:underline;}

  .foot-note{text-align:center; color:var(--muted); font-size:13px; margin-top:34px; padding-top:22px; border-top:1px solid var(--line); line-height:1.85;}
  .foot-note a{color:var(--brand); text-decoration:none;}
  .foot-note a:hover{text-decoration:underline;}

  @media (max-width:560px){
    .hero{padding:34px 18px 24px;}
    .hero h1{font-size:26px;}
    .wrap{padding:0 14px 56px;}
    .grid{grid-template-columns:1fr;}
    .stat{flex:1 1 40%;}
  }
</style>
</head>
<body>
  <header class="hero" id="top">
    <div class="hero-inner">
      <div class="masthead">
        <div class="logo" aria-label="小马AI">小马AI</div>
        <p class="kicker">AI 每日新闻 · 聚合</p>
        <h1>小马AI 每日新闻</h1>
        <p class="tagline">每 6 小时自动更新的 AI 行业快讯</p>
        <p class="hero-date" id="heroDate"></p>
        <div class="stat-row">
          <div class="stat total"><div class="num" id="statTotal">0</div><div class="lbl">总条数</div></div>
          <div class="stat"><div class="num">6h</div><div class="lbl">更新频率</div></div>
          <div class="stat"><div class="num" id="statSec">5</div><div class="lbl">内容分类</div></div>
        </div>
        <p class="hero-meta">数据来源：量子位 · IT之家 · InfoQ中文 · 爱范儿 · 开源中国　·　<a href="https://xiaomaw.cn" target="_blank" rel="noopener">小马的主页</a></p>
      </div>
    </div>
  </header>

  <div class="wrap">
    <div class="lead" id="leadBox"></div>
    <nav class="nav" id="nav"></nav>
    <main id="main"></main>
    <div class="foot-note" id="footNote"></div>
  </div>

<script>
const DATA = __DATA__;

const ACCENTS = ["--c1","--c2","--c3","--c4","--c5"];
function accentVar(i){ return "var(" + ACCENTS[i % ACCENTS.length] + ")"; }

// 完整 HTML 转义（文本内容与属性通用）
function esc(s){
  return (s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// 北京时间人话格式；默认相对“报告日期”(DATA.date) 计算 今天/昨天
function fmtBeijing(iso, withDay){
  if(!iso) return "时间未公布";
  const d = new Date(iso);
  if(isNaN(d.getTime())) return "时间未公布";
  const bj = new Date(d.getTime() + 8*3600*1000);
  const Y=bj.getUTCFullYear(), M=bj.getUTCMonth()+1, D=bj.getUTCDate();
  const h=bj.getUTCHours(), m=String(bj.getUTCMinutes()).padStart(2,'0');
  // 防源 pubDate 标到未来（如 InfoQ 把当天新闻统一标 18:00 北京），显示未来时间不合理
  const nowBJ = new Date(Date.now() + 8*3600*1000);
  if(bj.getTime() > nowBJ.getTime()){
    return withDay===false ? (h+":"+m) : "刚刚";
  }
  if(withDay===false) return h+":"+m;
  const p=(DATA.date||"").split("-");
  const rY=+p[0], rM=+p[1], rD=+p[2];
  const dayDiff=Math.round((Date.UTC(Y,M-1,D)-Date.UTC(rY,rM-1,rD))/86400000);
  let prefix;
  if(dayDiff===0) prefix="今天";
  else if(dayDiff===1) prefix="明天";
  else if(dayDiff===-1) prefix="昨天";
  else prefix=(M+"月"+D+"日");
  return prefix+" "+h+":"+m;
}

function clip(s, max){
  const arr = Array.from(s || "");
  if(arr.length<=max) return s || "";
  return arr.slice(0,max).join("")+"…";
}

const WEEK = ["星期日","星期一","星期二","星期三","星期四","星期五","星期六"];
function renderHero(){
  const dateStr = DATA.date;
  const p = dateStr.split("-");
  const Y=+p[0], M=+p[1], D=+p[2];
  const wd = WEEK[new Date(Y, M-1, D).getDay()];
  const dateEl = document.getElementById("heroDate");
  if(dateEl){
    let txt = Y + "年" + M + "月" + D + "日 · " + wd;
    if(DATA.generatedAt){
      txt += " · 生成于北京时间 " + fmtBeijing(DATA.generatedAt, false);
    }
    if(DATA.isFallback) txt += ' <span class="badge-fallback">当日未生成 · 回退最近一期</span>';
    dateEl.innerHTML = txt;
  }
  const total = DATA.sections.reduce(function(a,s){return a+s.items.length;},0);
  document.getElementById("statTotal").textContent = total;
  document.getElementById("statSec").textContent = DATA.sections.length;
}

function renderLead(){
  const box = document.getElementById("leadBox");
  if(!DATA.lead){ box.style.display = 'none'; return; }
  box.innerHTML = '<span class="lead-tag">今日导语</span>' + esc(DATA.lead);
}

function renderNav(){
  const nav = document.getElementById("nav");
  let html = '<a href="#top">顶部</a>';
  DATA.sections.forEach(function(s,i){
    html += '<a href="#sec-' + i + '">'
      + s.label + '<span class="cnt">' + s.items.length + '</span></a>';
  });
  nav.innerHTML = html;
}

const CLOCK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';

function renderCards(){
  const main = document.getElementById("main");
  let counter = 0;
  let html = "";
  DATA.sections.forEach(function(s,i){
    const accent = accentVar(i);
    html += '<section class="section" id="sec-' + i + '">'
      + '<div class="section-head"><span class="bar" style="background:' + accent + '"></span>'
      + '<h2>' + s.label + '</h2><span class="count">' + s.items.length + ' 条</span></div>'
      + '<div class="grid">';
    s.items.forEach(function(it){
      counter++;
      const url = it.sourceUrl || "#";
      const src = it.sourceName || "来源";
      const time = fmtBeijing(it.publishedAt);
      const sumHtml = it.summary
        ? '<p class="summary" title="' + esc(it.summary) + '">' + esc(clip(it.summary, 60)) + '</p>'
        : '';
      html += '<article class="card" style="--accent:' + accent + '">'
        + '<div class="top">'
        + '<span class="badge">' + counter + '</span>'
        + '<span class="chip" title="' + esc(src) + '">' + esc(src) + '</span>'
        + '</div>'
        + '<h3><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(it.title) + '</a></h3>'
        + sumHtml
        + '<div class="foot">'
        + '<span class="time">' + CLOCK + time + '</span>'
        + '<a class="link" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">阅读原文 →</a>'
        + '</div>'
        + '</article>';
    });
    html += '</div></section>';
  });
  main.innerHTML = html;
}

function renderFoot(){
  const total = DATA.sections.reduce(function(a,s){return a+s.items.length;},0);
  const sl = (DATA.sourceList || []).map(function(s){return esc(s);}).join("、");
  document.getElementById("footNote").innerHTML =
    '本页共 <strong>' + total + '</strong> 条 · 数据来源：' + (sl || "中文科技媒体 RSS") + '<br>'
    + '时间均以北京时间展示，点击卡片标题或「阅读原文」跳转原出处。';
}

renderHero();
renderLead();
renderNav();
renderCards();
renderFoot();
</script>
</body>
</html>
"""

HEAD_TAG = "小马AI 每日新闻"


def esc_attr(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
        .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def main():
    print("抓取中文科技媒体 RSS ...")
    data = build_data()
    # 防 XSS：json.dumps 不会转义 '/'，若 RSS 标题含 </script> 会提前闭合脚本标签导致注入。
    # 将 '</' 转成 '<\/' —— HTML 解析器看不到闭合标签，而 JS 解析字符串时 '\/' 仍等于 '/'，数据无损。
    safe_data = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__DATA__", safe_data)

    og_title = HEAD_TAG + " · " + data["date"]
    og_desc = "中文 AI 资讯每日聚合：模型发布/更新、产品发布/更新、行业动态、论文研究、技巧与观点，来自量子位、IT之家、InfoQ、爱范儿等。"
    html = html.replace("__OG_TITLE__", esc_attr(og_title)).replace("__OG_DESC__", esc_attr(og_desc))

    os.makedirs(os.path.dirname(OUT_HTML) or ".", exist_ok=True)
    with io.open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    total = sum(len(s["items"]) for s in data["sections"])
    print(f"OK  日期={data['date']}  版块={len(data['sections'])}  总条数={total}")
    print("  各版块:", {s["label"]: len(s["items"]) for s in data["sections"]})
    print(f"输出: {OUT_HTML}")


if __name__ == "__main__":
    main()
