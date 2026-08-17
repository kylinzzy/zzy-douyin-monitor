"""采集编排：优先抖音 web 端（Cookie 免费真实），MaxHub 作为付费兜底。

⚠️ 永不编造：任何情况下拿不到真实数据就明确报错 / 空状态，绝不填充假数字。
数据源优先级：
  1) DOUYIN_COOKIE 配置 → 直接拉 douyin.com/user/{sec_uid} 的 RENDER_DATA（真实、免费、零积分）
  2) 仅 MAXHUB_API_KEY 配置 → 走 MaxHub 聚合 API（付费、按调用计费）
  3) 都未配置 → awaiting-config（dashboard/report 显示明确空状态）
"""
import re
import json
import time
import urllib.parse
from datetime import datetime, timezone, timedelta

import requests
from common import (log, now_iso, UA, DOUYIN_COOKIE, DOUYIN_SEC_UID,
                    DOUYIN_SHARE_URL, DOUYIN_SHORT_ID, TARGET_NAME,
                    TRACK_RECENT_DAYS, MAX_POST_DETAIL, MAXHUB_API_KEY,
                    dig, get_meta, set_meta)
from storage import (insert_profile, upsert_post, insert_post_stats,
                     insert_board, save_user)
from maxhub import MaxHubClient


def to_int(v):
    try:
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            return int(float(v.replace(",", "").strip()))
    except (TypeError, ValueError):
        pass
    return 0


# ---------------- 抖音 web 端（Cookie 免费真实） ----------------
# 抖音 web 主页是纯客户端渲染，真实资料/作品走独立 API（当前无需 X-Bogus 签名）。
#   资料： /aweme/v1/web/user/profile/other/
#   作品： /aweme/v1/web/aweme/post/  （翻页 max_cursor）

def _req_json(url, params):
    headers = {
        "User-Agent": UA,
        "Referer": f"https://www.douyin.com/user/{DOUYIN_SEC_UID or ''}",
        "Cookie": DOUYIN_COOKIE,
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    r = requests.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        raise RuntimeError("抖音返回非 JSON（可能风控/验证码页），Cookie 可能失效")


def _profile_params(extra=None):
    p = {"device_platform": "webapp", "aid": "6383",
         "channel": "channel_pc_web", "language": "zh-CN"}
    if extra:
        p.update(extra)
    return p


def _fetch_aweme_html(aweme_id: str) -> dict:
    """拉单条视频的详情页 HTML，从 RENDER_DATA 解析 aweme 字典。
    不依赖 X-Bogus 签名（抖音 web 视频详情页是 SSR）。
    """
    url = f"https://www.douyin.com/video/{aweme_id}"
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.douyin.com/",
        "Cookie": DOUYIN_COOKIE,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    text = r.text or ""
    # RENDER_DATA 通常是 <script id="RENDER_DATA">...urlencoded json...</script>
    m = re.search(
        r'id=["\']RENDER_DATA["\'][^>]*>([^<]+)</script>', text)
    if not m:
        # 兜底：找 window._ROUTER_DATA = {...} 或其他内嵌 json
        m = re.search(r'window\._ROUTER_DATA\s*=\s*(\{.+?\})\s*[;<]', text)
    if not m:
        raise RuntimeError(
            "未能从视频详情页提取到 RENDER_DATA（可能链接已失效/私密作品/需要登录）")
    import urllib.parse as _u
    raw = _u.unquote(m.group(1))
    try:
        data = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"RENDER_DATA 解析失败: {e}")
    # 在 data 里找 aweme dict
    aweme = dig(data, "aweme.detail", "aweme.aweme_detail",
                "data.aweme_detail", default={}) or {}
    if not aweme:
        # 深度兜底
        for k, v in data.items():
            if isinstance(v, dict) and "aweme_id" in v and "statistics" in v:
                aweme = v
                break
    if not aweme:
        raise RuntimeError("RENDER_DATA 中找不到视频详情")
    return aweme


