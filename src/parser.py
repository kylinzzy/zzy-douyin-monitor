"""抖音视频/图集无水印解析（封装 nologo-open-api）。

无需 MAXHUB_API_KEY —— 走的是独立去水印 API：
  https://nologo.code24.top/api/open/parse
请在 .env 中配置 NOLOGO_TOKEN（2 元起 100 次，单价 0.02 元）。
获取方式参考 nologo-open-api skill 文档。
"""
import re
from urllib.parse import quote
import requests

from common import log, NOLOGO_TOKEN, DOWNLOAD_DIR

API = "https://nologo.code24.top/api/open/parse"
TIMEOUT = 30

# 抖音分享链接中"提取 video_id"的简单正则（解析后的 video_id 仍以分享链接为入参）
SHARE_PATTERNS = [
    r"v\.douyin\.com/[A-Za-z0-9_-]+",
    r"www\.iesdouyin\.com/share/video/(\d+)",
    r"www\.douyin\.com/video/(\d+)",
]


def is_share_url(url: str) -> bool:
    """粗判：是否是抖音分享链接。"""
    return any(re.search(p, url or "") for p in SHARE_PATTERNS)


def parse(url: str) -> dict:
    """调用 nologo 解析。无 NOLOGO_TOKEN 时返回 dict 含 error。
    返回值统一为：
      {"ok": bool,
       "type": "video"|"img"|None,
       "url": 单视频直链（type==video）,
       "urls": 图集链接列表（type==img）,
       "title": "...", "desc": "...",
       "error": "..."}  （失败时）
    """
    if not NOLOGO_TOKEN:
        return {"ok": False,
                "error": "NOLOGO_TOKEN 未配置。请编辑 .env 填入后重启 server.py。\n"
                         "获取方式：搜索微信小程序「嗨去水印工具」→「我的」→「API管理」，"
                         "或加微信 linglan008 领取。",
                "need_token": True}
    if not url:
        return {"ok": False, "error": "URL 不能为空"}
    if not is_share_url(url):
        return {"ok": False, "error": f"URL 看起来不是抖音分享链接：{url[:80]}"}

    try:
        r = requests.post(
            API,
            headers={"Authorization": NOLOGO_TOKEN,
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"url": quote(url, safe="")},
            timeout=TIMEOUT,
        )
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": f"请求失败: {e}"}

    if j.get("code") != 200:
        msg = {
            400: "URL参数错误（400）",
            401: "缺少 Token（401）",
            403: "Token 无效/已禁用/次数耗尽（403）",
            404: "未找到资源（404）",
            500: "服务器错误（500）",
        }.get(j.get("code"), j.get("message", "未知错误"))
        return {"ok": False, "error": f"{msg} - {j}"}

    data = j.get("data") or {}
    typ = data.get("type")
    out = {
        "ok": True,
        "type": typ,
        "title": data.get("title", ""),
        "desc": data.get("desc", ""),
    }
    if typ == "video":
        out["url"] = data.get("url", "")
    elif typ == "img":
        out["urls"] = data.get("urls", []) or []
    out["usage"] = data.get("usage", {})
    return out


def download_video(parsed: dict, fallback_name: str = "video.mp4") -> str:
    """已 parse() 后，把视频文件落盘到 DOWNLOAD_DIR。返回本地路径。
    调用方负责保证 parsed 合法且 type=='video'。
    """
    url = parsed.get("url") or ""
    if not url:
        raise RuntimeError("parsed.url 为空")
    name = parsed.get("title") or fallback_name
    safe = re.sub(r"[^\w一-龥\-_]", "_", name)[:60].strip("_") or "video"
    target = DOWNLOAD_DIR / f"{safe}.mp4"
    log.info("开始下载: %s -> %s", url[:80], target.name)
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(target, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    return str(target)
