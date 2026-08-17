"""本地 web 服务：dashboard.html / fetch.html / admin + 配套 API。

启动： .venv/bin/python src/server.py [--port 8765]
打开： http://localhost:8765/dashboard.html   张真源小时级看板
       http://localhost:8765/fetch.html       一次性抓取任意抖音账号
       http://localhost:8765/admin            后台管理（需登录，添加/重抓视频链接）
       http://localhost:8765/admin/login      后台登录
"""
import os
import re
import json
import hmac
import hashlib
import secrets
import argparse
import sqlite3
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, quote as _quote
from datetime import datetime

from common import (DATA_DIR, DASHBOARD_PATH, SERVER_PORT,
                    DOUYIN_COOKIE, log, cfg, now_iso, PAGE_CSS)
from exporter import build_workbook_bytes  # noqa: E402
from storage import get_user, get_users, DB_PATH  # noqa: E402

FETCH_HTML = DATA_DIR / "fetch.html"
ADMIN_LOGIN_HTML = DATA_DIR / "admin_login.html"
ADMIN_HOME_HTML = DATA_DIR / "admin.html"

# ---- 页面专属样式（叠加在 common.PAGE_CSS 设计系统之上）----
FETCH_CSS = r"""
.hist{list-style:none;margin-top:12px;display:flex;flex-direction:column;gap:10px;}
.hist li{display:flex;justify-content:space-between;align-items:center;gap:14px;
padding:14px 16px;border:1px solid var(--bd);border-radius:var(--radius-sm);
background:#fff;box-shadow:var(--shadow-sm);}
.u-name{font-weight:700;color:var(--gd);font-size:14px;}
.u-meta{font-size:12px;color:var(--muted);margin-top:3px;}
.u-acts a{color:var(--gd);font-weight:600;margin-left:14px;white-space:nowrap;}
.u-acts a:first-child{margin-left:0;}
.u-acts a:hover{text-decoration:underline;}
.result-card{display:flex;align-items:center;gap:16px;}
.av{width:64px;height:64px;border-radius:50%;object-fit:cover;border:2px solid var(--bd);background:var(--gxl);flex-shrink:0;}
.av-ph{width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,var(--g),var(--gd));color:#fff;
display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:800;flex-shrink:0;}
.stats{display:flex;gap:28px;margin-top:16px;flex-wrap:wrap;}
.stats div{font-size:12px;color:var(--muted);}
.stats b{display:block;color:var(--gd);font-size:22px;font-weight:800;margin-top:3px;font-feature-settings:'tnum';}
.dl{color:var(--gd);font-weight:600;text-decoration:none;}
.dl:hover{text-decoration:underline;}
.warn{color:#b45309;font-size:12px;margin-top:12px;}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;vertical-align:middle;margin-right:6px;}
@keyframes spin{to{transform:rotate(360deg);}}
"""

ADMIN_CSS = r"""
.auth{max-width:380px;margin:40px auto;}
.auth-card{background:#fff;border:1px solid var(--bd);border-radius:var(--radius);padding:30px;box-shadow:var(--shadow);}
.add-box{background:var(--gxl);border:1px solid var(--bd);border-radius:var(--radius-sm);padding:16px;margin:14px 0 8px;
display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
.add-box .field{flex:1;min-width:240px;}
.code{font-family:ui-monospace,Menlo,Consolas,monospace;background:var(--gxl);padding:1px 6px;border-radius:5px;font-size:.92em;color:var(--gd);}
.row-acts a{color:var(--gd);font-weight:600;}
.row-acts a:hover{text-decoration:underline;}
.spinner{display:inline-block;width:13px;height:13px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;vertical-align:middle;margin-right:5px;}
@keyframes spin{to{transform:rotate(360deg);}}
.tbl-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;}
.tbl-scroll .tbl{min-width:600px;}
.tbl td.err{color:#991b1b;text-align:center;}
@media(max-width:760px){.add-box .btn{width:100%;}}
"""