def fetch_profile_api(sec_uid, persist_meta=True):
    """拉用户资料（粉丝/获赞/作品数/抖音号）。

    persist_meta=True 时把头像/昵称写入全局 meta（张真源监测看板用）；
    一次性抓取其他账号时传 False，避免覆盖张真源的头像。
    """
    url = "https://www.douyin.com/aweme/v1/web/user/profile/other/"
    params = _profile_params({"sec_user_id": sec_uid,
                              "publish_video_strategy_type": "1",
                              "personal_center_strategy": "1", "up_time": "0"})
    j = _req_json(url, params)
    raise_for_dy_error(j, "profile/other")
    u = j.get("user") or {}
    if not u.get("nickname") and not u.get("follower_count"):
        raise RuntimeError("profile/other 未返回用户资料（Cookie 可能失效）")
    # 头像：从 avatar_larger / avatar_300x300 / avatar_168x168 依次取
    avatar_url = ""
    for ak in ("avatar_larger", "avatar_300x300", "avatar_168x168",
               "avatar_medium", "avatar_thumb"):
        av = dig(u, f"{ak}.url_list.0",
                 f"{ak}.urlList.0", f"{ak}.url", default="")
        if av:
            avatar_url = str(av)
            break
    # 持久化头像（dashboard 头部使用）；空值不写以保留旧值
    if avatar_url and persist_meta:
        set_meta("avatar_url", avatar_url)
    # 个人主页直链：抖音 web 端
    short_id = str(dig(u, "short_id", "shortId", default="") or "")
    profile_url = (
        f"https://www.douyin.com/user/{dig(u, 'sec_uid', default=sec_uid)}"
    )
    return {
        "nickname": dig(u, "nickname", default=""),
        "sec_uid": dig(u, "sec_uid", default="") or sec_uid,
        "uid": dig(u, "uid", default=""),
        "unique_id": dig(u, "unique_id", "uniqueId", default=""),
        "short_id": short_id,
        "follower_count": to_int(dig(u, "follower_count", "followerCount", default=0)),
        "total_favorited": to_int(dig(u, "total_favorited", "totalFavorited", default=0)),
        "aweme_count": to_int(dig(u, "aweme_count", "awemeCount", default=0)),
        "favoriting_count": to_int(dig(u, "favoriting_count", "favoritingCount", default=0)),
        "avatar_url": avatar_url,
        "profile_url": profile_url,
    }


def fetch_posts_api(sec_uid, max_pages=60):
    """翻页拉全部作品（抖音 web 公开视频作品，含每条互动统计）。
    注：抖音 web 的 /aweme/post/ 接口 current_tab=image 与 post 返回重复，
    故只抓 post tab 并去重（接口 aweme_count 即公开作品总数）。"""
    url = "https://www.douyin.com/aweme/v1/web/aweme/post/"
    out, seen, cursor, pages = [], set(), "0", 0
    while True:
        params = _profile_params({
            "sec_user_id": sec_uid, "max_cursor": cursor,
            "locate_query": "false", "show_live_replay_strategy": "1",
            "count": "20", "current_tab": "post", "from_user_page": "1",
        })
        j = _req_json(url, params)
        raise_for_dy_error(j, "aweme/post")
        for it in (j.get("aweme_list") or []):
            aid = str(it.get("aweme_id") or "")
            if aid and aid not in seen:
                seen.add(aid)
                out.append(it)
        pages += 1
        if not j.get("aweme_list") or not j.get("has_more") or pages >= max_pages:
            break
        cursor = str(j.get("max_cursor"))
        time.sleep(1.0)  # 降低请求频率，避免触发抖音风控
    return out


def raise_for_dy_error(j, label):
    code = j.get("status_code")
    if code not in (0, None):
        raise RuntimeError(f"{label} 返回 status_code={code}："
                           f"{j.get('status_msg') or '未知错误'}"
                           f"（Cookie 可能失效或被风控）")


