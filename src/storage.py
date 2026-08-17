"""SQLite 存储：小时级快照、作品、作品互动、榜单。"""
import sqlite3
import json
from common import DB_PATH, log

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS profile_hourly (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    nickname TEXT, sec_uid TEXT, uid TEXT, unique_id TEXT,
    follower_count INTEGER, total_favorited INTEGER,
    aweme_count INTEGER, favoriting_count INTEGER
);
CREATE TABLE IF NOT EXISTS post (
    aweme_id TEXT PRIMARY KEY,
    desc TEXT, create_time INTEGER, ptype TEXT DEFAULT 'video',
    first_seen TEXT, last_seen TEXT,
    cover_url TEXT, share_url TEXT, play_url TEXT, download_url TEXT
);
CREATE TABLE IF NOT EXISTS post_stats_hourly (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, aweme_id TEXT,
    digg_count INTEGER, comment_count INTEGER,
    collect_count INTEGER, share_count INTEGER, play_count INTEGER
);
CREATE TABLE IF NOT EXISTS board_hourly (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, board_type TEXT, rank INTEGER,
    name TEXT, extra TEXT
);
CREATE TABLE IF NOT EXISTS users (
    sec_uid TEXT PRIMARY KEY,
    nickname TEXT, avatar_url TEXT, profile_url TEXT,
    unique_id TEXT, uid TEXT,
    follower_count INTEGER, total_favorited INTEGER, aweme_count INTEGER,
    fetched_at TEXT, post_count INTEGER
);
"""


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """补齐 sec_uid 列，并把历史 NULL 行回填为张真源（历史上唯一账号）。"""
    for tbl in ("post", "post_stats_hourly"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
        if "sec_uid" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN sec_uid TEXT")
    try:
        from common import DOUYIN_SEC_UID
        if DOUYIN_SEC_UID:
            for tbl in ("post", "post_stats_hourly"):
                conn.execute(
                    f"UPDATE {tbl} SET sec_uid=? WHERE sec_uid IS NULL",
                    (DOUYIN_SEC_UID,))
    except Exception as e:
        log.warning("sec_uid 回填跳过: %s", e)
    conn.commit()


def set_meta(key, value):
    conn = get_conn()
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
    conn.commit()
    conn.close()


def get_meta(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def insert_profile(ts, p):
    conn = get_conn()
    conn.execute(
        "INSERT INTO profile_hourly(ts,nickname,sec_uid,uid,unique_id,"
        "follower_count,total_favorited,aweme_count,favoriting_count) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (ts, p.get("nickname"), p.get("sec_uid"), p.get("uid"),
         p.get("unique_id"), p.get("follower_count"), p.get("total_favorited"),
         p.get("aweme_count"), p.get("favoriting_count")))
    conn.commit()
    conn.close()


def upsert_post(p):
    conn = get_conn()
    conn.execute(
        "INSERT INTO post(aweme_id,desc,create_time,ptype,first_seen,last_seen,"
        "cover_url,share_url,play_url,download_url,sec_uid) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(aweme_id) DO UPDATE SET "
        "desc=excluded.desc, ptype=excluded.ptype, last_seen=excluded.last_seen, "
        "cover_url=excluded.cover_url, share_url=excluded.share_url, "
        "play_url=excluded.play_url, download_url=excluded.download_url, "
        "sec_uid=COALESCE(excluded.sec_uid, post.sec_uid)",
        (p["aweme_id"], p.get("desc"), p.get("create_time"), p.get("ptype", "video"),
         p.get("first_seen"), p.get("last_seen"), p.get("cover_url"),
         p.get("share_url"), p.get("play_url"), p.get("download_url"),
         p.get("sec_uid")))
    conn.commit()
    conn.close()


def insert_post_stats(ts, aweme_id, s, sec_uid=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO post_stats_hourly(ts,aweme_id,digg_count,comment_count,"
        "collect_count,share_count,play_count,sec_uid) VALUES(?,?,?,?,?,?,?,?)",
        (ts, aweme_id, s.get("digg_count"), s.get("comment_count"),
         s.get("collect_count"), s.get("share_count"), s.get("play_count"),
         sec_uid))
    conn.commit()
    conn.close()


def insert_board(ts, board_type, rank, name, extra):
    conn = get_conn()
    conn.execute(
        "INSERT INTO board_hourly(ts,board_type,rank,name,extra) "
        "VALUES(?,?,?,?,?)",
        (ts, board_type, rank, name, json.dumps(extra, ensure_ascii=False)))
    conn.commit()
    conn.close()


def latest_profile(sec_uid=None):
    conn = get_conn()
    if sec_uid:
        row = conn.execute(
            "SELECT ts,nickname,follower_count,total_favorited,aweme_count "
            "FROM profile_hourly WHERE sec_uid=? ORDER BY id DESC LIMIT 1",
            (sec_uid,)).fetchone()
    else:
        row = conn.execute(
            "SELECT ts,nickname,follower_count,total_favorited,aweme_count "
            "FROM profile_hourly ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row


def profile_series(sec_uid=None):
    conn = get_conn()
    if sec_uid:
        rows = conn.execute(
            "SELECT ts,follower_count,total_favorited,aweme_count "
            "FROM profile_hourly WHERE sec_uid=? ORDER BY id",
            (sec_uid,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT ts,follower_count,total_favorited,aweme_count "
            "FROM profile_hourly ORDER BY id").fetchall()
    conn.close()
    return rows


def post_list(sec_uid=None):
    conn = get_conn()
    if sec_uid:
        rows = conn.execute(
            "SELECT aweme_id,desc,create_time,cover_url,share_url,play_url,"
            "download_url,last_seen FROM post WHERE sec_uid=? "
            "ORDER BY create_time DESC", (sec_uid,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT aweme_id,desc,create_time,cover_url,share_url,play_url,"
            "download_url,last_seen FROM post ORDER BY create_time DESC").fetchall()
    conn.close()
    return rows


def post_stats_rows(sec_uid=None):
    conn = get_conn()
    if sec_uid:
        rows = conn.execute(
            "SELECT ts,aweme_id,digg_count,comment_count,collect_count,"
            "share_count,play_count FROM post_stats_hourly WHERE sec_uid=? "
            "ORDER BY aweme_id,id", (sec_uid,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT ts,aweme_id,digg_count,comment_count,collect_count,"
            "share_count,play_count FROM post_stats_hourly ORDER BY aweme_id,id"
        ).fetchall()
    conn.close()
    return rows


def post_stats_series(aweme_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT ts,digg_count,comment_count,collect_count,share_count,play_count "
        "FROM post_stats_hourly WHERE aweme_id=? ORDER BY id", (aweme_id,)).fetchall()
    conn.close()
    return rows


def latest_post_stats(aweme_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT ts,digg_count,comment_count,collect_count,share_count,play_count "
        "FROM post_stats_hourly WHERE aweme_id=? ORDER BY id DESC LIMIT 1",
        (aweme_id,)).fetchone()
    conn.close()
    return row


def board_latest(board_type):
    conn = get_conn()
    # 取该类型最近一次快照（按最大 id 对应的 ts）
    row = conn.execute(
        "SELECT ts FROM board_hourly WHERE board_type=? ORDER BY id DESC LIMIT 1",
        (board_type,)).fetchone()
    if not row:
        conn.close()
        return []
    ts = row[0]
    rows = conn.execute(
        "SELECT rank,name,extra FROM board_hourly WHERE board_type=? AND ts=? "
        "ORDER BY rank", (board_type, ts)).fetchall()
    conn.close()
    return [{"rank": r[0], "name": r[1], "extra": json.loads(r[2])} for r in rows]


def count_rows(table):
    conn = get_conn()
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


# ---------------- users：已抓取账号索引 ----------------

def save_user(u):
    conn = get_conn()
    conn.execute(
        "INSERT INTO users(sec_uid,nickname,avatar_url,profile_url,unique_id,uid,"
        "follower_count,total_favorited,aweme_count,fetched_at,post_count) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(sec_uid) DO UPDATE SET "
        "nickname=excluded.nickname, avatar_url=excluded.avatar_url, "
        "profile_url=excluded.profile_url, unique_id=excluded.unique_id, "
        "uid=excluded.uid, follower_count=excluded.follower_count, "
        "total_favorited=excluded.total_favorited, aweme_count=excluded.aweme_count, "
        "fetched_at=excluded.fetched_at, post_count=excluded.post_count",
        (u.get("sec_uid"), u.get("nickname"), u.get("avatar_url"),
         u.get("profile_url"), u.get("unique_id"), u.get("uid"),
         u.get("follower_count"), u.get("total_favorited"),
         u.get("aweme_count"), u.get("fetched_at"), u.get("post_count")))
    conn.commit()
    conn.close()


def get_user(sec_uid):
    conn = get_conn()
    row = conn.execute(
        "SELECT sec_uid,nickname,avatar_url,profile_url,unique_id,uid,"
        "follower_count,total_favorited,aweme_count,post_count,fetched_at "
        "FROM users WHERE sec_uid=?", (sec_uid,)).fetchone()
    conn.close()
    if not row:
        return None
    keys = ["sec_uid", "nickname", "avatar_url", "profile_url", "unique_id",
            "uid", "follower_count", "total_favorited", "aweme_count",
            "post_count", "fetched_at"]
    return dict(zip(keys, row))


def get_users():
    conn = get_conn()
    rows = conn.execute(
        "SELECT sec_uid,nickname,avatar_url,profile_url,unique_id,uid,"
        "follower_count,total_favorited,aweme_count,post_count,fetched_at "
        "FROM users ORDER BY fetched_at DESC").fetchall()
    conn.close()
    keys = ["sec_uid", "nickname", "avatar_url", "profile_url", "unique_id",
            "uid", "follower_count", "total_favorited", "aweme_count",
            "post_count", "fetched_at"]
    return [dict(zip(keys, r)) for r in rows]
