# -*- coding: utf-8 -*-
"""
build_daily.py — 一键生成 AI HOT 晨报仪表盘（单文件 HTML）

流程：
  1. 拉取当日 AI HOT 日报（/api/public/daily）；若当日尚未生成则回退到最近一期。
  2. 用 /api/public/items 补全每条 item 的真实发布时间（按 permalink 末段 id 匹配）。
  3. 生成单文件 HTML（内联 CSS/JS，无外部资源，响应式），含导语、五大版块、
     全局连续编号、Open Graph 分享标签与 emoji favicon。

用法：
  python build_daily.py
  AI_DAILY_OUTPUT=docs/index.html python build_daily.py   # 输出到 docs/ 供 GitHub Pages
输出：默认与本脚本同目录的 ai_daily_dashboard.html；可用 AI_DAILY_OUTPUT 覆盖。
"""
import json
import io
import os
import datetime
import urllib.request
import urllib.parse

BASE_API = "https://aihot.virxact.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
# 输出路径可用环境变量 AI_DAILY_OUTPUT 覆盖（用于 GitHub Pages 的 docs/index.html）
_out = os.environ.get("AI_DAILY_OUTPUT")
if _out:
    OUT_HTML = _out if os.path.isabs(_out) else os.path.join(HERE, _out)
else:
    OUT_HTML = os.path.join(HERE, "ai_daily_dashboard.html")