def parse_posts_api(items, sec_uid):
    """从 API 返回的 aweme 列表解析为统一结构（兼容视频与图文）。"""
    out = []
    for it in items:
        st = dig(it, "statistics", default={}) or {}
        vid = dig(it, "video", default={}) or {}
        if vid:
            cover = dig(vid, "cover.url_list.0", "cover.urlList.0",
                        "cover.url", default="")
            play = dig(vid, "play_addr.url_list.0", "play_addr.urlList.0",
                       "play_addr.url", default="")
            dl = dig(vid, "download_addr.url_list.0", "download_addr.urlList.0",
                     "download_addr.url", default="")
            ptype = "video"
        else:  # 图文作品
            imgs = dig(it, "images", default=[]) or []
            cover = dig(imgs[0], "url_list.0", default="") if imgs else ""
            play, dl, ptype = "", "", "image"
        share = dig(it, "share_url", "shareUrl", default="")
        out.append({
            "aweme_id": str(dig(it, "aweme_id", default="") or ""),
            "desc": dig(it, "desc", default=""),
            "create_time": to_int(dig(it, "create_time", "createTime", default=0)),
            "ptype": ptype,
            "digg_count": to_int(dig(st, "digg_count", "diggCount", default=0)),
            "comment_count": to_int(dig(st, "comment_count", "commentCount", default=0)),
            "collect_count": to_int(dig(st, "collect_count", "collectCount", default=0)),
            "share_count": to_int(dig(st, "share_count", "shareCount", default=0)),
            "play_count": to_int(dig(st, "play_count", "playCount", default=0)),
            "cover_url": cover, "play_url": play,
            "download_url": dl, "share_url": share,
        })
    return out


def collect_via_web():
    set_meta("mode", "live")
    set_meta("source", "douyin-web")
    sec_uid = DOUYIN_SEC_UID
    if not sec_uid:
        raise RuntimeError("未配置 DOUYIN_SEC_UID（应为张真源真实 sec_uid）")
    set_meta("sec_uid", sec_uid)

    # 1) 粉丝/获赞/作品数：profile API 风控较轻，几乎不会被屏蔽；先跑它
    prof = None
    profile_err = None
    try:
        prof = fetch_profile_api(sec_uid)
        insert_profile(now_iso(), prof)
        # dashboard 头部需要：昵称 / sec_uid / 主页 URL / 头像（set_meta 已在 fetch_profile_api 内）
        set_meta("last_profile_nickname", prof.get("nickname") or "")
        set_meta("sec_uid", prof.get("sec_uid") or sec_uid)
        set_meta("profile_url", prof.get("profile_url") or
                 f"https://www.douyin.com/user/{prof.get('sec_uid') or sec_uid}")
    except Exception as e:
        profile_err = str(e)
        log.warning("profile 采集失败（将继续尝试作品）: %s", e)

    # 2) 作品列表：post API 风控严，若失败保留旧作品、只更新粉丝趋势
    ts = now_iso()
    post_count = 0
    post_err = None
    try:
        items = fetch_posts_api(sec_uid)
        posts = parse_posts_api(items, sec_uid)
        for p in posts:
            p["sec_uid"] = sec_uid
            p["first_seen"] = ts
            p["last_seen"] = ts
            upsert_post(p)
            insert_post_stats(ts, p["aweme_id"], p, sec_uid=sec_uid)
        post_count = len(posts)
    except Exception as e:
        post_err = str(e)
        log.warning("作品采集失败（保留旧数据）: %s", e)
        # 旧作品的最新 stats 用于时间戳，避免 sparkline 错位
        from storage import post_list as _post_list
        post_count = len(_post_list())

    # 3) 榜单：免费、带 Cookie；失败非致命
    hot_n = topic_n = 0
    try:
        hot, topic = fetch_boards_api()
        for rank, name, extra in hot:
            insert_board(ts, "hot_total", rank, name, extra)
        for rank, name, extra in topic:
            insert_board(ts, "topic", rank, name, extra)
            insert_board(ts, "challenge", rank, name, extra)
        hot_n, topic_n = len(hot), len(topic)
    except Exception as e:
        log.warning("榜单拉取失败（非致命）：%s", e)

    log.info("web 采集完成：作品 %d 个（接口 aweme_count=%s），粉丝 %s，热榜 %d，话题 %d",
             post_count, (prof or {}).get("aweme_count"),
             (prof or {}).get("follower_count"), hot_n, topic_n)
    return {
        "mode": "live", "source": "douyin-web", "ts": ts,
        "profile": prof, "post_count": post_count,
        "tracked_posts": post_count,
        "note": "娱乐榜/话题/挑战均来自抖音 web 公开接口（免费真实）。",
        "warnings": ([profile_err] if profile_err else []) +
                    ([post_err] if post_err else []),
    }


