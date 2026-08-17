"""公共模块：配置加载、路径、日志、工具函数。"""
import os
import re
import json
import math
import sqlite3
import logging
from pathlib import Path

# 项目根目录（本文件位于 <root>/src/common.py）
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("douyin-monitor")

# 公共请求 UA（抖音 web 端需桌面端 UA 才返回真实 JSON）
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def load_env():
    """极简 .env 解析（不依赖第三方库）。"""
    env_path = ROOT / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_ENV = load_env()


def cfg(key: str, default: str = ""):
    """优先级：环境变量 > .env > default。"""
    return os.getenv(key, _ENV.get(key, default))


# ---- 配置项 ----
# 数据源（唯一权威开关）：douyin_web=免费 Cookie 模式；maxhub=付费 API（仅显式设为 maxhub 且配 Key 才走）
DATA_SOURCE = cfg("DATA_SOURCE", "douyin_web")
# 数据源优先级：抖音 web 端（需 Cookie，免费真实）> MaxHub（付费兜底）
MAXHUB_API_KEY = cfg("MAXHUB_API_KEY")
# 抖音登录 Cookie（等同账号凭据，建议用小号）。用于免费真实拉取主页数据。
DOUYIN_COOKIE = cfg("DOUYIN_COOKIE", "")
# 真实 sec_uid（已解析自分享短链，预填避免每次请求依赖短链）
DOUYIN_SEC_UID = cfg("DOUYIN_SEC_UID",
                     "MS4wLjABAAAAOpX2NjhZ8eTZFkP6BeKiWOxQXo264vHMFU8Zngk6Nrh61qKZjDjJO5ZvnyoZKN_E")
# 分享短链（用于无 sec_uid 时解析；公开、无需 Cookie）
DOUYIN_SHARE_URL = cfg("DOUYIN_SHARE_URL", "https://v.douyin.com/RQ20zd4XbUo/")
DOUYIN_SHORT_ID = cfg("DOUYIN_SHORT_ID", "29832527783")
TARGET_NAME = cfg("TARGET_NAME", "张真源")
TRACK_RECENT_DAYS = int(cfg("TRACK_RECENT_DAYS", "7"))
MAX_POST_DETAIL = int(cfg("MAX_POST_DETAIL", "15"))
QQ_SMTP_ENABLED = cfg("QQ_SMTP_ENABLED", "false").lower() in ("1", "true", "yes", "on")
QQ_EMAIL = cfg("QQ_EMAIL", "")
QQ_SMTP_PASS = cfg("QQ_SMTP_PASS", "")
PUSH_TO_QQ = cfg("PUSH_TO_QQ", "")
# 去水印解析 token（nologo-open-api）。未配置时 downloader 会提示用户先配置。
NOLOGO_TOKEN = cfg("NOLOGO_TOKEN", "")
# 本地 web 服务端口
SERVER_PORT = int(cfg("SERVER_PORT", "8765"))

DB_PATH = DATA_DIR / "monitor.db"
DASHBOARD_PATH = DATA_DIR / "dashboard.html"
DOWNLOADS_HTML = DATA_DIR / "downloads.html"
DOWNLOAD_DIR = DATA_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR = DATA_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_DIR = DATA_DIR / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def dig(obj, *paths, default=None):
    """从嵌套 dict/list 中按多条候选路径取值，返回第一个成功的值。"""
    for path in paths:
        cur = obj
        ok = True
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
                cur = cur[int(key)]
            else:
                ok = False
                break
        if ok:
            return cur
    return default


