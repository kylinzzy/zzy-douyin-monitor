"""把任意抖音主页链接解析为稳定的 sec_uid。

支持的输入形态：
  · https://www.douyin.com/user/{sec_uid}
  · https://www.douyin.com/user/self?sec_user_id={sec_uid}
  · https://www.iesdouyin.com/share/user/{uid}   （分享页，需解析出 sec_uid）
  · https://v.douyin.com/{code}/                    （短链，跟随跳转后解析）

输出：抖音账号唯一标识 sec_uid（字符串）。
绝不编造：拿不到就明确抛错。
"""
import re

import requests

from common import UA, log

# sec_uid 形如 MS4wLjABAAAA…（base64url，长度通常 ≥ 20）
_SEC_RE = re.compile(r"([A-Za-z0-9_\-]{20,})")


def _extract_sec_uid(url):
    """从已展开的完整链接中直接抽取 sec_uid（路径或查询参数）。"""
    if not url:
        return None
    # 1) 查询参数 ?sec_user_id=...
    m = re.search(r"[?&]sec_user_id=([A-Za-z0-9_\-]+)", url)
    if m:
        return m.group(1)
    # 2) 路径 /user/{sec_uid}
    m = re.search(r"/user/([A-Za-z0-9_\-]{20,})", url)
    if m:
        return m.group(1)
    return None


def resolve_sec_uid(raw_url):
    """解析主页链接 → sec_uid。"""
    if not raw_url or not raw_url.strip():
        raise ValueError("链接为空，请粘贴抖音主页链接")
    url = raw_url.strip()

    # 直接形态（无需联网）
    got = _extract_sec_uid(url)
    if got:
        return got

    # 短链 / 分享页：联网跟随跳转，再从落地页或 HTML 中解析
    is_short = ("v.douyin.com" in url or "iesdouyin.com" in url
                or "t.tiktok.com" in url or url.startswith("http") and "user" not in url)
    if not is_short and _extract_sec_uid(url) is None:
        # 既不是已识别的直接形态，也不是明显的短链 → 仍尝试联网兜底
        pass

    try:
        r = requests.get(url, headers={"User-Agent": UA,
                                       "Accept-Language": "zh-CN,zh;q=0.9"},
                         allow_redirects=True, timeout=20)
    except Exception as e:
        raise RuntimeError(f"无法访问该链接（网络/链接无效）：{e}")
    r.encoding = r.encoding or "utf-8"
    final = r.url or url
    log.info("主页链接已展开: %s -> %s", url[:60], final[:80])

    got = _extract_sec_uid(final)
    if got:
        return got

    # 从落地页 HTML 解析：canonical / og:url / RENDER_DATA 里的 sec_uid
    text = r.text or ""
    # RENDER_DATA / JSON 中的 "sec_uid":"..."
    m = re.search(r'sec_uid["\']?\s*[:=]\s*["\'](' + _SEC_RE.pattern + r')', text)
    if m:
        return m.group(1)
    # <link rel="canonical" href=".../user/{sec_uid}">
    m = re.search(r'https?://[^"\'> ]*?/user/(' + _SEC_RE.pattern + r')', text)
    if m:
        return m.group(1)

    raise RuntimeError(
        "未能从该链接解析出 sec_uid（可能是私密账号、链接已失效，"
        "或粘贴的不是主页链接）。请尝试：在抖音 App 打开对方主页 → "
        "分享 → 复制链接，粘贴以 /user/ 或 v.douyin.com 开头的链接。"
    )


# ---------------- 单视频 aweme_id 解析 ----------------
_AWEME_RE = re.compile(r"\b(\d{16,20})\b")


def resolve_aweme_id(raw_url: str) -> str:
    """解析单个抖音视频分享链接 → aweme_id。"""
    if not raw_url or not raw_url.strip():
        raise ValueError("链接为空")
    url = raw_url.strip()

    # 1) 直接路径形态 /video/{aweme_id}
    m = re.search(r"/video/(\d{16,20})", url)
    if m:
        return m.group(1)
    # 2) modal_id / aweme_id 参数
    m = re.search(r"(?:modal_id|aweme_id)=(\d{16,20})", url)
    if m:
        return m.group(1)

    # 3) 短链 / 分享页：跟随跳转后从 HTML / RENDER_DATA 找
    try:
        r = requests.get(
            url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            allow_redirects=True, timeout=20)
    except Exception as e:
        raise RuntimeError(f"无法访问该链接：{e}")
    r.encoding = r.encoding or "utf-8"
    final = r.url or url
    m = re.search(r"/video/(\d{16,20})", final)
    if m:
        return m.group(1)
    text = r.text or ""
    # RENDER_DATA 里 "aweme_id":"xxx"
    m = re.search(r'aweme_id["\']?\s*[:=]\s*["\']?(\d{16,20})', text)
    if m:
        return m.group(1)
    # 兜底：找一段长数字（aweme_id 一般 19 位）
    m = _AWEME_RE.search(final)
    if m:
        return m.group(1)
    raise RuntimeError(
        "未能从该链接解析出 aweme_id，请尝试在抖音 App 内打开作品 → 分享 → 复制链接。"
    )
