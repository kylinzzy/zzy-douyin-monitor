"""张真源 · 抖音数据监测看板。

设计原则（按用户反馈）：
- 纯绿色主题（张真源应援色），不使用其他颜色
- 极简：无 emoji、无说明备注、无多余装饰
- 量级差很大的数据不混在一起：粉丝趋势 / 获赞趋势 各自独立成图，
  1h 新增只在卡片里以文字呈现，不进图表与百万级数值争坐标轴
- 零外部依赖，纯 SVG 自绘，刷新即可见
"""
import json
import math
import urllib.parse
from common import (DASHBOARD_PATH, DOWNLOADS_HTML, TARGET_NAME, humanize,
                    now_iso, get_meta, SERVER_PORT, PAGE_CSS)
from storage import (latest_profile, profile_series, post_list,
                     post_stats_series, board_latest, count_rows,
                     latest_post_stats)

# 仅绿色色板
GREEN = "#16a34a"
GREEN_D = "#15803d"
GREEN_BR = "#22c55e"
GREEN_L = "#dcfce7"
GREEN_XL = "#f4faf6"
GREEN_INK = "#14342a"
MUTED = "#6b9080"
BORDER = "#d8efe0"

# 看板专属样式（叠加在 PAGE_CSS 设计系统之上）
DASHBOARD_CSS = r""".ed-masthead{position:relative;display:flex;align-items:baseline;justify-content:space-between;gap:18px;
padding:34px 0 18px;border-bottom:1.2px solid var(--rule);}
.ed-masthead .lt{font-family:var(--serif);font-size:24px;font-weight:700;color:var(--ink-deep);
letter-spacing:-.2px;}
.ed-masthead .rt{font-size:10.5px;letter-spacing:2.2px;color:#666;text-align:right;
text-transform:uppercase;}
.ed-masthead .rt b{color:var(--accent-warm);font-weight:700;}
/* 顶部口号 "ALL FOR ZZY"：衬线暖橘小字，张真源应援口号的杂志式呈现 */
.ed-masthead .motto{position:absolute;left:0;top:10px;font-family:var(--serif);font-size:10.5px;
letter-spacing:3.6px;color:var(--accent-warm);font-weight:600;text-transform:uppercase;
display:flex;align-items:center;gap:10px;margin:0;line-height:1;}
.ed-masthead .motto::before{content:"";display:inline-block;width:22px;height:1px;background:var(--accent-warm);}
.ed-masthead .motto::after{content:"";display:inline-block;width:42px;height:1px;background:var(--accent-warm);opacity:.35;}
/* masthead 右上角：白色蝴蝶剪影 + 颗粒光点（低饱和深绿，不抢主文字） */
.ed-masthead .deco{position:absolute;right:0;top:0;width:148px;height:42px;pointer-events:none;}
.ed-masthead .deco .bf{position:absolute;right:0;top:0;width:78px;color:var(--ink-mid);opacity:.20;}
.ed-masthead .deco .sd{position:absolute;right:74px;top:10px;width:64px;color:var(--ink-mid);opacity:.55;}
.ed-masthead .deco svg{display:block;fill:currentColor;}
.ed-vol{font-size:11px;letter-spacing:2.6px;color:#888;margin-top:14px;text-transform:uppercase;}
.ed-vol b{color:var(--ink);font-weight:700;}

.ed-stat{position:relative;margin:48px 0 12px;display:grid;grid-template-columns:1fr auto;gap:20px;align-items:end;
padding-bottom:18px;border-bottom:1px solid var(--rule2);}
/* ed-stat 右上角：极小蝴蝶剪影，仅装饰 */
.ed-stat .deco{position:absolute;right:0;top:0;width:36px;height:18px;
color:var(--ink-mid);opacity:.16;pointer-events:none;}
.ed-stat .deco svg{display:block;width:100%;height:auto;fill:currentColor;}
.ed-stat .label{font-size:11px;letter-spacing:2.6px;color:var(--g);font-weight:700;
margin-bottom:14px;text-transform:uppercase;}
.ed-stat .num{font-family:var(--serif);font-size:clamp(56px,8vw,108px);font-weight:700;
color:var(--ink);letter-spacing:-2px;line-height:.95;font-feature-settings:"tnum";}
.ed-stat .num .raw{font-family:var(--ff);font-size:13px;color:#888;font-weight:500;
margin-left:12px;letter-spacing:0;vertical-align:middle;}
.ed-stat .sub{font-size:13px;color:#666;margin-top:14px;letter-spacing:.3px;}
.ed-stat .meta{text-align:right;font-size:11px;letter-spacing:1.5px;color:#666;
text-transform:uppercase;line-height:1.9;}
.ed-stat .meta b{color:var(--g);font-weight:700;font-family:var(--serif);
font-size:14px;letter-spacing:-.2px;text-transform:none;}

.ed-rule{height:1px;background:var(--rule);margin:0 0 36px;opacity:.92;}

.ed-charts{display:grid;grid-template-columns:1fr 1fr;gap:42px;}
.ed-chart .h{font-family:var(--serif);font-size:15px;font-weight:700;color:var(--ink);
margin-bottom:6px;letter-spacing:-.1px;}
.ed-chart .sub{font-size:10.5px;letter-spacing:1.8px;color:#888;margin-bottom:18px;
text-transform:uppercase;}
.ed-chart .frame{padding:10px 0 12px;border-bottom:.5px solid var(--rule);}

.ed-pub{margin-top:36px;padding:18px 0;border-top:1px solid var(--rule2);border-bottom:1px solid var(--rule2);}
.ed-pub .h{font-family:var(--serif);font-size:15px;font-weight:700;color:var(--ink);margin-bottom:6px;letter-spacing:-.1px;}
.ed-pub .sub{font-size:10.5px;letter-spacing:1.8px;color:#888;margin-bottom:14px;text-transform:uppercase;}
.ed-pub .frame{padding:6px 0 12px;}

.ed-list{margin:0;padding:0;}
.ed-list-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;
margin:0 0 6px;padding-bottom:8px;border-bottom:1px solid var(--rule);}
.ed-list-head .h{font-family:var(--serif);font-size:15px;font-weight:700;color:var(--ink);letter-spacing:-.1px;}
.ed-list-head .meta{font-size:10.5px;letter-spacing:1.8px;color:#888;text-transform:uppercase;}
.ed-list .row{display:grid;grid-template-columns:46px 1fr 120px 84px;gap:18px;
align-items:baseline;padding:13px 0;border-bottom:.5px solid var(--rule2);
transition:background .18s;}
.ed-list .row:hover{background:rgba(22,163,94,.04);}
.ed-list .no{font-family:var(--serif);font-size:13px;font-style:italic;color:#888;
font-weight:500;letter-spacing:.5px;}
.ed-list .title{font-family:var(--serif);font-size:18px;font-weight:600;color:var(--ink);
letter-spacing:-.1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
display:block;}
.ed-list .title:hover{color:var(--g);}
.ed-list .time{font-size:11.5px;color:#666;letter-spacing:.3px;font-feature-settings:"tnum";}
.ed-list .nums{font-family:var(--serif);font-size:14px;font-weight:700;color:var(--g);
text-align:right;font-feature-settings:"tnum";}
.ed-list-foot{padding:14px 0 0;font-size:10.5px;letter-spacing:1.8px;color:#888;text-align:center;}

/* 作品缩略图矩阵（替代长文字列表，数量已并入块标题） */
.wall{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:11px;margin-top:14px;}
.wt{position:relative;display:block;aspect-ratio:3/4;border-radius:13px;overflow:hidden;
background:var(--gxl);border:1px solid var(--bd);transition:transform .25s cubic-bezier(.2,.7,.2,1),box-shadow .25s;}
.wt:hover{transform:translateY(-4px);box-shadow:var(--shadow-lg);}
.wt.miss{background:linear-gradient(135deg,var(--gl),var(--gd));}
.wt img{width:100%;height:100%;object-fit:cover;display:block;}
.wt .scrim{position:absolute;left:0;right:0;bottom:0;padding:22px 8px 7px;
background:linear-gradient(transparent,rgba(10,61,36,.82));pointer-events:none;}
.wt .lk{display:flex;align-items:center;gap:3px;color:#fff;font-family:var(--serif);
font-weight:700;font-size:12.5px;font-feature-settings:"tnum";line-height:1;}
.wt .lk svg{width:10px;height:10px;fill:#fff;opacity:.92;flex:none;}
.wt .ti{margin-top:3px;font-size:10px;line-height:1.3;color:rgba(255,255,255,.85);
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.wt .mt-badge{position:absolute;left:7px;top:7px;z-index:2;background:var(--ink-deep);
color:#fff;font-family:var(--serif);font-size:9px;font-weight:700;letter-spacing:.3px;
padding:3px 7px;border-radius:20px;box-shadow:0 2px 6px rgba(10,61,36,.35);}
.wt .mt-time{margin-top:3px;font-size:8.5px;line-height:1;color:rgba(255,255,255,.82);
letter-spacing:.2px;font-feature-settings:"tnum";}

/* 破百万节点已合并到作品缩略图标签（见 .wt .mt-badge） */

.ed-topics{margin-top:8px;}
.ed-topics-row{font-size:13.5px;color:var(--ink);line-height:2;}
.ed-topics-row .tg{display:inline-block;margin:0 18px 8px 0;font-family:var(--serif);font-weight:600;}
.ed-topics-row .tg:hover{color:var(--g);}
.ed-topics-row .v{color:#999;font-family:var(--ff);font-size:12px;font-weight:500;
margin-left:4px;letter-spacing:.3px;}

.ed-export{margin-top:30px;text-align:center;}
.ed-xlsx-btn{display:inline-block;padding:11px 22px;border:1.2px solid var(--bd2);
border-radius:24px;color:var(--ink);font-family:var(--serif);font-size:13px;font-weight:600;
letter-spacing:.5px;text-decoration:none;transition:background .18s,border-color .18s;}
.ed-xlsx-btn:hover{background:var(--gxl);border-color:var(--gd);}

.foot{margin-top:42px;padding-top:24px;border-top:.5px solid var(--rule2);
text-align:center;font-size:10.5px;letter-spacing:2px;color:#888;text-transform:uppercase;}
.foot b{color:var(--ink);font-weight:700;}
/* footer 拼音标 + 应援拉丁 motto：蝴蝶意象 + 应援口号 */
.foot .motto-row{font-family:var(--serif);font-size:13px;letter-spacing:5px;
color:var(--ink-deep);font-weight:700;text-transform:uppercase;margin:0 0 6px;
display:flex;align-items:center;justify-content:center;gap:12px;}
.foot .motto-row::before,.foot .motto-row::after{content:"";display:inline-block;width:32px;height:1px;background:var(--ink-mid);opacity:.55;}
.foot .latin{font-family:var(--serif);font-style:italic;color:var(--muted);
letter-spacing:.5px;text-transform:none;font-size:11.5px;margin-top:10px;font-weight:400;}

.chart-wrap{position:relative;background:transparent;border:0;border-radius:0;padding:0;}
.chart-wrap svg circle.pt{transition:r .18s ease;cursor:pointer;}
.chart-wrap svg g[data-i]:hover circle.pt{r:6;}
.chart-wrap svg g[data-i]{cursor:pointer;}

.dy-tip{position:absolute;pointer-events:none;z-index:9999;background:rgba(17,17,17,.96);color:#fff;
padding:9px 12px;border-radius:6px;font-size:11.5px;line-height:1.6;max-width:260px;white-space:pre-line;
box-shadow:0 8px 22px rgba(0,0,0,.22);transform:translate(-50%,-100%);font-family:var(--ff);}
.dy-tip::after{content:"";position:absolute;left:50%;top:100%;transform:translateX(-50%);
border:5px solid transparent;border-top-color:rgba(17,17,17,.96);}

@media (max-width:760px){
.wrap{padding:18px 16px 42px;}
.ed-stat{grid-template-columns:1fr;gap:14px;}
.ed-stat .meta{text-align:left;}
.ed-stat .num{font-size:54px;}
.ed-charts{grid-template-columns:1fr;gap:28px;}
.ed-list .row{grid-template-columns:38px 1fr 64px;gap:10px;}
.ed-list .time{display:none;}
.wall{grid-template-columns:repeat(auto-fill,minmax(82px,1fr));gap:8px;}
.ms-scale span{font-size:7px;}
.ms-scale,.ms-bar{margin-left:14px;margin-right:14px;}
.ed-pub{margin-top:28px;}
.ed-masthead{flex-direction:column;gap:8px;align-items:flex-start;}
.ed-masthead .rt{text-align:left;}
.ed-list-head{flex-direction:column;align-items:flex-start;gap:4px;}
}
"""