def humanize(n):
    """数字本地化：万/亿。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if n is None:
        return "-"
    if abs(n) >= 1e8:
        return f"{n/1e8:.2f}亿"
    if abs(n) >= 1e4:
        return f"{n/1e4:.1f}万"
    if abs(n) >= 1e3:
        return f"{n:,.0f}"
    return f"{n:.0f}" if float(n).is_integer() else f"{n:.1f}"


def now_iso():
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


# ---- 轻量 KV 元数据存储（避免循环依赖，独立建表）----
def get_meta(key, default=None):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_meta(key, value):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
    conn.commit()
    conn.close()


# ---- 纯绿设计系统（看板 / 抓取页 / 后台 共用，零外部依赖）----
PAGE_CSS = """
:root{
--g:#16a34a;--gd:#157a3a;--gl:#22c55e;--gxl:#f1faf4;--gxx:#ffffff;
/* 张真源应援深绿：H1/H2/KPI 大数字等主要文字统一用 --ink（深绿） */
--ink:#14532d;--ink-deep:#0a3d24;--ink-mid:#1f5e3a;
--muted:#4a7060;--muted2:#7a9a8c;
--paper:#faf8f3;--rule:#1a1a1a;--rule2:#e6e3dc;--rule3:#c9c4b8;
/* 暖橘点缀（应援海报里的补丁色，仅作 motto / 编号等小标记用） */
--accent-warm:#c2410c;
--bd:rgba(20,124,58,.10);--bd2:rgba(20,124,58,.20);
--shadow:0 1px 2px rgba(16,58,43,.04),0 10px 30px rgba(16,58,43,.07);
--shadow-sm:0 1px 2px rgba(16,58,43,.05);
--shadow-lg:0 2px 6px rgba(16,58,43,.06),0 24px 50px rgba(16,58,43,.12);
--radius:20px;--radius-sm:13px;
--ff:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
--serif:"Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSongti-SC-Regular","SimSun","宋体",Georgia,"Times New Roman",serif;
}
*{box-sizing:border-box;margin:0;padding:0;}
html{scroll-behavior:smooth;}
html,body{font-family:var(--ff);color:var(--ink);min-height:100vh;-webkit-font-smoothing:antialiased;
line-height:1.55;background:var(--paper);background-attachment:fixed;}
a{color:inherit;text-decoration:none;}
img{max-width:100%;}

/* 顶部导航 */
.nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.7);
backdrop-filter:saturate(180%) blur(16px);-webkit-backdrop-filter:saturate(180%) blur(16px);
border-bottom:1px solid var(--bd);box-shadow:0 1px 0 rgba(255,255,255,.6);}
.nav-in{max-width:1080px;margin:0 auto;padding:13px 22px;display:flex;align-items:center;
justify-content:space-between;gap:16px;}
.brand{display:flex;align-items:center;gap:11px;font-weight:800;letter-spacing:.3px;color:var(--gd);font-size:16px;}
.brand .logo{width:30px;height:30px;border-radius:10px;background:linear-gradient(135deg,var(--gl),var(--gd));
color:#fff;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:800;
box-shadow:0 6px 14px rgba(22,163,74,.3);}
.nav-links{display:flex;gap:5px;align-items:center;}
.nav-links a{padding:8px 15px;border-radius:999px;font-size:13px;font-weight:600;color:var(--gd);transition:.2s;}
.nav-links a:hover{background:rgba(22,163,74,.1);}
.nav-links a.active{background:linear-gradient(135deg,var(--g),var(--gd));color:#fff;
box-shadow:0 6px 16px rgba(22,163,74,.28);}
.nav-status{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:7px;}
.nav-status .dot-live{width:8px;height:8px;border-radius:50%;background:var(--gl);
box-shadow:0 0 0 4px rgba(34,197,94,.16);animation:pulse 2.4s ease-in-out infinite;}
@keyframes pulse{0%,100%{box-shadow:0 0 0 3px rgba(34,197,94,.18);}50%{box-shadow:0 0 0 6px rgba(34,197,94,.06);}}

/* 容器与区块 */
.wrap{max-width:980px;margin:0 auto;padding:24px 22px 56px;}
.section-h{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:48px 0 18px;
padding-top:30px;border-top:1px solid var(--rule);}
.section-h h2{font-family:var(--serif);font-size:26px;color:var(--ink);font-weight:700;letter-spacing:-.2px;line-height:1.2;}
.section-sub{font-size:12.5px;color:var(--muted);font-weight:500;margin-top:5px;letter-spacing:.2px;}
.hr-title{font-size:15px;color:var(--gd);font-weight:700;margin:0 0 14px;display:flex;align-items:center;gap:9px;}
.hr-title::before{content:"";width:4px;height:16px;border-radius:3px;
background:linear-gradient(var(--gl),var(--gd));display:inline-block;}