# ---- 后台管理 ----
ADMIN_USER = cfg("ADMIN_USER", "kylinwu")
ADMIN_PASS = cfg("ADMIN_PASS", "kylinwu")
# 用 cfg() 注入密钥；用户没配置则用一次性随机（重启即失效，但本地调试够用）
SESSION_SECRET = cfg("ADMIN_SESSION_SECRET") or secrets.token_hex(32)
SESSION_COOKIE = "dy_admin"

# ---- 鉴权（HMAC-SHA256 签名 cookie，防伪造；本地单用户足够）----
def _sign(payload: str) -> str:
    return hmac.new(SESSION_SECRET.encode("utf-8"),
                    payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_token(user: str) -> str:
    body = f"{user}|{int(datetime.now().timestamp())}"
    sig = _sign(body)
    return f"{body}|{sig}"


def _verify_token(token: str):
    try:
        user, ts, sig = token.rsplit("|", 2)
        if not hmac.compare_digest(sig, _sign(f"{user}|{ts}")):
            return None
        # 7 天内有效
        if int(datetime.now().timestamp()) - int(ts) > 7 * 24 * 3600:
            return None
        return user
    except Exception:
        return None


def _parse_cookie(header: str):
    out = {}
    if not header:
        return out
    for part in header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k] = v
    return out


def _current_user(req_headers) -> str:
    return _verify_token(_parse_cookie(req_headers.get("Cookie", "")).get(SESSION_COOKIE, ""))


