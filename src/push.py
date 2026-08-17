"""推送：本地快照（始终）+ QQ邮箱 SMTP（可选，免费不耗 MaxHub 积分）。
腾讯文档推送由 WorkBuddy 已连接连接器在小时级自动化中完成。"""
import smtplib
import ssl
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from common import (log, QQ_SMTP_ENABLED, QQ_EMAIL, QQ_SMTP_PASS, PUSH_TO_QQ,
                    SNAPSHOT_DIR, now_iso, get_meta)
from storage import count_rows


def push_local(summary):
    """把本次采集摘要写入本地快照（供看板/报告/自动化读取）。"""
    snap = {"ts": now_iso(), "summary": summary,
            "rows": {"profile": count_rows("profile_hourly"),
                     "post_stats": count_rows("post_stats_hourly"),
                     "boards": count_rows("board_hourly")}}
    path = SNAPSHOT_DIR / f"latest.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def push_qqmail(subject, body, attachments=None):
    """通过 QQ 邮箱 SMTP 发送（免费，不消耗 MaxHub 积分）。"""
    if not QQ_SMTP_ENABLED:
        log.info("QQ邮箱推送未启用（QQ_SMTP_ENABLED=false），跳过")
        return False
    if not (QQ_EMAIL and QQ_SMTP_PASS):
        log.warning("QQ邮箱凭据缺失（QQ_EMAIL / QQ_SMTP_PASS），跳过推送")
        return False
    to = PUSH_TO_QQ or QQ_EMAIL
    msg = MIMEMultipart()
    msg["From"] = QQ_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for att in (attachments or []):
        try:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(open(att, "rb").read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                            f"attachment; filename={att.split('/')[-1]}")
            msg.attach(part)
        except Exception as e:
            log.warning(f"附件添加失败 {att}: {e}")
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.qq.com", 465, context=ctx) as s:
            s.login(QQ_EMAIL, QQ_SMTP_PASS)
            s.sendmail(QQ_EMAIL, [to], msg.as_string())
        log.info(f"QQ邮箱推送成功 → {to}")
        return True
    except Exception as e:
        log.error(f"QQ邮箱推送失败: {e}")
        return False


def queue_tencent_docs(payload):
    """把待推送到腾讯文档的内容写入队列，供 WorkBuddy 自动化（已连接连接器）消费。"""
    qpath = SNAPSHOT_DIR / "tencent_docs_queue.jsonl"
    with open(qpath, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return qpath
