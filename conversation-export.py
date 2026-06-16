#!/usr/bin/env python3
"""
Conversation Export — Hermes Agent 全部对话记录导出
从 state.db 读取所有会话和消息，输出 JSON + Markdown 两份文件
供 Dashboard API 读取展示。
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
STATE_DB = os.path.join(HOME, ".hermes", "state.db")
OUT_DIR = os.path.join(HOME, ".hermes", "data", "conversations")
JSON_OUT = os.path.join(OUT_DIR, "conversations.json")
MD_OUT = os.path.join(OUT_DIR, "conversations.md")

# IM 来源的友好名称
SOURCE_LABELS = {
    "weixin": "微信 (WeChat)",
    "yuanbao": "元宝 (WeCom)",
    "cron": "定时任务",
    "cli": "终端 (CLI)",
    "lightclawbot": "LightClaw Bot",
    "qqbot": "QQ Bot",
}


def fmt_time(ts):
    """Unix timestamp → readable local time string"""
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except:
        return str(ts)


def fmt_source(src):
    return SOURCE_LABELS.get(src, src or "未知")


def export_json(cursor):
    """Export all sessions + messages to JSON"""
    cursor.execute("""
        SELECT id, source, user_id, title,
               datetime(started_at, 'unixepoch') as started,
               datetime(ended_at, 'unixepoch') as ended,
               started_at as ts_start,
               message_count
        FROM sessions
        ORDER BY started_at DESC
    """)
    sessions = []
    for row in cursor.fetchall():
        sid, source, uid, title, started, ended, ts_start, msg_count = row

        # 获取该会话的所有对话消息（排除 tool 调用）
        cursor.execute("""
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY id ASC
        """, (sid,))
        messages = []
        for m in cursor.fetchall():
            messages.append({
                "id": m[0],
                "role": m[1],
                "content": m[2] or "",
                "timestamp": m[3],
                "time": fmt_time(m[3]),
            })

        sessions.append({
            "id": sid,
            "source": source,
            "source_label": fmt_source(source),
            "user_id": uid,
            "title": title or "(无标题)",
            "started_at": started or "",
            "ended_at": ended or "",
            "timestamp": ts_start or 0,
            "message_count": msg_count or len(messages),
            "messages": messages,
        })

    return sessions


def export_markdown(sessions):
    """Export all sessions to a readable Markdown file"""
    lines = []
    lines.append("# Hermes Agent — 全部对话记录")
    lines.append("")
    lines.append(f"> 导出时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"> 总会话数: {len(sessions)}")
    total_msgs = sum(len(s["messages"]) for s in sessions)
    lines.append(f"> 总消息数: {total_msgs}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, session in enumerate(sessions):
        title = session["title"]
        source = session["source_label"]
        started = session["started_at"]
        msg_count = len(session["messages"])

        lines.append(f"## {i+1}. {title}")
        lines.append("")
        lines.append(f"- **来源**: {source}")
        lines.append(f"- **会话ID**: `{session['id']}`")
        lines.append(f"- **时间**: {started}")
        lines.append(f"- **消息数**: {msg_count}")
        lines.append("")

        if not session["messages"]:
            lines.append("*(无对话消息)*")
            lines.append("")
            continue

        # 按时间顺序列出消息
        for m in session["messages"]:
            role_emoji = "👤 **用户**" if m["role"] == "user" else "🤖 **Agent**"
            msg_time = m["time"]
            content = m["content"]

            # 截取过长消息（保留标记）
            if len(content) > 500:
                content = content[:500] + f"\n\n> *(消息过长，剩余 {len(content)-500} 字符已截断)*"

            lines.append(f"### {role_emoji} · {msg_time}")
            lines.append("")
            # 用代码块保持格式
            lines.append("```text")
            lines.append(content)
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    if not os.path.exists(STATE_DB):
        print(f"❌ 数据库不存在: {STATE_DB}")
        return

    conn = sqlite3.connect(STATE_DB)
    cursor = conn.cursor()

    # 统计数据
    cursor.execute("SELECT COUNT(*) FROM sessions")
    total_sessions = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM messages WHERE role IN ('user', 'assistant')")
    total_messages = cursor.fetchone()[0]

    print(f"📖 读取数据库: {total_sessions} 个会话, {total_messages} 条对话消息...")

    # JSON 导出
    sessions = export_json(cursor)
    json_data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "generated_at_ts": time.time(),
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "sessions": sessions,
    }
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    json_size = os.path.getsize(JSON_OUT)
    print(f"  ✅ JSON 导出: {JSON_OUT} ({json_size/1024/1024:.1f} MB)")

    # Markdown 导出
    md_content = export_markdown(sessions)
    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write(md_content)
    md_size = os.path.getsize(MD_OUT)
    print(f"  ✅ Markdown 导出: {MD_OUT} ({md_size/1024/1024:.1f} MB)")

    conn.close()
    print(f"\n✨ 全量对话导出完成")


if __name__ == "__main__":
    main()
