"""MaxHub API 客户端（抖音数据采集）。"""
import time
import requests
from common import log, MAXHUB_API_KEY, dig

BASE = "https://www.aconfig.cn/api/v1/douyin"


class MaxHubClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or MAXHUB_API_KEY
        if not self.api_key:
            raise RuntimeError("MAXHUB_API_KEY 未配置，请写入项目根目录 .env")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def _request(self, method, path, params=None, json_body=None, retries=1):
        url = f"{BASE}{path}"
        for attempt in range(retries + 1):
            try:
                if method == "GET":
                    r = self.session.get(url, params=params, timeout=30)
                else:
                    r = self.session.post(url, params=params, json=json_body, timeout=30)
            except requests.RequestException as e:
                log.warning(f"网络异常 {path}: {e}")
                if attempt < retries:
                    time.sleep(3)
                    continue
                return {"code": -1, "message": str(e)}

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    return {"code": -2, "message": "响应非 JSON"}
            if r.status_code == 429:
                log.warning("429 限流，5s 后重试")
                time.sleep(5)
                continue
            if r.status_code in (500, 502, 503) and attempt < retries:
                log.warning(f"{r.status_code} 服务端错误，重试")
                time.sleep(3)
                continue
            return {"code": r.status_code, "message": r.text[:200]}

        return {"code": -1, "message": "超过重试次数"}

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post(self, path, json_body=None):
        return self._request("POST", path, json_body=json_body)

    # ---------- 高层封装 ----------
    def profile_by_short_id(self, short_id):
        """通过抖音号取用户基础信息（含 sec_uid）。"""
        return self.get("/web/fetch_user_profile_by_short_id", {"short_id": short_id})

    def profile_detail(self, sec_user_id):
        """用户主页详情，带路径降级。"""
        candidates = [
            "/web/handler_user_profile_v4",
            "/app/v3/handler_user_profile_v4",
            "/web/handler_user_profile_v3",
        ]
        last = None
        for path in candidates:
            res = self.get(path, {"sec_user_id": sec_user_id})
            if res.get("code") == 0 and dig(res, "data.user", "data"):
                return res
            last = res
        return last or {"code": -1, "message": "profile_detail 全部失败"}

    def post_videos(self, sec_user_id, count=20, max_cursor=0):
        return self.get("/app/v3/fetch_user_post_videos", {
            "sec_user_id": sec_user_id, "count": count, "max_cursor": max_cursor,
        })

    def one_video(self, aweme_id):
        return self.get("/app/v3/fetch_one_video_v2", {"aweme_id": aweme_id})

    def challenge_list(self, page=1, page_size=20):
        return self.get("/billboard/fetch_hot_challenge_list",
                        {"page": page, "page_size": page_size})

    def hot_total_list(self, page=1, page_size=20, list_type="snapshot"):
        return self.get("/billboard/fetch_hot_total_list",
                        {"page": page, "page_size": page_size, "type": list_type})

    def challenge_search(self, keyword, cursor=0):
        return self.post("/search/fetch_challenge_search_v1", {
            "keyword": keyword, "cursor": cursor, "count": 20,
        })
