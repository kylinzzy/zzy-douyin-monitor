# 抖音账号小时级监测 · 张真源

> 本地部署的抖音账号数据监测站：粉丝/获赞/作品数按小时采集入 SQLite，
> 单作品 24h 内逐条互动（点赞/评论/收藏/分享/播放），挑战/娱乐/话题榜，
> 本地自包含 HTML 看板 + 每日报告，免费推送通道（QQ邮箱 + 腾讯文档），
> **以及独立的「作品下载器」（粘分享链接 → 解析 → 下载到本地）**。

- 主体：抖音号 **29832527783**（IP 上海 / 关注 16 / 粉丝 510.2万 / 获赞 1.1亿）
- 项目根：`/Users/kylinwu/Documents/腾讯ai/2026-08-16-05-00-08/douyin-monitor`
- 主视觉：绿色（#16a34a / #15803d / #dcfce7），主体标注「张真源」，署名 © kylinwu

---

## ⚠️ 关于「演示模式」

早期版本在缺少 `MAXHUB_API_KEY` 时生成了 382 个作品、虚假粉丝/获赞等**编造数据**，
造成严重误导。**新版本已彻底移除 demo 编造**：未配置 key 时 dashboard/report 显式
展示「等待配置」状态，所有指标显示 —，并列出获取 key 的步骤。

> 本项目不会在缺失真实数据源时向用户呈现任何「看起来像真的」伪造数据。

---

## 项目结构

```
douyin-monitor/
├── .env                    # 实际配置（不提交）
├── .env.example            # 配置模板
├── README.md
├── src/
│   ├── common.py           # 配置/路径/工具
│   ├── maxhub.py           # MaxHub API 客户端
│   ├── collector.py        # 采集编排（仅真实采集，不再有 demo 编造）
│   ├── storage.py          # SQLite 存储
│   ├── dashboard.py        # 生成本地看板（绿色主题，支持空状态）
│   ├── report.py           # 每日报告 / 小时摘要
│   ├── parser.py           # 抖音去水印解析（nologo）
│   ├── server.py           # 本地 web 服务（dashboard + downloads）
│   ├── push.py             # 本地快照 + QQ邮箱 + 腾讯文档队列
│   └── run.py              # 主入口（采集→看板→报告→推送）
└── data/
    ├── monitor.db          # SQLite
    ├── dashboard.html      # 自包含看板（可浏览器直接打开）
    ├── downloads.html      # 作品下载器（粘链接 → 下载）
    ├── downloads/          # 下载的视频文件落盘目录
    ├── reports/            # 每日报告 MD/HTML
    └── snapshots/          # latest.json + 腾讯文档推送队列
```

---

## 快速开始

### 1. 安装依赖

```bash
cd /Users/kylinwu/Documents/腾讯ai/2026-08-16-05-00-08/douyin-monitor
python3 -m venv .venv          # 已建则跳过
.venv/bin/pip install -q requests pyyaml
```

### 2. 配置 `.env`

**主路径（推荐，免费、真实）：抖音 web 端 + 你的浏览器 Cookie**
1. 复制模板：`cp .env.example .env`
2. 按 `COOKIE_GUIDE.md` 5 步获取整段 Cookie
3. 把那段长字符串粘到 `.env` 的 `DOUYIN_COOKIE=` 后面（**不要加引号、不要换行**）
4. `DATA_SOURCE=douyin_web`（默认就是这个）

**付费兜底（可选）：MaxHub Key**（国内打不开 aconfig.cn，仅在你确实能访问时用）
```bash
# 在 .env 中追加：
DATA_SOURCE=maxhub
MAXHUB_API_KEY=<你的 key>
```

**下载器（独立功能，不依赖 Cookie）：去水印 API**
- 微信搜「嗨去水印工具」小程序 → 我的 → API管理；或加微信 `linglan008`。
- 在 `.env` 中填 `NOLOGO_TOKEN=<token>`。

### 3. 单次采集（生成看板+报告）

```bash
.venv/bin/python src/run.py --once
# 输出：
#   data/dashboard.html
#   data/reports/YYYY-MM-DD.md / .html
#   data/snapshots/latest.json
#   data/snapshots/tencent_docs_queue.jsonl
```

### 4. 启动本地 web 服务（看板 + 下载器）

```bash
.venv/bin/python src/server.py --port 8765
# 浏览器打开：
#   http://localhost:8765/dashboard.html
#   http://localhost:8765/downloads.html
```

### 5. 进入小时级本地守护（可选）

```bash
.venv/bin/python src/run.py --loop   # 每小时一轮；或交给 WorkBuddy 小时级自动化（已配置）
```

