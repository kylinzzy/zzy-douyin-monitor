"""每日报告 + 小时摘要（绿色主题，署名 kylinwu）。
无数据时展示明确空状态，不生成编造内容。
"""
from common import (REPORT_DIR, TARGET_NAME, humanize, today_str,
                    now_iso, get_meta)
from storage import (latest_profile, profile_series, post_list,
                     post_stats_series, board_latest, count_rows)

GREEN = "#16a34a"
GREEN_D = "#15803d"
GREEN_L = "#dcfce7"


def _mode_label():
    meta = get_meta("mode")
    if meta == "awaiting-config" or (not meta and count_rows("profile_hourly") == 0):
        return "等待配置"
    if meta == "error":
        return "采集异常"
    if count_rows("profile_hourly") == 0:
        return "暂无数据"
    return "实时"


def _today_bounds():
    t = today_str()
    return f"{t} 00:00:00", f"{t} 23:59:59"


def daily_delta():
    series = profile_series()
    today = today_str()
    rows = [r for r in series if r[0].startswith(today)]
    if len(rows) >= 2:
        f0, l0 = rows[0][1], rows[-1][1]
        t0, t1 = rows[0][2], rows[-1][2]
        return (l0 - f0, t1 - t0, rows[-1][3], l0, t1)
    if rows:
        return (0, 0, rows[-1][3], rows[-1][1], rows[-1][2])
    return (0, 0, 0, 0, 0)


def top_posts(n=10):
    posts = post_list()
    enriched = []
    for p in posts:
        aweme_id = p[0]
        s = post_stats_series(aweme_id)
        last = s[-1] if s else (None, 0, 0, 0, 0, 0)
        enriched.append({
            "aweme_id": aweme_id, "desc": p[1], "create_time": p[2],
            "cover": p[3], "share": p[4], "play": p[5], "download": p[6],
            "digg": last[1] or 0, "comment": last[2] or 0,
            "collect": last[3] or 0, "share_c": last[4] or 0,
        })
    enriched.sort(key=lambda x: x["digg"], reverse=True)
    return enriched[:n]


def board_block(title, items):
    if not items:
        return f"**{title}**：暂无数据\n"
    lines = [f"**{title}**"]
    for it in items[:10]:
        extra = " · ".join(f"{k}:{humanize(v)}" for k, v in it["extra"].items())
        lines.append(f"{it['rank']}. {it['name']} — {extra}")
    return "\n".join(lines) + "\n"


def generate_daily():
    date = today_str()
    mode = _mode_label()
    has_data = count_rows("profile_hourly") > 0

    if not has_data:
        md = f"""# 张真源 · 抖音每日数据报告

> 日期：{date} ｜ 抖音号：29832527783 ｜ 模式：**{mode}**

## 当前状态

| 指标 | 当前 | 当日变化 |
|---|---|---|
| 粉丝 | — | — |
| 获赞 | — | — |
| 作品数 | — | — |

## 待办

1. 访问 https://www.aconfig.cn 获取 `MAXHUB_API_KEY`；
2. 写入 `.env`：`MAXHUB_API_KEY=你的key`；
3. 执行 `.venv/bin/python src/run.py --once`，本报告将自动填充真实数据。

> 本项目不再以 demo 模式编造任何数据，避免误导。

---

## 单作品下载（无需 MAXHUB_API_KEY）

如果你想下载主页某个具体作品，可使用本地下载器：

```
.venv/bin/python src/server.py
# 浏览器访问 http://localhost:8765/downloads.html
```

将抖音分享链接粘贴进输入框即可解析并下载到本地。

---

© kylinwu · 张真源抖音数据监测
"""
    else:
        d_fans, d_liked, works, fans, liked = daily_delta()
        posts = top_posts(10)
        ch = board_latest("challenge")
        ht = board_latest("hot_total")
        tp = board_latest("topic")

        md = f"""# 张真源 · 抖音每日数据报告

> 日期：{date} ｜ 抖音号：29832527783 ｜ 模式：{mode}

## 核心指标
| 指标 | 当前 | 当日变化 |
|---|---|---|
| 粉丝 | {humanize(fans)} | {('+' if d_fans>=0 else '')+humanize(d_fans)} |
| 获赞 | {humanize(liked)} | {('+' if d_liked>=0 else '')+humanize(d_liked)} |
| 作品数 | {humanize(works)} | — |

## 重点作品（按点赞）
| 标题 | 点赞 | 评论 | 收藏 | 分享 | 下载 |
|---|---|---|---|---|---|
"""
        for p in posts:
            dl = p["download"] or p["play"] or ""
            link = f"[下载]({dl})" if dl else "待采集"
            md += (f"| {p['desc'][:18] or p['aweme_id']} | {humanize(p['digg'])} | "
                   f"{humanize(p['comment'])} | {humanize(p['collect'])} | "
                   f"{humanize(p['share_c'])} | {link} |\n")

        md += "\n" + board_block("挑战榜", ch)
        md += "\n" + board_block("热点总榜（娱乐）", ht)
        md += "\n" + board_block("张真源相关话题", tp)

        md += f"""
## 下载方式
- 单个作品：把抖音分享链接粘贴到本地下载器 `/downloads.html` 一键下载。
- 看板：<code>data/dashboard.html</code>
- 历史数据：本地 SQLite <code>data/monitor.db</code>

---
© kylinwu · 张真源抖音数据监测
"""

    md_path = REPORT_DIR / f"{date}.md"
    md_path.write_text(md, encoding="utf-8")
    html_path = REPORT_DIR / f"{date}.html"
    html_path.write_text(_md_to_html(md, date, mode), encoding="utf-8")
    return md_path, html_path