def fetch_boards_api():
    """拉取娱乐热榜（全站）与张真源相关话题/挑战。
    免费、带 Cookie，无需 X-Bogus 签名；失败非致命，不阻断主流程。"""
    # 1) 娱乐 / 热点总榜
    hot = []
    try:
        j = _req_json("https://www.douyin.com/aweme/v1/web/hot/search/list/",
                      _profile_params())
        for i, it in enumerate(j.get("data") or []):
            hot.append((i + 1, str(dig(it, "word", default="") or ""),
                        {"hot_value": to_int(dig(it, "hot_value", "hotValue", default=0))}))
    except Exception as e:
        log.warning("热榜拉取失败（非致命）：%s", e)
    # 2) 张真源相关话题 / 挑战
    topic = []
    try:
        j2 = _req_json("https://www.douyin.com/aweme/v1/web/challenge/search/",
                       _profile_params({"keyword": TARGET_NAME, "cursor": "0",
                                        "count": "20", "type": "1"}))
        for i, c in enumerate(j2.get("challenge_list") or []):
            info = dig(c, "challenge_info", default={}) or {}
            topic.append((i + 1, str(dig(info, "cha_name", default="") or ""),
                          {"view_count": to_int(dig(info, "view_count", default=0)),
                           "user_count": to_int(dig(info, "user_count", default=0)),
                           "video_count": to_int(dig(info, "video_count", default=0))}))
    except Exception as e:
        log.warning("话题拉取失败（非致命）：%s", e)
    return hot, topic


# ---------------- 一次性抓取任意账号（粘贴主页链接入口） ----------------

def collect_user(sec_uid, max_pages=60):
    """一次性抓取某账号：资料（粉丝/获赞/作品数）+ 全部公开作品。
    结果写入同一套存储（按 sec_uid 区分），便于按账号导出 Excel。
    返回可直接序列化给前端的结构。"""
    ts = now_iso()
    prof = None
    profile_err = None
    try:
        prof = fetch_profile_api(sec_uid, persist_meta=False)
        insert_profile(ts, prof)
    except Exception as e:
        profile_err = str(e)
        log.warning("抓取账号资料失败: %s", e)

    post_count = 0
    post_err = None
    try:
        items = fetch_posts_api(sec_uid, max_pages=max_pages)
        posts = parse_posts_api(items, sec_uid)
        for p in posts:
            p["sec_uid"] = sec_uid
            p["first_seen"] = ts
            p["last_seen"] = ts
            upsert_post(p)
            insert_post_stats(ts, p["aweme_id"], p, sec_uid=sec_uid)
        post_count = len(posts)
    except Exception as e:
        post_err = str(e)
        log.warning("抓取作品失败: %s", e)

    # 连资料都拿不到（Cookie 失效 / 风控 / 网络异常）→ 视为硬失败，
    # 让前端明确报错，而不是返回一个 0 作品的「假成功」。
    if prof is None and profile_err:
        raise RuntimeError(profile_err)

    summary = {
        "sec_uid": sec_uid,
        "nickname": (prof or {}).get("nickname", ""),
        "avatar_url": (prof or {}).get("avatar_url", ""),
        "profile_url": (prof or {}).get("profile_url")
                       or f"https://www.douyin.com/user/{sec_uid}",
        "unique_id": (prof or {}).get("unique_id", ""),
        "follower_count": (prof or {}).get("follower_count", 0),
        "total_favorited": (prof or {}).get("total_favorited", 0),
        "aweme_count": (prof or {}).get("aweme_count", 0),
        "post_count": post_count,
        "fetched_at": ts,
        "profile_err": profile_err,
        "post_err": post_err,
    }
    # 写账号索引（供下载页列出历史抓取）
    save_user(summary)
    log.info("一次性抓取完成：%s（昵称=%s）作品 %d 个，粉丝 %s",
             sec_uid[:12], summary["nickname"], post_count,
             summary["follower_count"])
    return summary