# ============================================================
# 页面渲染
# ============================================================
def _render_fetch_html() -> str:
    """一次性抓取入口：粘贴抖音主页链接 → 抓取全部作品+粉丝/获赞 → 下载 Excel / 导出网页。"""
    tpl = r"""<!DOCTYPE html>
<html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>抓取任意抖音账号 · 张真源监测</title>
<style>{CSS}</style></head>
<body>
<nav class='nav'><div class='nav-in'>
  <a class='brand' href='/dashboard.html'><span class='logo'>张</span><span>张真源监测</span></a>
  <div class='nav-links'>
    <a href='/dashboard.html'>看板</a>
    <a href='/fetch.html' class='active'>抓取账号</a>
    <a href='/admin'>后台管理</a>
  </div>
</div></nav>
<div class='wrap'>
  <div class='hr-title'>抓取任意抖音账号</div>
  <p class='muted' style='margin-bottom:18px'>粘贴目标账号的抖音主页链接，一键抓取 TA 的全部公开作品数据，以及当前粉丝数 / 总获赞数，并导出 Excel 或独立网页。</p>
  <div class='box' style='margin-bottom:18px'>
    <input class='field' id='url' placeholder='https://www.douyin.com/user/MS4wLjAB...  或  https://v.douyin.com/xxxxx'>
    <div style='margin-top:12px'><button class='btn btn-primary' id='btnFetch' type='button'>抓取并解析</button></div>
  </div>
  <div id='result'></div>
  <div class='hr-title' style='margin-top:30px'>历史抓取</div>
  <ul class='hist' id='hist'><li class='muted'>加载中…</li></ul>
  <div class='foot'>© kylinwu · 张真源抖音数据监测 · 仅本地化运行</div>
</div>
<script>
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function human(n){n=Number(n)||0;if(n>=1e8)return (n/1e8).toFixed(2)+'亿';if(n>=1e4)return (n/1e4).toFixed(1)+'万';return n.toLocaleString();}
function busy(btn,on){btn.disabled=on;if(on){btn.dataset.t=btn.innerHTML;btn.innerHTML='<span class="spinner"></span>抓取中…';}else{btn.innerHTML=btn.dataset.t;}}

async function fetchUser(){
  const url=document.getElementById('url').value.trim();
  if(!url) return alert('请粘贴抖音主页链接');
  const btn=document.getElementById('btnFetch'); busy(btn,true);
  try{
    const r=await fetch('/api/fetch-user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
    const j=await r.json();
    const el=document.getElementById('result');
    if(!j.ok){ el.innerHTML=`<div class='box err'><b>抓取失败</b><br>${esc(j.error||'')}</div>`; return; }
    const av=j.avatar_url?`<img class='av' src='${esc(j.avatar_url)}' alt=''>`:`<div class='av-ph'>${(j.nickname||'?').slice(0,1)}</div>`;
    const xl=`/api/export-xlsx?sec_uid=${encodeURIComponent(j.sec_uid)}&name=${encodeURIComponent(j.nickname||'抖音账号')}`;
    const html=`/api/export-html?sec_uid=${encodeURIComponent(j.sec_uid)}&name=${encodeURIComponent(j.nickname||'抖音账号')}`;
    const warns=[j.profile_err,j.post_err].filter(Boolean);
    el.innerHTML=`<div class='box'><div class='result-card'>${av}
      <div><div style='font-size:18px;font-weight:700;color:var(--gd)'>${esc(j.nickname||'未知账号')}</div>
      <a class='dl' href='${esc(j.profile_url)}' target='_blank'>在抖音打开主页</a></div></div>
      <div class='stats'>
        <div>粉丝数<b>${human(j.follower_count)}</b></div>
        <div>总获赞<b>${human(j.total_favorited)}</b></div>
        <div>已抓取作品<b>${human(j.post_count)}</b></div>
        <div>主页作品数<b>${human(j.aweme_count)}</b></div>
      </div>
      <div style='margin-top:14px'>
        <a class='btn btn-primary' href='${xl}'>下载 Excel</a>
        <a class='btn btn-ghost' href='${html}' target='_blank'>导出独立网页</a>
      </div>
      ${warns.length?`<div class='warn'>提示：${esc(warns.join('；'))}</div>`:''}
    </div>`;
    loadUsers();
  }catch(e){ document.getElementById('result').innerHTML=`<div class='box err'>${esc(e)}</div>`; }
  finally{ busy(btn,false); }
}

async function loadUsers(){
  const ul=document.getElementById('hist');
  try{
    const r=await fetch('/api/users'); const j=await r.json();
    if(!j.ok||!j.users.length){ ul.innerHTML='<li class="muted">暂无历史抓取记录</li>'; return; }
    ul.innerHTML=j.users.map(u=>{
      const xl=`/api/export-xlsx?sec_uid=${encodeURIComponent(u.sec_uid)}&name=${encodeURIComponent(u.nickname||'抖音账号')}`;
      const html=`/api/export-html?sec_uid=${encodeURIComponent(u.sec_uid)}&name=${encodeURIComponent(u.nickname||'抖音账号')}`;
      return `<li><div><div class='u-name'>${esc(u.nickname||u.sec_uid.slice(0,12))}</div>
        <div class='u-meta'>粉丝 ${human(u.follower_count)} · 作品 ${human(u.post_count)} · ${esc((u.fetched_at||'').slice(0,16))}</div></div>
        <div class='u-acts'><a href='${xl}'>Excel</a><a href='${html}' target='_blank'>网页</a></div></li>`;
    }).join('');
  }catch(e){ ul.innerHTML='<li class="muted">加载失败</li>'; }
}

document.getElementById('btnFetch').onclick=fetchUser;
loadUsers();
</script>
</body></html>"""
    return tpl.replace("{CSS}", PAGE_CSS + FETCH_CSS)


