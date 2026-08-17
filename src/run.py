"""张真源抖音数据监测 —— 主运行入口。
每小时：采集 → 看板 → 报告 → 本地快照 → 免费推送（QQ邮箱/腾讯文档）。
运行： python src/run.py --once   （单次，供 WorkBuddy 小时级自动化调用）
       python src/run.py --loop   （本地守护，每小时一轮）

⚠️ 无 MAXHUB_API_KEY 时不再写假数据，dashboard/report 显示明确空状态与获取 key 的指引。
"""
import sys
import time
import traceback
from common import (log, now_iso, today_str, TARGET_NAME,
                    DASHBOARD_PATH, REPORT_DIR)
import collector
import dashboard
import report
import push


def run_once():
    log.info("=== 开始本轮采集 ===")
    summary = None
    try:
        summary = collector.collect()
    except Exception as e:
        log.error("采集失败: %s", e)
        traceback.print_exc()
        summary = {"mode": "error", "error": str(e)}

    try:
        dashboard.render()
    except Exception as e:
        log.error("看板生成失败: %s", e)

    try:
        push.push_local(summary or {})
    except Exception as e:
        log.error("本地快照失败: %s", e)

    try:
        push.queue_tencent_docs({
            "ts": now_iso(),
            "target": TARGET_NAME,
            "text": report.hourly_summary(),
            "dashboard": str(DASHBOARD_PATH),
        })
    except Exception as e:
        log.error("腾讯文档队列失败: %s", e)

    try:
        date = today_str()
        daily_md = REPORT_DIR / f"{date}.md"
        if not daily_md.exists():
            report.generate_daily()
            log.info("已生成每日报告: %s", daily_md)
    except Exception as e:
        log.error("每日报告失败: %s", e)

    try:
        push.push_qqmail(f"【张真源】小时播报 {now_iso()}", report.hourly_summary())
    except Exception as e:
        log.error("QQ邮箱推送失败: %s", e)

    log.info("=== 本轮完成: %s (mode=%s) ===",
             (summary or {}).get("ts", now_iso()),
             (summary or {}).get("mode", "unknown"))
    return summary


def main():
    if "--loop" in sys.argv:
        log.info("进入本地守护循环（每小时一轮）")
        while True:
            run_once()
            time.sleep(3600)
    else:
        run_once()


if __name__ == "__main__":
    main()