/* 卡片 */
.card{background:var(--gxx);border:1px solid var(--bd);border-radius:var(--radius);
box-shadow:var(--shadow);transition:transform .28s cubic-bezier(.2,.7,.2,1),box-shadow .28s;}
.card:hover{transform:translateY(-4px);box-shadow:var(--shadow-lg);}

/* 按钮 */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;
font-family:var(--ff);font-weight:600;font-size:13px;padding:10px 18px;border-radius:999px;
border:1px solid var(--rule);cursor:pointer;transition:.2s;white-space:nowrap;background:transparent;color:var(--ink);}
.btn:hover{background:var(--ink);color:#fff;}
.btn-primary{background:var(--ink);color:#fff;border-color:var(--ink);}
.btn-primary:hover{background:var(--g);border-color:var(--g);}
.btn-ghost{background:transparent;color:var(--ink);border-color:var(--rule);}
.btn:disabled{opacity:.55;cursor:not-allowed;}

/* 表单 */
.field{width:100%;padding:14px 16px;border:1px solid var(--bd2);border-radius:var(--radius-sm);
font-size:14px;font-family:inherit;color:var(--ink);background:#fff;outline:none;transition:.18s;}
.field:focus{border-color:var(--g);box-shadow:0 0 0 4px rgba(22,163,74,.12);}
.field::placeholder{color:#a8bbb0;}

/* 标签 / 徽标 */
.badge{display:inline-flex;align-items:center;padding:4px 12px;border-radius:999px;font-size:12px;
font-weight:700;line-height:1.5;letter-spacing:.3px;}
.badge-soft{background:rgba(22,163,74,.1);color:var(--gd);}
.badge-line{border:1px solid var(--bd2);color:var(--gd);}
.badge-g{background:var(--g);color:#fff;}

/* 表格 */
.tbl{width:100%;border-collapse:collapse;font-size:13px;}
.tbl th{text-align:left;padding:13px 14px;color:var(--muted);font-weight:600;font-size:11.5px;
letter-spacing:.06em;text-transform:uppercase;border-bottom:1px solid var(--bd);}
.tbl td{padding:13px 14px;border-bottom:1px solid rgba(20,124,58,.07);vertical-align:middle;}
.tbl tbody tr{transition:.15s;}
.tbl tbody tr:hover{background:rgba(22,163,74,.05);}
.tbl a{color:var(--ink);font-weight:600;}
.tbl a:hover{color:var(--gd);text-decoration:underline;}
.rk{color:var(--gd);font-weight:800;width:46px;}

/* 提示框 / 空态 */
.box{background:var(--gxl);border:1px solid var(--bd);border-radius:var(--radius-sm);padding:16px 18px;
font-size:14px;line-height:1.65;}
.box.err{background:#fef2f2;border-color:#fecaca;color:#991b1b;}
.empty{text-align:center;color:var(--muted);padding:46px 16px;font-size:13.5px;}
.muted{color:var(--muted);font-size:12px;}
.foot{text-align:center;color:var(--muted2);font-size:12px;margin-top:40px;letter-spacing:.4px;}

/* 动效 */
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes draw{to{stroke-dashoffset:0}}
@keyframes fadeArea{from{opacity:0}to{opacity:1}}
.fade-in{animation:fadeIn .6s ease both;}
.fade-up{animation:fadeUp .7s cubic-bezier(.2,.7,.2,1) both;}
.dy-line{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 1.5s ease forwards;}
.dy-area{opacity:0;animation:fadeArea 1s ease .25s forwards;}

/* 响应式 */
@media (max-width:760px){
.wrap{padding:16px 14px 38px;}
.nav-in{padding:11px 14px;gap:10px;}
.nav-status{display:none;}
.nav-links a{padding:7px 12px;font-size:12.5px;}
.section-h{flex-direction:column;align-items:flex-start;gap:8px;margin:30px 0 14px;}
}
@media (max-width:480px){
.nav-links a.extra{display:none;}
}
"""