def _render_admin_login_html(error: str = "") -> str:
    err = (f"<div class='box err'>{html.escape(error)}</div>" if error else "")
    tpl = r"""<!DOCTYPE html>
<html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>后台登录 · 张真源监测</title>
<style>{CSS}</style></head>
<body>
<nav class='nav'><div class='nav-in'>
  <a class='brand' href='/dashboard.html'><span class='logo'>张</span><span>张真源监测</span></a>
  <div class='nav-links'>
    <a href='/dashboard.html'>看板</a>
    <a href='/fetch.html'>抓取账号</a>
    <a href='/admin' class='active'>后台管理</a>
  </div>
</div></nav>
<div class='wrap'>
  <div class='auth'><div class='auth-card'>
    <div class='hr-title'>后台管理 · 登录</div>
    {err}
    <form method='POST' action='/admin/login'>
      <input class='field' type='text' name='user' placeholder='用户名' required autofocus style='margin-bottom:12px'>
      <input class='field' type='password' name='pw' placeholder='密码' required>
      <button class='btn btn-primary' type='submit' style='width:100%;margin-top:16px'>登 录</button>
    </form>
    <p class='muted' style='margin-top:16px;text-align:center'>用户名 / 密码写在项目根目录 <span class='code'>.env</span> 的 <span class='code'>ADMIN_USER</span> / <span class='code'>ADMIN_PASS</span></p>
  </div></div>
</div>
</body></html>"""
    return tpl.replace("{CSS}", PAGE_CSS + ADMIN_CSS).replace("{err}", err)


