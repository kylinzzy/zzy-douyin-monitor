/**
 * 张真源监测站 · 抖音 CORS 转发 Worker（Cloudflare 免费层）
 * 部署：Cloudflare 控制台 → Workers → 新建 → 粘贴本文件 → 部署 → 得到 xxx.workers.dev
 * 作用：浏览器前端因 CORS 无法直接请求抖音接口，本 Worker 在服务端转发，并把
 *      Access-Control-Allow-Origin 设为 *，使前端可跨域拿到抖音数据。
 * 完全免费、零自建后端、不存储任何数据。
 *
 * 路由说明：
 *   /profile?sec_user_id=xxx    -> 抖音 /user/profile/other/ 返回用户画像
 *   /posts?sec_user_id=xxx&max_cursor=0 -> 抖音 /aweme/v1/web/aweme/post/ 返回作品页
 *   /detail?aweme_id=xxx         -> 抖音 /aweme/v1/web/aweme/detail/ 返回单条作品
 *   /resolve?url=xxx             -> 把抖音短链/主页链接解析为 sec_user_id
 */

const DOUYIN_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
  "Referer": "https://www.douyin.com/",
  "Accept": "application/json, text/plain, */*",
};

// 抖音接口基础地址（web 端免签名通道，浏览器直连会被 CORS 拦，故在此转发）
const APIS = {
  profile: "https://www.douyin.com/aweme/v1/web/user/profile/other/",
  posts:   "https://www.douyin.com/aweme/v1/web/aweme/post/",
  detail:  "https://www.douyin.com/aweme/v1/web/aweme/detail/",
  // 短链解析：v.douyin.com/xxx 会 302 跳转到带 sec_user_id 的主页
  resolve: "https://www.iesdouyin.com/web/api/v2/user/info/",
};

function cors(resp) {
  const h = new Headers(resp.headers);
  h.set("Access-Control-Allow-Origin", "*");
  h.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  h.set("Access-Control-Allow-Headers", "*");
  h.set("Cache-Control", "no-store");
  return new Response(resp.body, { status: resp.status, headers: h });
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-store",
    },
  });
}

async function douyinGet(url) {
  const r = await fetch(url, { headers: DOUYIN_HEADERS });
  const txt = await r.text();
  // 抖音有时返回非 JSON（风控页/验证码），原样透传给前端让它判断
  return new Response(txt, { status: r.status, headers: r.headers });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "*",
        },
      });
    }

    const p = url.pathname;
    try {
      // ---- /resolve : 主页链接/短链 -> sec_user_id ----
      if (p === "/resolve") {
        const target = url.searchParams.get("url");
        if (!target) return json({ ok: false, error: "缺少 url 参数" }, 400);
        // 先用抖音短链/主页直接抓，从 HTML 里抠 sec_user_id
        const r = await fetch(target, { headers: DOUYIN_HEADERS, redirect: "follow" });
        const html = await r.text();
        const m = html.match(/sec_user_id=([^&"'\s]+)/) ||
                  html.match(/"sec_user_id":"([^"]+)"/) ||
                  html.match(/ucid=([^&"'\s]+)/);
        if (m) return json({ ok: true, sec_user_id: m[1], profile_url: target });
        // 兜底：尝试 iesdouyin 接口
        const m2 = html.match(/user\/([A-Za-z0-9_-]{20,})/);
        if (m2) return json({ ok: true, sec_user_id: m2[1], profile_url: target });
        return json({ ok: false, error: "无法从链接解析出 sec_user_id，请直接粘贴 user/MS4w... 主页" }, 422);
      }

      // ---- /profile : 用户画像 ----
      if (p === "/profile") {
        const sec = url.searchParams.get("sec_user_id");
        if (!sec) return json({ ok: false, error: "缺少 sec_user_id" }, 400);
        const u = `${APIS.profile}?sec_user_id=${encodeURIComponent(sec)}&current_tab=post`;
        return cors(await douyinGet(u));
      }

      // ---- /posts : 作品列表（翻页）----
      if (p === "/posts") {
        const sec = url.searchParams.get("sec_user_id");
        const cursor = url.searchParams.get("max_cursor") || "0";
        if (!sec) return json({ ok: false, error: "缺少 sec_user_id" }, 400);
        const u = `${APIS.posts}?sec_user_id=${encodeURIComponent(sec)}` +
          `&count=20&max_cursor=${encodeURIComponent(cursor)}` +
          `&locate_query=false&show_live_replay_strategy=1` +
          `&current_tab=post&from_user_page=1`;
        return cors(await douyinGet(u));
      }

      // ---- /detail : 单条作品 ----
      if (p === "/detail") {
        const aid = url.searchParams.get("aweme_id");
        if (!aid) return json({ ok: false, error: "缺少 aweme_id" }, 400);
        const u = `${APIS.detail}?aweme_id=${encodeURIComponent(aid)}`;
        return cors(await douyinGet(u));
      }

      return json({ ok: false, error: "未知路径 " + p }, 404);
    } catch (e) {
      return json({ ok: false, error: String(e.message || e) }, 502);
    }
  },
};