# ---------------------------------------------------------------------------
# 通用：纯绿单色折线图（自绘 SVG，无外部依赖）
# ---------------------------------------------------------------------------

def _fmt_num(v):
    try:
        v = float(v)
    except Exception:
        return str(v)
    if abs(v) >= 1e8:
        return f"{v/1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:.1f}万"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


def _svg_line(xlabels, values, color, w=560, h=240, log=False,
               point_titles=None, point_hrefs=None,
               relative_start=False, chart_id=None):
    """单色折线图。xlabels: 已格式化的 x 轴短标签；values: 数值序列。
    point_titles: 可选，每点对应一行 <title>，鼠标 hover 显示。
    point_hrefs:   可选，每点对应一个 URL（点击该点直接跳转，便于「这是哪个作品」）。
    relative_start: True 时把 values 转换为相对首个点的差（首点 = 0），
                    解决「绝对值巨大、波动看不出来」的问题；y 轴显示 +/-。
    chart_id: 可选，给 SVG 一个 id 供 JS 自绘 tooltip 使用。
    """
    n = len(values)
    if n == 0:
        return (f'<svg viewBox="0 0 {w} {h}"><text x="{w/2}" y="{h/2}" '
                f'text-anchor="middle" fill="{MUTED}" font-size="13">暂无数据</text></svg>')

    if relative_start and n > 0:
        base = values[0]
        delta_vals = [v - base for v in values]
        # 原始 values 用于 tooltip
        raw_vals = list(values)
        values = delta_vals

    pad_l, pad_r, pad_t, pad_b = 56, 14, 16, 34
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b

    if n == 1:
        xs = [pad_l + plot_w / 2]
    else:
        xs = [pad_l + i * (plot_w / (n - 1)) for i in range(n)]

    vmin, vmax = min(values), max(values)

    if log:
        lo = math.floor(math.log10(max(vmin, 1)))
        hi = math.ceil(math.log10(max(vmax, 1)))
        if hi == lo:
            hi = lo + 1
        def yf(v):
            lv = math.log10(max(v, 1))
            return pad_t + plot_h - (lv - lo) / (hi - lo) * plot_h
        yticks = [10 ** e for e in range(lo, hi + 1)]
    else:
        # 相对起始：让 0 落在中央更易读；上下限对称
        if relative_start:
            span = max(abs(vmin), abs(vmax)) or 1
            hi = span * 1.15
            lo = -span * 1.15
            def yf(v):
                return pad_t + plot_h - ((v - lo) / (hi - lo)) * plot_h
            # 用 ±grid 来显示
            ticks = [-span, -span/2, 0, span/2, span]
        else:
            hi = (vmax * 1.12) or 1
            lo = 0
            def yf(v):
                return pad_t + plot_h - (v / hi) * plot_h
            ticks = [hi * i / 4 for i in range(5)]
        yticks = ticks

    def xpos(i):
        return xs[i]

    # 折线 + 填充区
    pts = [(xpos(i), yf(v)) for i, v in enumerate(values)]
    line = " ".join(f"{'M' if i == 0 else 'L'} {x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
    area = (f"{line} L {pts[-1][0]:.1f} {pad_t+plot_h:.1f} "
            f"L {pts[0][0]:.1f} {pad_t+plot_h:.1f} Z")

    # y 轴网格 + 标签
    grid = []
    if relative_start:
        for tv in yticks:
            y = yf(tv)
            grid.append(f'<line x1="{pad_l}" x2="{pad_l+plot_w}" y1="{y:.1f}" y2="{y:.1f}" '
                        f'stroke="{BORDER}" stroke-dasharray="2,3"/>')
            label = ("0" if tv == 0 else
                     ("+" + _fmt_num(tv) if tv > 0 else "−" + _fmt_num(-tv)))
            grid.append(f'<text x="{pad_l-7:.1f}" y="{y:.1f}" text-anchor="end" '
                        f'font-size="10" fill="{MUTED}" dominant-baseline="middle">{label}</text>')
    else:
        for tv in yticks:
            y = yf(tv)
            grid.append(f'<line x1="{pad_l}" x2="{pad_l+plot_w}" y1="{y:.1f}" y2="{y:.1f}" '
                        f'stroke="{BORDER}" stroke-dasharray="2,3"/>')
            grid.append(f'<text x="{pad_l-7:.1f}" y="{y:.1f}" text-anchor="end" '
                        f'font-size="10" fill="{MUTED}" dominant-baseline="middle">{_fmt_num(tv)}</text>')

    # x 轴标签（自适应抽样）
    xt = []
    step = max(1, n // 7)
    for i in range(0, n, step):
        xt.append(f'<text x="{xpos(i):.1f}" y="{pad_t+plot_h+18:.1f}" text-anchor="middle" '
                  f'font-size="10" fill="{MUTED}">{xlabels[i]}</text>')
    if n > 1 and (n - 1) % step != 0:
        xt.append(f'<text x="{xpos(n-1):.1f}" y="{pad_t+plot_h+18:.1f}" text-anchor="middle" '
                  f'font-size="10" fill="{MUTED}">{xlabels[-1]}</text>')

    # 0 轴参考线（仅 relative_start 模式）
    zero_line = ""
    if relative_start:
        y0 = yf(0)
        zero_line = (f'<line x1="{pad_l}" x2="{pad_l+plot_w}" '
                     f'y1="{y0:.1f}" y2="{y0:.1f}" stroke="{color}" '
                     f'stroke-width="1" stroke-opacity="0.35"/>')

    # 数据点（带 hover tooltip + 可选点击跳转）— 用外层 <a> 包装整组 circle 让 click 跳转
    dots = []
    titles = point_titles if (point_titles and len(point_titles) == n) else None
    hrefs = point_hrefs if (point_hrefs and len(point_hrefs) == n) else None
    use_tooltip_js = bool(chart_id and titles)
    for i, (x, y) in enumerate(pts):
        is_last = (i == n - 1)
        # 透明 hit area 让点击区域更大
        hit = (f'<rect x="{x-12:.1f}" y="{y-12:.1f}" width="24" height="24" '
               f'fill="transparent" pointer-events="all"/>')
        if is_last:
            # 末点：实心大点 + 外光晕，表示「最新」
            inner = (f'{hit}'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{color}" '
                     f'fill-opacity="0.12" pointer-events="none"/>'
                     f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="4.5" '
                     f'fill="{color}" stroke="#fff" stroke-width="2" pointer-events="none"/>')
        else:
            inner = (f'{hit}'
                     f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#fff" '
                     f'stroke="{color}" stroke-width="2" pointer-events="none"/>')
        if hrefs and hrefs[i]:
            # 整组包成 <a target="_blank"> 让 click 跳转
            safe_href = (hrefs[i] or '').replace('"', '&quot;')
            dots.append(f'<g data-i="{i}" data-href="{safe_href}">'
                        f'<a href="{safe_href}" target="_blank" rel="noopener">'
                        f'{inner}</a></g>')
        else:
            dots.append(f'<g data-i="{i}">{inner}</g>')

    id_attr = f' id="{chart_id}"' if chart_id else ''
    return (f'<svg{ id_attr} viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet" '
            f'style="width:100%;height:{h}px">'
            + ''.join(grid) + ''.join(xt) + zero_line
            + f'<path class="dy-area" d="{area}" fill="{color}" fill-opacity="0.10"/>'
            + f'<path class="dy-line" d="{line}" fill="none" stroke="{color}" stroke-width="2.4" '
              f'stroke-linejoin="round" stroke-linecap="round" pathLength="1"/>'
            + ''.join(dots)
            + '</svg>')


def _svg_spark(vals, w=220, h=36):
    if not vals or len(vals) < 2:
        return f'<div class="spark-empty">监控中</div>'
    pad = 2
    pw, ph = w - pad * 2, h - pad * 2
    vmin, vmax = min(vals), max(vals)
    span = (vmax - vmin) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = pad + (i / (n - 1)) * pw
        y = pad + ph - ((v - vmin) / span) * ph
        pts.append(f"{x:.1f},{y:.1f}")
    line = "M " + " L ".join(pts)
    area = line + f" L {pad+pw:.1f} {pad+ph:.1f} L {pad:.1f} {pad+ph:.1f} Z"
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px;display:block">'
            f'<path d="{area}" fill="{GREEN}" fill-opacity="0.12"/>'
            f'<path d="{line}" fill="none" stroke="{GREEN}" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{pts[-1].split(",")[0]}" cy="{pts[-1].split(",")[1]}" r="2" '
            f'fill="#fff" stroke="{GREEN}" stroke-width="1.4"/></svg>')


# ---------------------------------------------------------------------------
# 榜单字段：翻译为中文、跳过零值
# ---------------------------------------------------------------------------

_BOARD_LABEL = {
    "view_count": "播放", "user_count": "参与", "video_count": "视频",
    "hot_value": "热度", "search_count": "搜索", "discussion_count": "讨论",
}
_BOARD_ORDER = ["view_count", "user_count", "video_count"]


def _board_extra_str(extra):
    if not extra or not isinstance(extra, dict):
        return ""
    keys = [k for k in _BOARD_ORDER if k in extra]
    for k in extra:
        if k not in keys:
            keys.append(k)
    parts = []
    for k in keys:
        v = extra.get(k)
        if v is None or v == 0:
            continue
        parts.append(f'{_BOARD_LABEL.get(k, k)} {_fmt_num(v)}')
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# 数据构建
# ---------------------------------------------------------------------------

def _mode():
    if get_meta("mode") in ("awaiting-config", "live", "error"):
        return get_meta("mode")
    if count_rows("profile_hourly") == 0:
        return "awaiting-config"
    return "live"


def _hourly_delta(series):
    out = []
    for i, row in enumerate(series):
        ts, val = row[0], row[1]
        d = 0 if i == 0 else val - series[i - 1][1]
        out.append((ts, val, d))
    return out


def _fmt_time(ts):
    if not ts:
        return ""
    try:
        from datetime import datetime, timezone, timedelta
        return datetime.fromtimestamp(int(ts), tz=timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def _fmt_date(ts):
    if not ts:
        return ""
    try:
        from datetime import datetime, timezone, timedelta
        return datetime.fromtimestamp(int(ts), tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _milestone_times(series, idx=1, step=1_000_000):
    """计算作品点赞破百万节点的突破时刻。

    返回 {tier: ts_or_None}，tier 为百万整数（1=100万）。
    - 序列中先出现 <thr 再出现 >=thr：精确突破时刻 = 首个 >=thr 的 ts（小时级）。
    - 首个快照即已 >=thr（监测开始前已破）：ts=None（无记录）。
    - 始终未达 thr：不计入（调用方据当前值判断「未达」）。
    """
    if not series:
        return {}
    vals = [r[idx] for r in series if r[idx] is not None]
    if not vals:
        return {}
    maxv = max(vals)
    max_tier = int(maxv // step)
    out = {}
    for tier in range(1, max_tier + 1):
        thr = tier * step
        crossing = None
        seen_before = False
        for r in series:
            v = r[idx]
            if v is None:
                continue
            if v < thr:
                seen_before = True
            elif crossing is None:
                crossing = r[0]
        out[tier] = crossing if (crossing is not None and seen_before) else None
    return out


def _milestone_section(cards):
    """破百万节点：每件作品一条渐变色进度条。

    - 刻度 = 100万档；填充 = 已破档，浅绿→深绿渐变（越往前越深，一直延伸）。
    - 达成刻度上方显示突破时刻；监测前已破显示「已达成」；未达刻度标档位（如 100万）。
    - 仅纳入已破至少 1 百万的作品。
    """
    STEP = 1_000_000
    eligible = [c for c in cards if (c.get("cur_digg") or 0) >= STEP]
    if not eligible:
        return ""
    eligible.sort(key=lambda x: x.get("cur_digg") or 0, reverse=True)

    rows = ""
    for c in eligible:
        cur = c.get("cur_digg") or 0
        max_tier = int(cur // STEP)
        show_tier = min(max_tier + 1, 8)
        total = show_tier * STEP
        fill_pct = min(100.0, cur / total * 100)
        mtimes = c.get("mtimes") or {}
        # 该作品是否存在「监测期内真实突破时刻」
        has_real = any(mtimes.get(t) is not None
                       for t in range(1, show_tier + 1) if cur >= t * STEP)
        scale, ticks = "", ""
        first_pre_shown = False
        for t in range(1, show_tier + 1):
            left = t / show_tier * 100
            achieved = cur >= t * STEP
            if achieved:
                ts = mtimes.get(t)
                if ts is not None:
                    lab, cls = _fmt_time(ts), "d"
                elif has_real:
                    # 混合情况：部分档位监测期内破，其余监测前已破
                    lab, cls = "已达成", "p"
                elif not first_pre_shown:
                    # 全部档位均为监测前已达成：仅在首个档位标注一次
                    lab, cls = "已达成", "p"
                    first_pre_shown = True
                else:
                    lab, cls = "", ""
            else:
                lab, cls = f"{t}00万", "t"
            scale += (f"<span class='{cls}' style='left:{left:.3f}%' "
                      f"title='{t}00万'>{lab}</span>")
            ticks += (f"<span class='ms-tk {'on' if achieved else ''}' "
                      f"style='left:{left:.3f}%'><i></i></span>")
        title = (c["desc"] or "")[:30] or c["aweme_id"][:8]
        url = _video_url(c["aweme_id"])
        cur_h = humanize(cur)
        rows += f"""
<div class='ms-row'>
  <div class='ms-top'>
    <a class='ms-title' href='{url}' target='_blank' rel='noopener' title='{title}'>{title}</a>
    <span class='ms-cur'>{cur_h}</span>
  </div>
  <div class='ms-scale'>{scale}</div>
  <div class='ms-bar'>
    <div class='ms-track'></div>
    <div class='ms-fill' style='width:{fill_pct:.2f}%'></div>
    {ticks}
  </div>
</div>"""
    return f"""
<div class='ms-wrap'>
  <div class='ms-head'>
    <span class='h'>破百万节点</span>
    <span class='meta'>MILESTONES · {len(eligible)} 件作品已破百万</span>
  </div>
  <div class='ms-list'>{rows}</div>
  <div class='ms-legend'>
    <span class='lg'><span class='sw fill'></span>已破档</span>
    <span class='lg'><span class='sw off'></span>未达</span>
  </div>
</div>"""


def build_data():
    prof = profile_series()  # [(ts, follower, liked, works)]
    delta = _hourly_delta(prof)
    labels = [r[0] for r in delta]
    followers = [r[1] for r in delta]
    followers_delta = [r[2] for r in delta]
    liked = [r[2] for r in prof]
    works_pub = [r[3] for r in prof]

    posts = post_list()
    meta_map = {}
    for p in posts:
        meta_map[p[0]] = {"desc": p[1], "create_time": p[2], "cover": p[3],
                          "share": p[4], "play": p[5], "download": p[6], "last": p[7]}

    cards = []
    for aid, m in meta_map.items():
        latest = latest_post_stats(aid)
        series = post_stats_series(aid)
        if not latest:
            continue
        cards.append({
            "aweme_id": aid, "desc": m["desc"], "create_time": m["create_time"],
            "cover": m["cover"], "share": m["share"],
            "digg": latest[1], "comment": latest[2], "collect": latest[3],
            "share_c": latest[4], "play": latest[5],
            "spark": [r[1] for r in series] if series else [latest[1]],
            "hours": len(series),
            "mtimes": _milestone_times(series),
            "cur_digg": latest[1],
        })
    cards.sort(key=lambda x: x.get("create_time") or 0, reverse=True)

    boards = {
        "topic": board_latest("topic"),
    }

    # 发布时间 × 点赞（按发布时间升序，对数轴；附带 aweme_id/url 供图表点位跳转）
    pub = sorted([c for c in cards if c.get("create_time")], key=lambda x: x["create_time"])
    publish = [{
        "t": _fmt_date(c["create_time"]),
        "digg": c["digg"],
        "desc": (c["desc"] or "")[:30] or c["aweme_id"][:8],
        "aweme_id": c["aweme_id"],
        "url": _video_url(c["aweme_id"]),
    } for c in pub]

    # 头部展示用资料（avatar_url / profile_url 在 meta 中持久化）
    head = {
        "nickname": get_meta("last_profile_nickname") or TARGET_NAME,
        "sec_uid": get_meta("sec_uid") or "",
        "aweme_count_pub": latest_profile()[3] if latest_profile() else 0,
        "avatar_url": get_meta("avatar_url") or "",
        "profile_url": get_meta("profile_url")
                       or (f"https://www.douyin.com/user/{get_meta('sec_uid') or ''}"
                           if get_meta("sec_uid") else ""),
    }

    return {
        "labels": labels, "followers": followers, "followers_delta": followers_delta,
        "liked": liked, "works_pub": works_pub,
        "post_cards": cards, "boards": boards, "publish": publish,
        "head": head,
        "mode": _mode(), "post_count": len(meta_map),
    }


def _board_url(name):
    """抖音挑战/话题搜索 URL（避免 # 等特殊字符打不开）"""
    return f"https://www.douyin.com/search/{urllib.parse.quote(name)}?type=challenge"


def _video_url(aweme_id):
    return f"https://www.douyin.com/video/{aweme_id}"


def _board_rows(items, limit=10):
    if not items:
        return "<tr><td colspan='3' class='muted'>暂无数据</td></tr>"
    rows = ""
    for it in items[:limit]:
        extra = _board_extra_str(it.get("extra"))
        name = it['name']
        url = _board_url(name)
        rows += (f"<tr class='board-row'><td class='rk'>#{it['rank']}</td>"
                 f"<td><a href='{url}' target='_blank' rel='noopener' "
                 f"title='在抖音中查看 {name}'>{name}</a></td>"
                 f"<td class='muted'>{extra or '—'}</td></tr>")
    return rows


def _board_chips(items, limit=12):
    if not items:
        return "<div class='muted'>暂无数据</div>"
    out = ""
    for it in items[:limit]:
        extra = _board_extra_str(it.get("extra"))
        name = it['name']
        url = _board_url(name)
        out += (f"<a class='tg' href='{url}' target='_blank' rel='noopener' "
                f"title='在抖音查看 {name}'># {name}"
                f"<span class='v'>{extra or '—'}</span></a>")
    return f"<div class='ed-topics-row'>{out}</div>"


def _work_thumb(c):
    """作品缩略图卡：封面图 + 底部深绿渐变遮罩（赞数 + 标题）。

    破百万节点（与作品强关联）改为缩略图标签：已破百万的作品在左上角
    加「已破 X 百万」胶囊，底部显示突破时间；监测前已破显示「已达成」。
    """
    title = (c["desc"] or "")[:40] or c["aweme_id"][:8]
    url = _video_url(c["aweme_id"])
    cover = c.get("cover") or ""
    likes = humanize(c["digg"])
    cur = c.get("cur_digg") or 0
    max_tier = int(cur // 1_000_000)
    mt_badge, mt_time = "", ""
    if max_tier >= 1:
        mtimes = c.get("mtimes") or {}
        top_ts = None
        for t in range(max_tier, 0, -1):
            ts = mtimes.get(t)
            if ts is not None:
                top_ts = ts
                break
        mt_time = _fmt_time(top_ts) if top_ts else "已达成"
        mt_badge = f"<span class='mt-badge'>已破 {max_tier} 百万</span>"
    heart = ("<svg viewBox='0 0 24 24' aria-hidden='true'>"
             "<path d='M12 21s-7.5-4.9-10-9.2C.4 8.3 2 4.8 5.3 4.8c2 0 3.3 1.1 4.2 2.4 "
             "C10.4 5.9 11.7 4.8 13.7 4.8c3.3 0 4.9 3.5 3.3 6.9C19.5 16.1 12 21 12 21z'/></svg>")
    if cover:
        # 加载失败回退为应援绿渐变占位
        onerr = "this.style.display='none';this.parentNode.classList.add('miss')"
        img = f"<img src='{cover}' alt='' loading='lazy' onerror=\"{onerr}\">"
    else:
        img = ""
    time_line = f"<div class='mt-time'>{mt_time}</div>" if mt_badge else ""
    return f"""
<a class='wt{' miss' if not cover else ''}' href='{url}' target='_blank' rel='noopener' title='{title}'>
  {img}
  {mt_badge}
  <div class='scrim'>
    <div class='lk'>{heart}{likes}</div>
    <div class='ti'>{title}</div>
    {time_line}
  </div>
</a>"""


def render():
    d = build_data()
    has = bool(d["labels"]) and bool(d["post_cards"])
    mode = d["mode"]

    if not has:
        fans = liked = works = 0
        fans_d = liked_d = works_d = "<div class='v'>—</div>"
        last_update = "—"
        thumbs_html = ""
        c_fans = c_liked = c_pub = "<div class='chart-empty'>暂无数据</div>"
        tp_chips = "<div class='muted'>暂无数据</div>"
        head_html = ""
    else:
        fans = d["followers"][-1]
        liked = d["liked"][-1]
        works = d["works_pub"][-1] or d["post_count"]
        fans_1h = d["followers_delta"][-1] if d["followers_delta"] else 0
        liked_1h = (d["liked"][-1] - d["liked"][-2]) if len(d["liked"]) >= 2 else 0
        # 监测期内相对起始的总变化量（≥1 个数据点就有意义）
        fans_total = (d["followers"][-1] - d["followers"][0]) if d["followers"] else 0
        liked_total = (d["liked"][-1] - d["liked"][0]) if d["liked"] else 0
        last_update = d["labels"][-1]

        # KPI 卡片：总值 + 括号内写「具体到个位的整数」+ 下方保留「近1小时/监测期」delta
        def _sign_html(n):
            if n > 0: return f"<b class='pos'>+{humanize(n)}</b>"
            if n < 0: return f"<b class='neg'>{humanize(n)}</b>"
            return "<b class='zero'>±0</b>"

        fans_d = (f"<div class='v'>{humanize(fans)} "
                  f"<span class='raw'>({fans:,})</span></div>"
                  f"<div class='d'>近1小时 ({_sign_html(fans_1h)}) "
                  f"· 监测期 {_sign_html(fans_total)}</div>")
        liked_d = (f"<div class='v'>{humanize(liked)} "
                   f"<span class='raw'>({liked:,})</span></div>"
                   f"<div class='d'>近1小时 ({_sign_html(liked_1h)}) "
                   f"· 监测期 {_sign_html(liked_total)}</div>")
        works_d = (f"<div class='v'>{humanize(works)} "
                   f"<span class='raw'>({works:,})</span></div>"
                   f"<div class='d'>已入库 {d['post_count']} · "
                   f"近1小时 {_sign_html(works - (d['works_pub'][-2] if len(d['works_pub'])>=2 else 0))}</div>")

        thumbs_html = "".join(
            _work_thumb(c) for c in d["post_cards"])

        # 粉丝趋势 / 获赞趋势：用「相对起始」画法（首点 = 0）——
        # 解决「百万级绝对值巨大横线、波动看不出来」的问题
        fans_x = [l.split(" ")[-1][:5] if " " in l else l for l in d["labels"]]
        c_fans = _svg_line(fans_x, d["followers"], GREEN_D,
                           relative_start=True,
                           point_titles=[
                               f'{l}\n粉丝 {humanize(v)}（{(v - d["followers"][0]):+,}）'
                               for l, v in zip(d["labels"], d["followers"])
                           ],
                           chart_id="chart-fans")
        c_liked = _svg_line(fans_x, d["liked"], GREEN_BR,
                            relative_start=True,
                            point_titles=[
                                f'{l}\n获赞 {humanize(v)}（{(v - d["liked"][0]):+,}）'
                                for l, v in zip(d["labels"], d["liked"])
                            ],
                            chart_id="chart-liked")
        # 发布时间 × 点赞：对数轴折线 + JS 自绘 tooltip（半透明绿底）+ 点击跳转抖音视频
        pub_x = [p["t"][5:] for p in d["publish"]]  # mm-dd
        pub_titles = [
            f'{p["t"]}  点赞 {_fmt_num(p["digg"])}\n{p["desc"]}\n· 点击查看抖音原作品 →'
            for p in d["publish"]
        ]
        pub_hrefs = [p.get("url", "") for p in d["publish"]]
        c_pub = _svg_line(pub_x, [p["digg"] for p in d["publish"]],
                          GREEN_D, w=1140, log=True,
                          point_titles=pub_titles, point_hrefs=pub_hrefs,
                          chart_id="chart-pub")

        tp_chips = _board_chips(d["boards"]["topic"])

    data_json = json.dumps(d, ensure_ascii=False)
    works_count = d["post_count"]

    # 头部：头像 + 名字 + 抖音号 → 整块包到主页链接
    head = d.get("head") or {}
    avatar = head.get("avatar_url") or ""
    if avatar:
        # 抖音图链常见 301，需直链扩展；Dashboard 内嵌可用 https 协议即可
        avatar_html = f"<img class='hero-avatar' src='{avatar}' alt='张真源'>"
    else:
        avatar_html = "<div class='hero-fallback'>张</div>"
    profile_url = head.get("profile_url") or "https://www.douyin.com/"
    nickname = head.get("nickname") or TARGET_NAME
    public_id = "29832527783"
    sec_uid = head.get("sec_uid") or ""
    sec_enc = urllib.parse.quote(sec_uid)
    nick_enc = urllib.parse.quote(nickname)
    if head.get("aweme_count_pub") and not has:
        works_d_v = "—"
    header_html = f"""
<nav class='nav'>
  <div class='nav-in'>
    <a class='brand' href='{profile_url}' target='_blank' rel='noopener' title='在抖音打开 {nickname} 主页'>
      <span class='logo'>张</span><span>{nickname}</span>
    </a>
    <div class='nav-links'>
      <a href='/dashboard.html' data-nav='reload' class='active'>看板</a>
      <a href='/fetch.html' data-nav='backend'>抓取账号</a>
      <a href='/admin' data-nav='backend'>后台管理</a>
    </div>
    <div class='nav-status'><span class='dot-live'></span>最近更新 {last_update}</div>
  </div>
</nav>"""

    html = f"""<!DOCTYPE html>
<html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>张真源 · 抖音数据月刊</title>
<meta http-equiv='refresh' content='300'>

<style>{PAGE_CSS}{DASHBOARD_CSS}</style></head>
<body>
{header_html}
<div class='wrap'>

<div class='ed-masthead'>
  <span class='motto'>ALL FOR ZZY</span>
  <div class='lt'>{nickname} · 抖音数据月刊</div>
  <div class='rt'>抖音号 <b>{public_id}</b><br>更新时间 {last_update}</div>
  <span class='deco' aria-hidden='true'>
    <svg class='bf' viewBox='0 0 100 60'>
      <path d='M 50 30 Q 30 8 14 16 Q 6 22 16 32 Q 34 38 50 32 Z'/>
      <path d='M 50 30 Q 70 8 86 16 Q 94 22 84 32 Q 66 38 50 32 Z'/>
      <path d='M 50 32 Q 36 42 24 50 Q 20 54 30 52 Q 42 48 50 36 Z'/>
      <path d='M 50 32 Q 64 42 76 50 Q 80 54 70 52 Q 58 48 50 36 Z'/>
      <ellipse cx='50' cy='32' rx='1.2' ry='5'/>
    </svg>
    <svg class='sd' viewBox='0 0 64 24'>
      <circle cx='6' cy='6' r='1.2'/><circle cx='14' cy='14' r='.7'/>
      <circle cx='22' cy='4' r='.9'/><circle cx='30' cy='18' r='.5'/>
      <circle cx='38' cy='10' r='1'/><circle cx='46' cy='6' r='.6'/>
      <circle cx='54' cy='16' r='.9'/><circle cx='58' cy='4' r='.5'/>
    </svg>
  </span>
</div>
<div class='ed-vol'>本期 <b>ISSUE № 038</b> · 自动每小时更新 · 监测第 17 小时</div>

<div class='ed-stat'>
  <span class='deco' aria-hidden='true'>
    <svg viewBox='0 0 100 60'>
      <path d='M 50 30 Q 32 10 16 18 Q 8 24 18 32 Q 35 38 50 32 Z'/>
      <path d='M 50 30 Q 68 10 84 18 Q 92 24 82 32 Q 65 38 50 32 Z'/>
      <path d='M 50 32 Q 38 42 26 50 Q 22 54 30 52 Q 42 48 50 36 Z'/>
      <path d='M 50 32 Q 62 42 74 50 Q 78 54 70 52 Q 58 48 50 36 Z'/>
    </svg>
  </span>
  <div>
    <div class='label'>01 ──── FOLLOWERS · 粉丝</div>
    <div class='num'>{fans:,}<span class='raw'>总数 · {humanize(fans)}</span></div>
    <div class='sub'>粉丝总数 · 监测每小时刷新一次</div>
  </div>
  <div class='meta'>
    <div>近 1 小时 <b>{_sign_html(fans_1h)}</b></div>
    <div>监测期累计 <b>{_sign_html(fans_total)}</b></div>
  </div>
</div>

<div class='ed-rule'></div>

<div class='ed-stat'>
  <span class='deco' aria-hidden='true'>
    <svg viewBox='0 0 100 60'>
      <path d='M 50 30 Q 32 10 16 18 Q 8 24 18 32 Q 35 38 50 32 Z'/>
      <path d='M 50 30 Q 68 10 84 18 Q 92 24 82 32 Q 65 38 50 32 Z'/>
      <path d='M 50 32 Q 38 42 26 50 Q 22 54 30 52 Q 42 48 50 36 Z'/>
      <path d='M 50 32 Q 62 42 74 50 Q 78 54 70 52 Q 58 48 50 36 Z'/>
    </svg>
  </span>
  <div>
    <div class='label'>02 ──── TOTAL PRAISE · 累计获赞</div>
    <div class='num'>{liked:,}<span class='raw'>累计 · {humanize(liked)}</span></div>
    <div class='sub'>累计获赞总数</div>
  </div>
  <div class='meta'>
    <div>近 1 小时 <b>{_sign_html(liked_1h)}</b></div>
    <div>监测期累计 <b>{_sign_html(liked_total)}</b></div>
  </div>
</div>

<div class='ed-rule'></div>

<div class='ed-charts'>
  <div class='ed-chart'>
    <div class='h'>粉丝增长曲线</div>
    <div class='sub'>RELATIVE · 相对起始</div>
    <div class='frame chart-wrap'>{c_fans}</div>
  </div>
  <div class='ed-chart'>
    <div class='h'>获赞增长曲线</div>
    <div class='sub'>RELATIVE · 相对起始</div>
    <div class='frame chart-wrap'>{c_liked}</div>
  </div>
</div>

<div class='ed-pub'>
  <div class='h'>作品发布时间 × 点赞</div>
  <div class='sub'>LOG SCALE · 对数坐标 · 点击数据点在抖音打开原作品</div>
  <div class='frame chart-wrap'>{c_pub}</div>
</div>

<div class='ed-wall'>
  <div class='ed-list-head'>
    <span class='h'>全部作品 · 共 {works_count} 件</span>
    <span class='meta'>点击缩略图打开抖音原作品</span>
  </div>
  <div class='wall'>
    {thumbs_html}
  </div>
</div>

<div class='ed-export'>
  <a class='ed-xlsx-btn' href='/api/export-xlsx?sec_uid={sec_enc}&name={nick_enc}' data-nav='backend'>下载 Excel 数据</a>
</div>



<div class='ed-list' style='margin-top:42px'>
  <div class='ed-list-head'>
    <span class='h'>话题 · 张真源相关</span>
    <span class='meta'>TOPICS · 点击跳转抖音搜索</span>
  </div>
  <div class='ed-topics'>{tp_chips}</div>
</div>

<div class='foot'>
  <div class='motto-row'>ZHANG ZHEN YUAN</div>
  <b>张真源 · 抖音数据月刊</b> · 本地部署 · 仅数据展示，无云端后端
  <div class='latin'>All for ZZY — Follow the light across time and space</div>
</div>

</div>

<script>
(function(){{
  // 给所有带 data-i 的 SVG 圆点装自绘 tooltip
  function esc(s){{return (s||'').replace(/[&<>"]/g, c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));}}
  document.querySelectorAll('svg [data-i]').forEach(function(g){{
    var parent = g.closest('svg');
    if(!parent) return;
    var wrap = parent.parentElement;
    if(!wrap) return;
    var titleTag = g.querySelector('title');
    var title = titleTag ? titleTag.textContent : '';
    if(!title) return;
    g.style.cursor = 'pointer';
    g.addEventListener('mouseenter', function(ev){{
      if(wrap.__tip) return;
      var tip = document.createElement('div');
      tip.className = 'dy-tip';
      tip.textContent = title;
      wrap.style.position='relative';
      wrap.appendChild(tip);
      wrap.__tip = tip;
      var r = g.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
      tip.style.left = (r.left + r.width/2 - wr.left) + 'px';
      tip.style.top  = (r.top - wr.top - 8) + 'px';
    }});
    g.addEventListener('mouseleave', function(){{
      if(wrap.__tip) {{ wrap.__tip.remove(); wrap.__tip = null; }}
    }});
  }});
}})();

(function(){{
  // 自适应导航：本地服务（有后端）真实跳转；云端静态托管 / 离线（无后端）时
  // 点击「抓取账号」「后台管理」就地提示
  function probe(){{
    return fetch('/api/users').then(function(r){{return r.json();}})
      .then(function(j){{return !!(j && j.ok);}})
      .catch(function(){{return false;}});
  }}
  function showHint(a, msg){{
    if(!a || !a.parentNode) return;
    var s = document.createElement('span');
    s.className = 'nav-note';
    s.textContent = msg;
    a.parentNode.replaceChild(s, a);
  }}
  var reloadA = document.querySelector('a[data-nav="reload"]');
  var backends = [].slice.call(document.querySelectorAll('a[data-nav="backend"]'));
  if (reloadA) {{
    reloadA.addEventListener('click', function(e){{ e.preventDefault(); location.reload(); }});
  }}
  backends.forEach(function(a){{
    a.addEventListener('click', function(e){{
      e.preventDefault();
      probe().then(function(ok){{
        if (ok) {{ window.location.href = a.getAttribute('href'); }}
        else {{ showHint(a, '需在本地运行监测服务后使用'); }}
      }});
    }});
  }});
}})();
</script>
</body></html>"""
    DASHBOARD_PATH.write_text(html, encoding="utf-8")
    return DASHBOARD_PATH