def collect_single_aweme(aweme_id: str) -> dict:
    """手动添加：抓取单条视频，落到 post / post_stats_hourly（含 sec_uid）。

    返回字典供 API 直接给前端（title / share_url / aweme_id）。
    拿不到就抛错，不编造。
    """
    if not aweme_id:
        raise ValueError("aweme_id 为空")
    if not DOUYIN_COOKIE:
        raise RuntimeError("未配置 DOUYIN_COOKIE，无法抓取视频详情")
    aweme = _fetch_aweme_html(aweme_id)
    sec_uid = dig(aweme, "author.sec_uid", "author.user_id", default="") or ""
    if not sec_uid:
        # 兜底：用 dev_id 留个标记，便于人工比对
        sec_uid = "manual_skip"
    parsed = parse_video_detail({"data": {"aweme_detail": aweme}})
    parsed["sec_uid"] = sec_uid
    ts = now_iso()
    parsed["first_seen"] = ts
    parsed["last_seen"] = ts
    upsert_post(parsed)
    insert_post_stats(ts, parsed["aweme_id"], parsed, sec_uid=sec_uid)
    log.info("手动添加单条：%s 标题=%s", aweme_id, parsed.get("desc", "")[:30])
    return {
        "title": parsed.get("desc", ""),
        "share_url": parsed.get("share_url", "")
                      or f"https://www.douyin.com/video/{aweme_id}",
        "aweme_id": aweme_id,
        "sec_uid": sec_uid,
    }


# ---------------- MaxHub 兜底（付费） ----------------

def parse_profile(data):
    d = dig(data, "data.user", "data", default={}) or {}
    if not isinstance(d, dict):
        d = dig(data, "user", default={}) or {}
    return {
        "nickname": dig(d, "nickname", default=""),
        "sec_uid": dig(d, "sec_uid", default=""),
        "uid": dig(d, "uid", default=""),
        "unique_id": dig(d, "unique_id", default=""),
        "follower_count": dig(d, "follower_count", default=0) or 0,
        "total_favorited": dig(d, "total_favorited", default=0) or 0,
        "aweme_count": dig(d, "aweme_count", default=0) or 0,
        "favoriting_count": dig(d, "favoriting_count", default=0) or 0,
    }


def _extract_video_urls(item):
    cover = dig(item, "video.cover.url_list.0", "video.origin_cover.url_list.0",
                "video.cover.url", default="")
    play = dig(item, "video.play_addr.url_list.0", "video.play_addr.url", default="")
    dl = dig(item, "video.download_addr.url_list.0", "video.download_addr.url", default="")
    share = dig(item, "share_url", default="")
    return cover, play, dl, share


def parse_posts(data):
    items = (dig(data, "data.aweme_list", "aweme_list", "data.list", "list")
             or [])
    if not isinstance(items, list):
        items = []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        aweme_id = str(dig(it, "aweme_id", default="") or "")
        if not aweme_id:
            continue
        cover, play, dl, share = _extract_video_urls(it)
        out.append({
            "aweme_id": aweme_id,
            "desc": dig(it, "desc", default=""),
            "create_time": dig(it, "create_time", default=0) or 0,
            "cover_url": cover, "play_url": play,
            "download_url": dl, "share_url": share,
        })
    return out


def parse_video_detail(data):
    aweme = dig(data, "data.aweme_detail", "data.aweme_info", "aweme_detail",
                "data", default={}) or {}
    if not isinstance(aweme, dict):
        aweme = {}
    st = dig(aweme, "statistics", default={}) or {}
    aweme_id = str(dig(aweme, "aweme_id", default="") or "")
    cover, play, dl, share = _extract_video_urls(aweme)
    return {
        "aweme_id": aweme_id,
        "desc": dig(aweme, "desc", default=""),
        "create_time": dig(aweme, "create_time", default=0) or 0,
        "digg_count": dig(st, "digg_count", default=0) or 0,
        "comment_count": dig(st, "comment_count", default=0) or 0,
        "collect_count": dig(st, "collect_count", default=0) or 0,
        "share_count": dig(st, "share_count", default=0) or 0,
        "play_count": dig(st, "play_count", default=0) or 0,
        "cover_url": cover, "play_url": play,
        "download_url": dl, "share_url": share,
    }