# ----------------------------------------------------------------------------
# 网络层
# ----------------------------------------------------------------------------
def fetch_json(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def get_daily():
    """返回 (daily_obj, date_str, is_fallback)。"""
    d = fetch_json(f"{BASE_API}/api/public/daily")
    if d and d.get("date"):
        return d, d["date"], False
    # 回退到最近一期
    arch = fetch_json(f"{BASE_API}/api/public/dailies", {"take": 1})
    if arch and arch.get("items"):
        date = arch["items"][0]["date"]
        d = fetch_json(f"{BASE_API}/api/public/daily/{date}")
        if d:
            return d, date, True
    raise RuntimeError("无法获取任何一期日报")


def item_id(it):
    return it.get("permalink", "").rsplit("/", 1)[-1]


def enrich(daily):
    """为日报每条 item 补全 publishedAt（北京时间来源）。"""
    sections = daily.get("sections", [])
    need = {item_id(it) for s in sections for it in s.get("items", [])}
    pub = {}

    # 以日报窗口起点往前 3 天作为 since，覆盖可能早于窗口的条目
    ws = daily.get("windowStart")
    if ws:
        dt = datetime.datetime.fromisoformat(ws.replace("Z", "+00:00"))
        since = (dt - datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        since = (datetime.datetime.utcnow() - datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    cursor = None
    pages = 0
    while pages < 15 and (need - set(pub)):
        pages += 1
        params = {"mode": "all", "since": since, "take": 100}
        if cursor:
            params["cursor"] = cursor
        data = fetch_json(f"{BASE_API}/api/public/items", params)
        if not data:
            break
        for it in data.get("items", []):
            iid = it.get("id")
            if iid in need and iid not in pub:
                pub[iid] = it.get("publishedAt")
        cursor = data.get("nextCursor")
        if not cursor:
            break

    # 仍缺失的条目：用标题关键词兜底搜索
    missing = list(need - set(pub))
    title_of = {}
    for s in sections:
        for it in s.get("items", []):
            title_of[item_id(it)] = it.get("title", "")
    for iid in missing:
        kw = (title_of.get(iid) or "")[:18]
        if not kw:
            continue
        data = fetch_json(f"{BASE_API}/api/public/items", {"q": kw, "take": 10})
        if not data:
            continue
        for it in data.get("items", []):
            if it.get("id") == iid:
                pub[iid] = it.get("publishedAt")
    return pub


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
<meta property="og:site_name" content="AI HOT 晨报">
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
      <p class="kicker">AI HOT · 晨报仪表盘</p>
      <h1 id="heroDate">AI 晨报</h1>
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
  let h = Y + " 年 " + M + " 月 " + D + " 日 · AI 晨报";
  if(DATA.isFallback) h += ' <span class="badge-fallback">当日未生成 · 回退最近一期</span>';
  document.getElementById("heroDate").innerHTML = h;
  let sub = "每" + wd.slice(1) + " · 五大版块全球 AI 动态精选";
  if(DATA.generatedAt){
    sub += " · 报告生成于北京时间 " + fmtBeijing(DATA.generatedAt, false);
  }
  document.getElementById("heroSub").textContent = sub;

  const total = DATA.sections.reduce(function(a,s){return a+s.items.length;},0);
  const row = document.getElementById("statRow");
  let html = '<div class="stat total"><div class="num">' + total + '</div><div class="lbl">今日总条数</div></div>';
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
      const sum = clip(it.summary, 60);
      const url = it.sourceUrl || "#";
      const src = it.sourceName || "来源";
      const time = fmtBeijing(it.publishedAt);
      html += '<article class="card" style="--accent:' + accent + '">'
        + '<div class="top">'
        + '<span class="badge">' + counter + '</span>'
        + '<span class="chip" title="' + esc(src) + '">' + esc(src) + '</span>'
        + '</div>'
        + '<h3><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(it.title) + '</a></h3>'
        + '<p class="summary" title="' + esc(it.summary) + '">' + esc(sum) + '</p>'
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
  let srcHtml;
  if(DATA.attribution && DATA.attribution.canonical){
    srcHtml = '<a href="' + esc(DATA.attribution.canonical) + '" target="_blank" rel="noopener noreferrer">'
      + esc(DATA.attribution.source || 'AI HOT') + '</a>';
  } else {
    srcHtml = esc((DATA.attribution && DATA.attribution.source) ? DATA.attribution.source : 'AI HOT');
  }
  document.getElementById("footNote").innerHTML =
    '本日报共 <strong>' + total + '</strong> 条 · 数据来源：' + srcHtml + '（aihot.virxact.com）<br>'
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


def build_data(daily, pub, is_fallback):
    sections = []
    for s in daily.get("sections", []):
        items = []
        for it in s.get("items", []):
            items.append({
                "title": it.get("title", ""),
                "summary": it.get("summary", "") or "",
                "sourceName": it.get("sourceName", ""),
                "sourceUrl": it.get("sourceUrl", ""),
                "publishedAt": pub.get(item_id(it)),
            })
        sections.append({"label": s.get("label", ""), "items": items})
    return {
        "date": daily.get("date"),
        "generatedAt": daily.get("generatedAt"),
        "attribution": daily.get("attribution", {}),
        "lead": daily.get("lead", "") or "",
        "isFallback": is_fallback,
        "sections": sections,
    }


def esc_attr(s):
    """Python 侧转义，用于注入 <title>/<meta> 等属性值。"""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
        .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def main():
    daily, date_str, is_fallback = get_daily()
    pub = enrich(daily)
    data = build_data(daily, pub, is_fallback)

    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))

    # Open Graph / 描述：注入与当日相关的内容，供爬虫与社交分享预览
    og_title = "AI 晨报 · " + date_str
    og_desc = (data.get("lead") or
               "每日自动生成的 AI 资讯晨报：模型发布/更新、产品发布/更新、行业动态、论文研究、技巧与观点，全球 AI 动态精选。").strip()
    html = html.replace("__OG_TITLE__", esc_attr(og_title)).replace("__OG_DESC__", esc_attr(og_desc))

    os.makedirs(os.path.dirname(OUT_HTML) or ".", exist_ok=True)
    with io.open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    total = sum(len(s["items"]) for s in data["sections"])
    print(f"OK  日期={date_str}  回退={is_fallback}  版块={len(data['sections'])}  总条数={total}  lead={'有' if data['lead'] else '无'}")
    print(f"输出: {OUT_HTML}")
    missing = [item_id(it) for s in daily.get("sections", []) for it in s.get("items", []) if not pub.get(item_id(it))]
    if missing:
        print(f"注意: {len(missing)} 条未能补全发布时间（将显示“时间未公布”）")


if __name__ == "__main__":
    main()
