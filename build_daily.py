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

数据源（偏 AI 的 5 个，实测可用）：量子位 / 36氪 / InfoQ 中文 / 爱范儿 / 开源中国。
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
    ("36氪", "https://36kr.com/feed"),
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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%232f6df6'/><text x='16' y='22' font-size='16' font-weight='700' text-anchor='middle' fill='white'>AI</text></svg>">
<style>
  :root{
    --bg:#f5f7fb; --panel:#ffffff; --ink:#1f2733; --muted:#6b7686;
    --line:#e6eaf0; --shadow:0 1px 3px rgba(20,30,50,.06),0 8px 24px rgba(20,30,50,.06);
    --c1:#2f6df6; --c2:#7c3aed; --c3:#0ea5a4; --c4:#e0851a; --c5:#db2777;
  }
  *{box-sizing:border-box;}
  html{scroll-behavior:smooth;}
  body{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.6; -webkit-font-smoothing:antialiased;
  }
  .wrap{max-width:1180px; margin:0 auto; padding:0 18px 64px;}

  .hero{
    background:linear-gradient(135deg,#2f6df6 0%,#7c3aed 55%,#db2777 100%);
    color:#fff; border-radius:0 0 26px 26px; padding:42px 28px 34px; margin-bottom:18px;
    box-shadow:var(--shadow);
  }
  .hero-inner{max-width:1180px; margin:0 auto;}
  .kicker{font-size:13px; letter-spacing:.18em; text-transform:uppercase; opacity:.85; margin:0 0 6px;}
  .hero h1{margin:0; font-size:30px; font-weight:800; letter-spacing:.5px;}
  .hero .sub{margin:8px 0 0; opacity:.92; font-size:15px;}
  .badge-fallback{display:inline-block; margin-left:10px; font-size:12px; font-weight:700;
    background:rgba(255,255,255,.22); border:1px solid rgba(255,255,255,.4); padding:3px 10px; border-radius:999px; vertical-align:middle;}
  .stat-row{display:flex; flex-wrap:wrap; gap:14px; margin-top:24px;}
  .stat{
    background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.22);
    border-radius:14px; padding:12px 16px; min-width:120px; flex:1 1 120px; backdrop-filter:blur(4px);
  }
  .stat .num{font-size:26px; font-weight:800; line-height:1;}
  .stat .lbl{font-size:12.5px; opacity:.9; margin-top:6px;}
  .stat.total .num{font-size:34px;}

  .lead{
    background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--c2);
    border-radius:14px; padding:16px 18px; margin:18px 0 0; box-shadow:var(--shadow);
    font-size:15px; color:#33405a; line-height:1.7;
  }
  .lead .lead-tag{display:block; font-size:12px; font-weight:700; color:var(--c2); letter-spacing:.08em; margin-bottom:6px;}

  .nav{
    position:sticky; top:0; z-index:20; background:rgba(255,255,255,.9);
    backdrop-filter:blur(8px); border:1px solid var(--line); border-radius:14px;
    display:flex; flex-wrap:wrap; gap:8px; padding:10px 12px; margin:18px 0 26px; box-shadow:var(--shadow);
  }
  .nav a{
    text-decoration:none; color:var(--ink); font-size:13.5px; font-weight:600;
    padding:7px 13px; border-radius:999px; border:1px solid var(--line); background:#fff; transition:.15s; white-space:nowrap;
  }
  .nav a:hover{transform:translateY(-1px); box-shadow:0 4px 12px rgba(20,30,50,.1);}
  .nav a .dot{display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:7px; vertical-align:middle;}
  .nav a .cnt{color:var(--muted); font-weight:700; margin-left:6px;}

  .section{margin-bottom:40px; scroll-margin-top:78px;}
  .section-head{display:flex; align-items:baseline; gap:12px; margin:0 0 16px; padding-bottom:10px; border-bottom:2px solid var(--line);}
  .section-head .bar{width:5px; height:24px; border-radius:3px;}
  .section-head h2{margin:0; font-size:20px; font-weight:800;}
  .section-head .count{margin-left:auto; color:var(--muted); font-size:14px; font-weight:600;}

  .grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:16px;}
  .card{
    background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px 18px 16px;
    box-shadow:var(--shadow); position:relative; display:flex; flex-direction:column; transition:.18s; border-top:3px solid var(--accent,#ccc);
  }
  .card:hover{transform:translateY(-3px); box-shadow:0 10px 30px rgba(20,30,50,.12);}
  .card .top{display:flex; align-items:center; gap:10px; margin-bottom:10px;}
  .badge{
    flex:0 0 auto; width:30px; height:30px; border-radius:9px; background:var(--accent,#2f6df6);
    color:#fff; font-weight:800; font-size:14px; display:flex; align-items:center; justify-content:center;
  }
  .chip{
    margin-left:auto; font-size:12px; font-weight:600; color:var(--accent,#2f6df6);
    background:color-mix(in srgb,var(--accent,#2f6df6) 12%,#fff);
    border:1px solid color-mix(in srgb,var(--accent,#2f6df6) 28%,#fff);
    padding:4px 10px; border-radius:999px; max-width:62%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }
  .card h3{margin:2px 0 8px; font-size:16px; font-weight:700; line-height:1.45;}
  .card h3 a{color:inherit; text-decoration:none;}
  .card h3 a:hover{color:var(--accent,#2f6df6); text-decoration:underline;}
  .card .summary{font-size:13.5px; color:#46505f; margin:0 0 14px; flex:1 1 auto;}
  .card .foot{display:flex; align-items:center; justify-content:space-between; gap:10px; margin-top:auto;}
  .card .time{font-size:12px; color:var(--muted); display:flex; align-items:center; gap:5px;}
  .card .time svg{flex:0 0 auto; opacity:.7;}
  .card .link{font-size:13px; font-weight:700; color:var(--accent,#2f6df6); text-decoration:none; display:inline-flex; align-items:center; gap:4px;}
  .card .link:hover{text-decoration:underline;}

  .foot-note{text-align:center; color:var(--muted); font-size:13px; margin-top:30px; padding-top:20px; border-top:1px solid var(--line); line-height:1.8;}
  .foot-note a{color:var(--c1); text-decoration:none;}
  .foot-note a:hover{text-decoration:underline;}

  @media (max-width:560px){
    .hero{padding:30px 18px 24px; border-radius:0 0 18px 18px;}
    .hero h1{font-size:23px;}
    .grid{grid-template-columns:1fr;}
    .stat{flex:1 1 45%;}
  }
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <p class="kicker">小马AI 每日新闻 · 聚合</p>
      <h1 id="heroDate">小马AI 每日新闻</h1>
      <p class="sub" id="heroSub"></p>
      <div class="stat-row" id="statRow"></div>
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
  if(withDay===false) return h+":"+m;
  const p=(DATA.date||"").split("-");
  const rY=+p[0], rM=+p[1], rD=+p[2];
  const dayDiff=Math.round((Date.UTC(Y,M-1,D)-Date.UTC(rY,rM-1,rD))/86400000);
  let prefix;
  if(dayDiff===0) prefix="今天";
  else if(dayDiff===1) prefix="昨天";
  else if(dayDiff===-1) prefix="明天";
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
  let h = Y + " 年 " + M + " 月 " + D + " 日 · 小马AI 每日新闻";
  if(DATA.isFallback) h += ' <span class="badge-fallback">当日未生成 · 回退最近一期</span>';
  document.getElementById("heroDate").innerHTML = h;
  let sub = "每" + wd.slice(1) + " · 五大版块中文 AI 资讯聚合";
  if(DATA.generatedAt){
    sub += " · 生成于北京时间 " + fmtBeijing(DATA.generatedAt, false);
  }
  document.getElementById("heroSub").textContent = sub;

  const total = DATA.sections.reduce(function(a,s){return a+s.items.length;},0);
  const row = document.getElementById("statRow");
  let html = '<div class="stat total"><div class="num">' + total + '</div><div class="lbl">总条数</div></div>';
  DATA.sections.forEach(function(s,i){
    html += '<div class="stat" style="border-left:4px solid ' + accentVar(i) + '">'
      + '<div class="num">' + s.items.length + '</div>'
      + '<div class="lbl">' + s.label + '</div></div>';
  });
  row.innerHTML = html;
}

function renderLead(){
  const box = document.getElementById("leadBox");
  if(!DATA.lead){ box.parentNode.removeChild(box); return; }
  box.innerHTML = '<span class="lead-tag">今日导语</span>' + esc(DATA.lead);
}

function renderNav(){
  const nav = document.getElementById("nav");
  let html = '<a href="#top"><span class="dot" style="background:#94a3b8"></span>顶部</a>';
  DATA.sections.forEach(function(s,i){
    html += '<a href="#sec-' + i + '"><span class="dot" style="background:' + accentVar(i) + '"></span>'
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
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))

    og_title = HEAD_TAG + " · " + data["date"]
    og_desc = "中文 AI 资讯每日聚合：模型发布/更新、产品发布/更新、行业动态、论文研究、技巧与观点，来自量子位、36氪、InfoQ、爱范儿等。"
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