---

## 单作品下载器（核心功能）

1. 启动服务：`.venv/bin/python src/server.py`
2. 浏览器打开 `http://localhost:8765/downloads.html`
3. 在抖音 App 找到张真源主页里任一作品 → 「分享 → 复制链接」
4. 把链接粘贴到下载器输入框 → 任选：
   - **🔍 仅解析**：显示无水印视频直链（新标签页打开可下载）
   - **📥 解析并下载到本地**：自动保存到 `data/downloads/{标题}.mp4`

**说明**：
- 下载器**不依赖 MAXHUB_API_KEY**——走的是独立去水印 API（nologo-open-api）。
- 需要在 `.env` 配 `NOLOGO_TOKEN`（首次 100 次免费体验，¥2 起）。
- 未配 token 时页面会显示明确引导。

---

## 数据看板（dashboard.html）

- 主视觉绿色（`#16a34a` / `#15803d` / `#dcfce7`），主体「张真源」，署名 © kylinwu。
- 卡片：粉丝 / 获赞 / 作品数 / 监测作品。
- 图表：粉丝·获赞小时趋势、各作品互动趋势。
- 表格：挑战榜 / 热点总榜（娱乐）/ 张真源话题 / 作品下载。
- **空状态**：未配 Cookie/key 时所有指标显示 —，并指引到 `COOKIE_GUIDE.md`。

## 每日报告（reports/YYYY-MM-DD.md & .html）

- 包含：核心指标、当日变化、Top 10 作品、各榜单。
- **空状态**：自动生成「待办步骤」章节，引导配 key。
- **下载方式章节**：列出本地下载器使用步骤。

---

## 免费推送（不消耗 MaxHub 积分）

| 通道 | 默认 | 配置 |
|---|---|---|
| 本地文件（dashboard.html / report.md / latest.json） | ✅ 始终 | 无 |
| QQ 邮箱 SMTP | ❌ 关闭 | `.env`: `QQ_SMTP_ENABLED=true` + `QQ_EMAIL` + `QQ_SMTP_PASS`(授权码) + `PUSH_TO_QQ` |
| 腾讯文档 | ⚙️ 由 WorkBuddy 自动化 | 已配置自动化 `automation-1786831765525` 每小时调用 `tencent-docs` 连接器写「张真源抖音监测」 |

**核心原则**：所有推送通道都不依赖 MaxHub、不消耗积分——Cookie 模式拉数据本地免费、QQ邮箱走 SMTP、腾讯文档走已连接连接器。

---

---

## 🔄 实时自动更新架构（每小时采集 → GitHub → 页面自动拉取）

整套链路已打通，**页面打开即拉取最新数据，无需重新部署**：

```
每小时（WorkBuddy 自动化 automation-1786831765525）
  └─ .venv/bin/python src/run.py --once
       1. collector.collect()        采集粉丝/获赞/作品/榜单
       2. dashboard.render()         生成 data/data.json + deploy/index.html（前端 JS 渲染页）
       3. publish.publish_to_github() 把 data.json + index.html 推到 GitHub 仓库根
       4. push.*                     本地快照 + QQ邮箱 + 腾讯文档（可关闭）
       5. （自动化额外步骤）把 deploy/ 重新部署到 CloudStudio
```

**页面如何「自动拉取最新数据」**：前端 `assets/dashboard.js` 的 `fetchLatest()` 在打开时异步拉取数据，回退链为：

1. 同源 `data.json`（GitHub Pages 站点即此文件，永远最新）
2. `https://cdn.jsdelivr.net/gh/kylinzzy/zzy-douyin-monitor@main/data.json`（国内可直连 CDN）
3. `https://raw.githubusercontent.com/kylinzzy/zzy-douyin-monitor/main/data.json`（即时新鲜、CORS 开放兜底）

→ 任意一层命中即渲染，因此 GitHub Pages / CloudStudio 两个在线版打开永远是最新数据。

**在线地址**

| 站点 | 链接 | 说明 |
|---|---|---|
| GitHub Pages | `https://kylinzzy.github.io/zzy-douyin-monitor/` | 仓库根 `index.html`；大陆常被墙，需代理 |
| CloudStudio | `https://d0bf842042214527baf3f8062fa671b7.app.workbuddy.link/` | 国内稳定可开，主在线地址 |
| GitHub 仓库 | `https://github.com/kylinzzy/zzy-douyin-monitor` | `data.json` + `index.html` 每小时自动更新 |

---

## 每小时触发器（两种任选其一，勿同时启用）