def parse_board(data):
    items = (dig(data, "data.list", "data.challenge_list", "list",
                 "challenge_list", "data.aweme_list", "aweme_list")
             or [])
    if not isinstance(items, list):
        items = []
    out = []
    name_keys = ["cha_name", "title", "word", "name", "challenge_info.cha_name",
                 "aweme_info.desc", "desc"]
    count_keys = ["view_count", "hot_value", "score", "user_count",
                  "video_count", "count", "play_count"]
    for i, it in enumerate(items[:50]):
        if not isinstance(it, dict):
            continue
        name = None
        for nk in name_keys:
            v = dig(it, nk)
            if v:
                name = str(v)
                break
        if not name:
            continue
        extra = {}
        for ck in count_keys:
            v = dig(it, ck, f"challenge_info.{ck}", f"stats.{ck}")
            if isinstance(v, (int, float)):
                extra[ck] = v
        rank = dig(it, "rank", "position", default=i + 1) or (i + 1)
        out.append((int(rank), name, extra))
    out.sort(key=lambda x: x[0])
    return out


def collect_via_maxhub():
    set_meta("mode", "live")
    set_meta("source", "maxhub")
    client = MaxHubClient()
    ts = now_iso()
    summary = {"mode": "live", "source": "maxhub", "ts": ts}

    base = client.profile_by_short_id(DOUYIN_SHORT_ID)
    if base.get("code") != 0:
        raise RuntimeError(f"profile_by_short_id 失败: {base.get('message')}")
    prof = parse_profile(base)
    sec_uid = prof.get("sec_uid") or DOUYIN_SEC_UID
    if not sec_uid:
        raise RuntimeError("未能获取 sec_uid")
    set_meta("sec_uid", sec_uid)

    detail = client.profile_detail(sec_uid)
    if detail.get("code") == 0:
        dprof = parse_profile(detail)
        for k in ("follower_count", "total_favorited", "aweme_count",
                  "favoriting_count", "nickname", "uid", "unique_id"):
            if dprof.get(k):
                prof[k] = dprof[k]
    insert_profile(ts, prof)
    summary["profile"] = prof

    pv = client.post_videos(sec_uid, count=MAX_POST_DETAIL)
    posts = parse_posts(pv) if pv.get("code") == 0 else []
    for p in posts:
        p["first_seen"] = ts
        p["last_seen"] = ts
        upsert_post(p)
    summary["post_count"] = len(posts)

    cutoff = datetime.now(timezone(timedelta(hours=8))).timestamp() - TRACK_RECENT_DAYS * 86400
    tracked = 0
    for p in posts:
        if p.get("create_time") and p["create_time"] < cutoff:
            continue
        if tracked >= MAX_POST_DETAIL:
            break
        vd = client.one_video(p["aweme_id"])
        if vd.get("code") == 0:
            det = parse_video_detail(vd)
            det["first_seen"] = p.get("first_seen", ts)
            det["last_seen"] = ts
            upsert_post(det)
            insert_post_stats(ts, det["aweme_id"], det)
            tracked += 1
    summary["tracked_posts"] = tracked

    ch = client.challenge_list()
    if ch.get("code") == 0:
        for rank, name, extra in parse_board(ch):
            insert_board(ts, "challenge", rank, name, extra)
    ht = client.hot_total_list()
    if ht.get("code") == 0:
        for rank, name, extra in parse_board(ht):
            insert_board(ts, "hot_total", rank, name, extra)
    tp = client.challenge_search(TARGET_NAME)
    if tp.get("code") == 0:
        for rank, name, extra in parse_board(tp):
            insert_board(ts, "topic", rank, name, extra)
    return summary


# ---------------- 主入口 ----------------

def collect():
    if DOUYIN_COOKIE:
        try:
            return collect_via_web()
        except Exception as e:
            log.error("抖音 web 采集失败: %s", e)
            set_meta("mode", "error")
            set_meta("error", str(e))
            return {"mode": "error", "error": str(e)}
    if MAXHUB_API_KEY:
        try:
            return collect_via_maxhub()
        except Exception as e:
            log.error("MaxHub 采集失败: %s", e)
            set_meta("mode", "error")
            set_meta("error", str(e))
            return {"mode": "error", "error": str(e)}
    set_meta("awaiting", "1")
    set_meta("mode", "awaiting-config")
    return {"mode": "awaiting-config", "ts": now_iso(),
            "reason": "未配置 DOUYIN_COOKIE / MAXHUB_API_KEY"}