def _render_admin_home_html(user: str) -> str:
    tpl = r"""<!DOCTYPE html>
<html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>后台管理 · 张真源监测</title>
<style>{CSS}</style></head>
<body>
<nav class='nav'><div class='nav-in'>
  <a class='brand' href='/dashboard.html'><span class='logo'>张</span><span>张真源监测</span></a>
  <div class='nav-links'>
    <a href='/dashboard.html'>看板</a>
    <a href='/fetch.html'>抓取账号</a>
    <a href='/admin' class='active'>后台管理</a>
  </div>
</div></nav>
<div class='wrap'>
  <div class='section-h'>
    <div>
      <h2>后台管理</h2>
      <div class='section-sub'>登录身份：{user}</div>
    </div>
    <a class='btn btn-ghost' href='/admin/logout'>退出登录</a>
  </div>

  <div class='add-box'>
    <input class='field' id='newUrl' placeholder='粘贴抖音视频分享链接 / 主页 / 短链'>
    <button class='btn btn-primary' id='btnAdd' type='button'>添加并抓取</button>
  </div>
  <p class='muted' style='margin:2px 0 6px'>支持分享短链、iesdouyin 分享页、<code class='code'>/user/</code> 主页、<code class='code'>/video/</code> 直链</p>

  <div id='result'></div>

  <div class='section-h'>
    <div>
      <h2>已添加作品</h2>
      <div class='section-sub'>按发布时间倒序</div>
    </div>
  </div>
  <div class='card' style='padding:6px 10px'>
    <div class='tbl-scroll'>
      <table class='tbl' id='tb'><thead><tr>
        <th style='width:18%'>发布时间</th>
        <th style='width:38%'>标题</th>
        <th style='width:8%'>点赞</th>
        <th style='width:8%'>评论</th>
        <th style='width:8%'>收藏</th>
        <th>链接</th>
      </tr></thead><tbody id='tbBody'>
        <tr><td colspan='6' class='empty'>加载中…</td></tr>
      </tbody></table>
    </div>
  </div>

  <div class='foot'>© kylinwu · 张真源抖音数据监测 · 仅本地化运行</div>
</div>
<script>
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function human(n){n=Number(n)||0;if(n>=1e8)return (n/1e8).toFixed(2)+'亿';if(n>=1e4)return (n/1e4).toFixed(1)+'万';return n.toLocaleString();}
function timeFmt(t){
  if(!t) return '';
  try { const d=new Date(Number(t)*1000); const p=n=>String(n).padStart(2,'0');
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch(e){ return ''; }
}
function busy(btn,on){btn.disabled=on;if(on){btn.dataset.t=btn.innerHTML;btn.innerHTML='<span class="spinner"></span>处理中…';}else{btn.innerHTML=btn.dataset.t;}}

async function loadTable(){
  try {
    const r=await fetch('/api/admin/posts'); const j=await r.json();
    const tb=document.getElementById('tbBody');
    if(!j.ok){ tb.innerHTML=`<tr><td colspan='6' class='err'>${esc(j.error)}</td></tr>`; return; }
    if(!j.posts.length){ tb.innerHTML=`<tr><td colspan='6' class='empty'>还没有添加任何作品。先在输入框粘贴一个抖音链接试试</td></tr>`; return; }
    tb.innerHTML=j.posts.map(p=>{
      const link=p.share_url||(p.aweme_id?`https://www.douyin.com/video/${p.aweme_id}`:'');
      return `<tr>
        <td>${esc(timeFmt(p.create_time))}</td>
        <td>${esc((p.desc||'').slice(0,80))}${p.desc&&p.desc.length>80?'…':''}</td>
        <td>${human(p.digg_count)}</td>
        <td>${human(p.comment_count)}</td>
        <td>${human(p.collect_count)}</td>
        <td>${link?`<a href='${esc(link)}' target='_blank'>打开抖音</a>`:`<span class='muted'>${esc(p.aweme_id||'')}</span>`}</td>
      </tr>`;
    }).join('');
  } catch(e) {
    document.getElementById('tbBody').innerHTML=`<tr><td colspan='6' class='err'>${esc(e)}</td></tr>`;
  }
}

async function addLink(){
  const url=document.getElementById('newUrl').value.trim();
  if(!url) return alert('请粘贴抖音链接');
  const btn=document.getElementById('btnAdd'); busy(btn,true);
  document.getElementById('result').innerHTML='';
  try {
    const r=await fetch('/api/admin/add-link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
    const j=await r.json();
    if(!j.ok){
      document.getElementById('result').innerHTML=`<div class='box err'><b>抓取失败</b><br>${esc(j.error)}</div>`;
      return;
    }
    document.getElementById('result').innerHTML=`<div class='box'>
      <b style='color:var(--gd)'>已添加并抓取</b><br>
      标题：${esc(j.title||'(无标题)')}<br>
      链接：<a href='${esc(j.share_url)}' target='_blank'>在抖音打开</a>
    </div>`;
    document.getElementById('newUrl').value='';
    loadTable();
  } catch(e) {
    document.getElementById('result').innerHTML=`<div class='box err'>${esc(e)}</div>`;
  } finally { busy(btn,false); }
}

document.getElementById('btnAdd').onclick=addLink;
document.getElementById('newUrl').addEventListener('keydown', e=>{ if(e.key==='Enter') addLink(); });
loadTable();
</script>
</body></html>"""
    return tpl.replace("{CSS}", PAGE_CSS + ADMIN_CSS).replace("{user}", html.escape(user))


def _ensure_html_files():
    """首次访问时把页面写到磁盘，方便浏览器直开。"""
    if not FETCH_HTML.exists():
        FETCH_HTML.write_text(_render_fetch_html(), encoding="utf-8")
    if not ADMIN_LOGIN_HTML.exists():
        ADMIN_LOGIN_HTML.write_text(_render_admin_login_html(), encoding="utf-8")
    if not ADMIN_HOME_HTML.exists():
        ADMIN_HOME_HTML.write_text(_render_admin_home_html(ADMIN_USER), encoding="utf-8")


