"""Append non-blocking DeepSeek usage summaries to the private chat."""
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = os.path.join(os.environ.get("GOAI_DATA_DIR", os.path.join(os.path.dirname(__file__), "data")), "command-center.sqlite3")
TZ = ZoneInfo("Asia/Shanghai")


def stamp(day):
    return int(datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp())


def main(kind):
    today = datetime.now(TZ).date()
    if kind == "daily":
        start_day, end_day, title = today - timedelta(days=1), today, "费用日报"
    elif kind == "weekly":
        end_day = today - timedelta(days=today.weekday())
        start_day, title = end_day - timedelta(days=7), "费用周报"
    else:
        raise SystemExit("usage: usage_report.py daily|weekly")
    start_at, end_at = stamp(start_day), stamp(end_day)
    with sqlite3.connect(DB_PATH) as connection:
        calls, input_tokens, output_tokens, cost = connection.execute("""
          SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),
                 COALESCE(SUM(estimated_cost_usd),0)
          FROM usage_events WHERE created_at >= ? AND created_at < ?
        """, (start_at, end_at)).fetchone()
        body = (
            f"{title}｜{start_day.isoformat()} 至 {(end_day - timedelta(days=1)).isoformat()}\n"
            f"调用 {calls} 次 · 输入 {input_tokens:,} tokens · 输出 {output_tokens:,} tokens\n"
            f"预估费用 ${cost:.4f}（按 DeepSeek V4 Pro 峰时公开价估算，非账户实时余额）"
        )
        connection.execute(
            "INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(NULL,'assistant',?,NULL,?)",
            (body, int(time.time())),
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else "")