**方案 A · WorkBuddy 自动化（已 ACTIVE，推荐）**
- `automation-1786831765525`：每小时跑 `run.py --once` → 自动同步 GitHub → 重新部署 CloudStudio，并走免费推送通道。
- 无需任何额外操作，WorkBuddy 在后台按小时执行。

**方案 B · macOS launchd（原生、重启用仍生效，可选）**
- plist 已就绪：`~/Library/LaunchAgents/com.zzy.douyin-autopublish.plist`（每天 :05 分跑一次）。
- 由于当前会话的 shell 与 GUI 引导域隔离，`launchctl load` 会被系统拒绝（I/O error 5）。
  **请在自己的「终端」App 里执行一次**即可常驻：
  ```bash
  launchctl load ~/Library/LaunchAgents/com.zzy.douyin-autopublish.plist
  # 卸载：launchctl unload ~/Library/LaunchAgents/com.zzy.douyin-autopublish.plist
  ```
- ⚠️ 若启用方案 B，请先在 WorkBuddy「自动化」里暂停 `automation-1786831765525`，避免每小时跑两遍。

---

## 数据库表结构

- `meta(key,value)`：状态/缓存（如 `mode='awaiting-config'`）。
- `profile_hourly(id,ts,nickname,sec_uid,uid,unique_id,follower_count,total_favorited,aweme_count,favoriting_count)`。
- `post(aweme_id PK, desc, create_time, first_seen, last_seen, cover_url, share_url, play_url, download_url)`。
- `post_stats_hourly(id,ts,aweme_id,digg_count,comment_count,collect_count,share_count,play_count)`。
- `board_hourly(id,ts,board_type,rank,name,extra)` —— board_type ∈ {challenge, hot_total, topic}。

---

## 已知行为

- **无 `DOUYIN_COOKIE`**：dashboard/report 显示「待配置 Cookie」，**不展示任何数据**。按 `COOKIE_GUIDE.md` 获取。
- **无 `MAXHUB_API_KEY` 没事**——现在的免费路径是 Cookie 模式，MaxHub 仅作为付费兜底。
- **无 `NOLOGO_TOKEN`**：下载器显示「❌ 未配置」，引导用户加微信 `linglan008` 领取。
- **网络隔离**：`aconfig.cn` 在国内访问受限——但 Cookie 模式不依赖它；nologo API（`nologo.code24.top`）按需配置后第一次解析时验证。

---

## 部署到云端（Python 宿主：后台 / 抓取账号 / Excel 全功能在线）

> ⚠️ CloudStudio / GitHub Pages 只能托管**静态文件**，跑不了 `server.py` 后端。
> 因此「后台管理、抓取任意账号、后端版 Excel」必须部署到一个**支持 Python 的宿主**。
> 本项目已改造为可部署形态：`server.py` 监听 `0.0.0.0` + 读 `$PORT`、含 `/healthz` 健康检查、内嵌每小时采集线程（单进程即服务又自动更新）。

### 方式一 · Render（最省事，Git 自动构建，有免费档）
1. 注册 https://render.com（用 GitHub 登录）。
2. New → Web Service → 连接本仓库 `kylinzzy/zzy-douyin-monitor`。
3. 构建/启动：Build `pip install -r requirements.txt`，Start `python src/server.py`（runtime.txt 已指定 `python-3.12.0`）。
4. 环境变量（必填）：`DOUYIN_COOKIE`（抖音浏览器 Cookie，建议小号）、`ADMIN_PASS`（强密码）、`DATA_SOURCE=douyin_web`；可选 `ADMIN_USER` / `ADMIN_SESSION_SECRET`。
5. 部署完得到 `https://xxx.onrender.com`：看板 `/dashboard.html`、抓取 `/fetch.html`、后台 `/admin`。内嵌线程每小时自动采集刷新；要改外部调度可设 `DISABLE_SCHEDULER=1`。

### 方式二 · 自有 VPS（SSH）
```bash
git clone <本仓库> && cd zzy-douyin-monitor
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # 填入 DOUYIN_COOKIE / ADMIN_PASS
nohup .venv/bin/python src/server.py --port 8765 > server.log 2>&1 &
# 再用 nginx 反代 8765 到域名并配置 HTTPS
```

### 说明
- 云端上线后，「每小时采集」由后台线程承担；若同时开着本机 WorkBuddy 自动化，两者各自采集（写各自数据库、互不冲突），建议云端上线后暂停本机自动化避免重复。
- 免费通道（Cookie 模式 + QQ邮箱 + 腾讯文档）在云端同样零 MaxHub 积分。

---

© kylinwu · 张真源抖音数据监测 · 本地 / 云端均可运行