# ============================================================
# 独立网页导出（一个完全自包含的 HTML，可下载到任意地方打开）
# ============================================================
def _build_standalone_html(sec_uid: str | None, nickname: str | None) -> str:
    """生成一份自包含 HTML（dashboard 数据的快照，无后端依赖）。

    保留完整 <head>（全部样式与自适应脚本），仅注入顶部 banner 并把
    「刷新」降级为原地重新加载（离线快照没有后端可跳）。
    """
    import dashboard as _d
    import re as _re
    # render() 会把 html 写到磁盘；直接读回来（已是完整 HTML 字符串）
    _d.render()
    inner = DASHBOARD_PATH.read_text(encoding="utf-8")
    banner = (
        "<div class='export-banner' style=\"position:sticky;top:0;"
        "background:#15803d;color:#fff;padding:10px 16px;font-size:13px;"
        "text-align:center;z-index:9999;box-shadow:0 2px 6px rgba(0,0,0,.1);"
        "font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif\">"
        "这是「" + (nickname or "抖音账号") + "」的本地数据快照，"
        "所有图表、链接均已内嵌 — 可离线打开、双击转发</div>"
    )
    # 在 <body ...> 之后注入 banner
    out = _re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + banner,
                  inner, count=1, flags=_re.IGNORECASE)
    # 离线快照没有后端：刷新改为原地重载；/downloads.html 为历史兼容链接直接置空
    out = (out
           .replace("<a href='/dashboard.html'>刷新</a>",
                    "<a href='javascript:location.reload()'>刷新</a>")
           .replace("href='/downloads.html'", "href='#'"))
    return out


def _send_html_download(handler, sec_uid: str | None, nickname: str | None):
    data = _build_standalone_html(sec_uid, nickname).encode("utf-8")
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    nick = nickname or "抖音账号"
    safe_nick = re.sub(r"[^\w一-龥\-_]", "_", nick)[:30] or "douyin"
    fname = f"{safe_nick}_快照_{ts}.html"
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Disposition",
                        f"attachment; filename*=UTF-8''{quote(fname)}")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