def _md_to_html(md, date, mode):
    rows = md.splitlines()
    out = [f"""<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>
<title>张真源 · 每日报告 {date}</title>
<style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#dcfce7;color:#0f291f;padding:28px;}}
.wrap{{max-width:900px;margin:0 auto;background:#fff;border-radius:14px;padding:26px;box-shadow:0 4px 16px rgba(0,0,0,.06);}}
h1{{color:{GREEN_D};border-bottom:3px solid {GREEN};padding-bottom:8px;}}
h2{{color:{GREEN_D};margin-top:22px;}}
table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px;}}
th,td{{border:1px solid #e3f0e8;padding:8px 10px;text-align:left;}}
th{{background:{GREEN_L};}}
a{{color:{GREEN_D};}}
code{{background:#eef5f0;padding:2px 6px;border-radius:4px;color:#15803d;font-size:13px;}}
.foot{{text-align:center;color:#7a9a8a;font-size:12px;margin-top:18px;}}
</style></head><body><div class='wrap'>"""]
    i = 0
    while i < len(rows):
        line = rows[i]
        if line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("> "):
            out.append(f"<p style='color:#5a7a6a'>{line[2:]}</p>")
        elif line.startswith("|"):
            tbl = []
            while i < len(rows) and rows[i].startswith("|"):
                tbl.append(rows[i]); i += 1
            out.append("<table>")
            for ti, tr in enumerate(tbl):
                cells = [c.strip() for c in tr.strip().strip("|").split("|")]
                if set(cells) == {"---"}:
                    continue
                tag = "th" if ti == 0 else "td"
                out.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            out.append("</table>")
            continue
        elif line.strip() == "":
            pass
        else:
            out.append(f"<p>{line}</p>")
        i += 1
    out.append(f"<div class='foot'>© kylinwu · 张真源抖音数据监测 · {date} · 模式 {mode}</div></div></body></html>")
    return "\n".join(out)


def hourly_summary():
    lp = latest_profile()
    has_data = lp is not None
    mode = _mode_label()
    if has_data:
        ts, nick, fans, liked, works = lp
        d_fans, d_liked, _, _, _ = daily_delta()
        return (f"【张真源 小时播报】{now_iso()}\n"
                f"粉丝 {humanize(fans)}（当日 {('+' if d_fans>=0 else '')+humanize(d_fans)}）\n"
                f"获赞 {humanize(liked)} ｜ 作品 {humanize(works)}\n"
                f"模式：{mode} ｜ 看板：data/dashboard.html")
    else:
        return (f"【张真源 小时播报】{now_iso()}\n"
                f"状态：{mode}（未配置 MAXHUB_API_KEY，无任何数据写入）\n"
                f"操作：编辑 .env 填入 MAXHUB_API_KEY 后重启 run.py\n"
                f"单作品下载：python src/server.py → http://localhost:8765/downloads.html")
