"""把最新看板自动同步到 GitHub（kylinzzy/zzy-douyin-monitor），实现「页面自动拉取最新数据」。

本地产物：
  - data/data.json    前端运行时拉取的纯数据（轻量）
  - deploy/index.html 自包含前端渲染页（内联 CSS+JS+初始数据）

GitHub 仓库根同时部署 index.html（GitHub Pages 源）与 data.json（jsDelivr 可直拉），
故 GitHub Pages 与 CloudStudio 两个在线版都能在打开时实时拉到最新数据。

用 ~/.mgtv_gh_token（kylinzzy 的 PAT，repo 权限）走 Contents API，规避国内 443 直推限制。
"""
import os
import json
import base64
import logging
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

log = logging.getLogger("douyin-monitor")

ROOT = Path(__file__).resolve().parent.parent
OWNER, REPO = "kylinzzy", "zzy-douyin-monitor"
TOKEN_FILE = os.path.expanduser("~/.mgtv_gh_token")


def _token():
    p = Path(TOKEN_FILE)
    if not p.exists():
        raise RuntimeError("未找到 GitHub PAT（~/.mgtv_gh_token）")
    return p.read_text(encoding="utf-8").strip()


def _req(method, path, data=None, token=None):
    url = "https://api.github.com" + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Authorization", f"Bearer {token}")
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("User-Agent", "workbuddy")
    if body:
        r.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(r, timeout=40)


def _now():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def _put(local_rel, gh_path, msg, token):
    local = ROOT / local_rel
    if not local.exists():
        raise RuntimeError(f"本地文件不存在: {local}")
    content = base64.b64encode(local.read_bytes()).decode()
    sha = None
    try:
        r = _req("GET", f"/repos/{OWNER}/{REPO}/contents/{gh_path}", token=token)
        sha = json.load(r).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    payload = {"message": msg, "content": content}
    if sha:
        payload["sha"] = sha
    else:
        payload["branch"] = "main"
    r = _req("PUT", f"/repos/{OWNER}/{REPO}/contents/{gh_path}", payload, token=token)
    return json.load(r)


def publish_to_github():
    """推送 data.json + index.html 到 GitHub 仓库根。返回 {文件: commit_sha}。"""
    token = _token()
    stamp = _now()
    out = {}
    out["data.json"] = _put(
        "data/data.json", "data.json",
        f"data: 自动同步 · {stamp}", token)
    out["index.html"] = _put(
        "deploy/index.html", "index.html",
        f"site: 自动同步 · {stamp}", token)
    log.info("已同步到 GitHub：data.json + index.html")
    return {k: out[k].get("commit", {}).get("sha", "")[:10] for k in out}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("pushed:", publish_to_github())