# ============================================================
# HTTP Handler
# ============================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("[%s] %s", self.address_string(), fmt % args)

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        try:
            # 兼容旧链接（用户已习惯）
            if u.path == "/downloads.html":
                self._redirect("/fetch.html")
                return

            if u.path in ("/", "/index.html"):
                self._redirect("/dashboard.html")
                return

            if u.path == "/dashboard.html":
                self._serve_file(DASHBOARD_PATH)
                return

            if u.path == "/fetch.html":
                self._ensure_html()
                self._serve_file(FETCH_HTML)
                return

            # ---- 后台 ----
            if u.path == "/admin/login":
                # 已登录直接进首页
                if _current_user(self.headers):
                    self._redirect("/admin")
                else:
                    self._ensure_html()
                    self._serve_file(ADMIN_LOGIN_HTML)
                return

            if u.path == "/admin/logout":
                self.send_response(302)
                self.send_header("Set-Cookie",
                                 f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly")
                self.send_header("Location", "/admin/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if u.path in ("/admin", "/admin/"):
                if not _current_user(self.headers):
                    self._redirect("/admin/login")
                else:
                    self._ensure_html()
                    self._serve_file(ADMIN_HOME_HTML)
                return

            if u.path == "/api/users":
                try:
                    self._json({"ok": True, "users": get_users()})
                except Exception as e:
                    self._json({"ok": False, "error": f"读取失败: {e}"})
                return

            if u.path == "/api/admin/posts":
                if not _current_user(self.headers):
                    self._json({"ok": False, "error": "未登录"}, status=401)
                    return
                self._admin_posts()
                return

            if u.path == "/api/export-xlsx":
                qs = parse_qs(u.query)
                sec = qs.get("sec_uid", [None])[0]
                name = qs.get("name", [None])[0]
                self._send_xlsx(sec, name)
                return

            if u.path == "/api/export-html":
                qs = parse_qs(u.query)
                sec = qs.get("sec_uid", [None])[0]
                name = qs.get("name", [None])[0]
                _send_html_download(self, sec, name)
                return

            self.send_error(404, "Not Found")
        except Exception as e:
            log.exception("GET %s 异常", self.path)
            self._json({"ok": False, "error": f"服务端异常: {e}"}, status=500)

    # ---- POST ----
    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""

        try:
            # 表单登录：先处理（不走 JSON）
            if u.path == "/admin/login":
                self._admin_login_post(raw)
                return

            # JSON API：解析失败就报错
            try:
                body = json.loads(raw or "{}")
            except Exception as e:
                return self._json({"ok": False, "error": f"请求体解析失败: {e}"})

            # 抓取任意账号
            if u.path == "/api/fetch-user":
                url = (body.get("url") or "").strip()
                self._api_fetch_user(url)
                return

            # 管理员添加单条作品
            if u.path == "/api/admin/add-link":
                if not _current_user(self.headers):
                    self._json({"ok": False, "error": "未登录"}, status=401)
                    return
                url = (body.get("url") or "").strip()
                self._api_admin_add_link(url)
                return

            self._json({"ok": False, "error": f"未知端点: {u.path}"})
        except Exception as e:
            log.exception("POST %s 异常", self.path)
            self._json({"ok": False, "error": f"服务端异常: {e}"})

    # ========================================================
    # 鉴权 / 业务子方法
    # ========================================================
    def _admin_login_post(self, raw: str = ""):
        """登录页表单提交（application/x-www-form-urlencoded）。"""
        try:
            form = parse_qs(raw or "")
        except Exception:
            form = {}
        user = (form.get("user", [""])[0] or "").strip()
        pw = (form.get("pw", [""])[0] or "")
        if (user == ADMIN_USER and pw == ADMIN_PASS):
            token = _make_token(user)
            # 302 + Set-Cookie（必须先 send_response 再写两个 header）
            self.send_response(302)
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={token}; Path=/; Max-Age={7*24*3600}; HttpOnly")
            self.send_header("Location", "/admin")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._serve_text(_render_admin_login_html("用户名或密码错误").encode("utf-8"),
                             status=401)

    def _admin_posts(self):
        """列出全部已添加作品（按发布时间倒序），含最新互动数。"""
        conn = sqlite3.connect(str(DB_PATH))
        # 左连接 post_stats_hourly 取最新一条
        rows = conn.execute(
            """
            SELECT p.aweme_id, p.desc, p.create_time, p.share_url,
                   IFNULL(s.digg_count, 0), IFNULL(s.comment_count, 0),
                   IFNULL(s.collect_count, 0), IFNULL(s.share_count, 0),
                   IFNULL(s.play_count, 0), p.sec_uid
              FROM post p
              LEFT JOIN (
                SELECT aweme_id, MAX(id) AS max_id
                  FROM post_stats_hourly GROUP BY aweme_id
              ) m ON m.aweme_id = p.aweme_id
              LEFT JOIN post_stats_hourly s ON s.id = m.max_id
              WHERE COALESCE(p.sec_uid, '') <> 'manual_skip'
              ORDER BY COALESCE(p.create_time, 0) DESC, p.last_seen DESC
            """
        ).fetchall()
        conn.close()
        posts = [
            {
                "aweme_id": r[0], "desc": r[1] or "", "create_time": r[2] or 0,
                "share_url": r[3] or "",
                "digg_count": r[4], "comment_count": r[5],
                "collect_count": r[6], "share_count": r[7], "play_count": r[8],
                "sec_uid": r[9] or "",
            } for r in rows
        ]
        self._json({"ok": True, "posts": posts})

    def _api_fetch_user(self, url: str):
        if not DOUYIN_COOKIE:
            self._json({"ok": False, "error":
                "未配置 DOUYIN_COOKIE，无法抓取。请在项目 .env 中填入抖音登录 Cookie 后重启服务。"})
            return
        if not url:
            self._json({"ok": False, "error": "请粘贴抖音主页链接"})
            return
        from dyurl import resolve_sec_uid
        from collector import collect_user
        try:
            sec = resolve_sec_uid(url)
            res = collect_user(sec)
            res["ok"] = True
            self._json(res)
        except Exception as e:
            log.warning("抓取账号失败: %s", e)
            self._json({"ok": False, "error": f"抓取失败: {e}"})

    def _api_admin_add_link(self, url: str):
        """管理员手动添加：粘贴视频短链/主页/直链 → 用 collect_user 抓取 → 保留到 post 表。"""
        if not DOUYIN_COOKIE:
            self._json({"ok": False, "error":
                "未配置 DOUYIN_COOKIE，无法抓取。请先在 .env 中填入抖音登录 Cookie 后重启服务。"})
            return
        if not url:
            self._json({"ok": False, "error": "请粘贴抖音链接（视频 / 主页 / 短链均可）"})
            return

        from dyurl import resolve_sec_uid, resolve_aweme_id
        from collector import collect_user, collect_single_aweme

        try:
            aweme_id = None
            try:
                aweme_id = resolve_aweme_id(url)
            except Exception:
                aweme_id = None

            if aweme_id:
                # 单视频：直接抓这一条
                res = collect_single_aweme(aweme_id)
                self._json({"ok": True, "title": res.get("title", ""),
                            "share_url": res.get("share_url", ""),
                            "aweme_id": aweme_id,
                            "type": "video"})
            else:
                # 主页：抓全部
                sec = resolve_sec_uid(url)
                res = collect_user(sec)
                self._json({"ok": True, "title": res.get("nickname", ""),
                            "share_url": res.get("profile_url", ""),
                            "sec_uid": sec,
                            "type": "user",
                            "post_count": res.get("post_count", 0)})
        except Exception as e:
            log.warning("管理员添加失败: %s", e)
            self._json({"ok": False, "error": f"抓取失败: {e}"})

    # ========================================================
    # 通用响应工具
    # ========================================================
    def _send_xlsx(self, sec_uid, nickname):
        try:
            data = build_workbook_bytes(sec_uid=sec_uid, nickname=nickname)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            if sec_uid:
                un = get_user(sec_uid) or {}
                nick = nickname or un.get("nickname") or "抖音账号"
            else:
                nick = "张真源"
            import re as _re
            safe = _re.sub(r"[^\w一-龥\-_]", "_", nick)[:30] or "douyin"
            fname = f"{safe}_作品数据_{ts}.xlsx"
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{quote(fname)}")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._json({"ok": False, "error": f"导出失败: {e}"})

    def _ensure_html(self):
        _ensure_html_files()

    def _redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _set_cookie(self, name, value, max_age=None):
        if max_age == 0:
            cookie = f"{name}=; Path=/; Max-Age=0; HttpOnly"
        else:
            cookie = f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly"
        self.send_header("Set-Cookie", cookie)

    def _send_status(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_file(self, path):
        if not path.exists():
            self.send_error(404, f"文件不存在: {path}")
            return
        data = path.read_bytes()
        self.send_response(200)
        ctype = ("text/html; charset=utf-8" if path.suffix == ".html"
                 else "text/plain; charset=utf-8")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_text(self, body: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=SERVER_PORT)
    args = ap.parse_args()
    port = args.port
    _ensure_html_files()
    # 启动后渲染一次 dashboard.html，让磁盘与最新代码一致（避免 handler 缓存旧版）
    try:
        import dashboard as _d
        _d.render()
    except Exception as e:
        log.warning("启动时 render() 失败：%s", e)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log.info("本地 web 服务已启动 http://localhost:%d", port)
    log.info("  · 张真源看板：http://localhost:%d/dashboard.html", port)
    log.info("  · 抓取任意账号：http://localhost:%d/fetch.html", port)
    log.info("  · 后台管理（默认账号 %s / %s）：http://localhost:%d/admin",
             ADMIN_USER, ADMIN_PASS, port)
    log.info("  · 提示：在 .env 设置 ADMIN_USER / ADMIN_PASS 即可修改后台账号")
    if not DOUYIN_COOKIE:
        log.warning("DOUYIN_COOKIE 未配置 — 抓取和后台添加功能暂时无法使用。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()

