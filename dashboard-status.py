#!/usr/bin/env python3
"""
Hermes Dashboard Status Generator
Cron job that collects memory, task history, cross-project issues
and writes to cache JSON for the dashboard frontend.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
HERMES_DIR = os.path.join(HOME, ".hermes")
PROJECTS_DIR = os.path.join(HOME, "projects")
CACHE_DIR = os.path.join(HERMES_DIR, "data", "dashboard")
CACHE_FILE = os.path.join(CACHE_DIR, "status.json")

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""

def run_lines(cmd, timeout=10):
    out = run(cmd, timeout)
    return [l for l in out.split("\n") if l.strip()] if out else []

# ──────────────────────────────────────────────
# 1. Memory extraction
# ──────────────────────────────────────────────
def get_memory():
    """Read memory from the SOUL.md MEMORY section or other sources"""
    memories = []
    
    # Try to read from the memory tool's SQLite storage
    state_db = os.path.join(HERMES_DIR, "state.db")
    if os.path.exists(state_db):
        try:
            import sqlite3
            conn = sqlite3.connect(state_db)
            cur = conn.cursor()
            # Read from state_meta - memory might be stored here
            cur.execute("SELECT key, value FROM state_meta WHERE key LIKE '%memory%' OR key LIKE '%MEMORY%'")
            rows = cur.fetchall()
            for k, v in rows:
                if v:
                    memories.append({"key": k, "content": v[:500]})
            conn.close()
        except:
            pass
    
    return memories

# ──────────────────────────────────────────────
# 2. Cross-project issues
# ──────────────────────────────────────────────
def get_cross_project_issues():
    """Find issues/bugs by examining git history, error logs, and recent commits"""
    issues = []
    
    for proj_name in sorted(os.listdir(PROJECTS_DIR)):
        proj_dir = os.path.join(PROJECTS_DIR, proj_name)
        if not os.path.isdir(proj_dir) or proj_name.startswith("."):
            continue
        
        # Look for TODO/FIXME/BUG/HACK in recent commits
        commits = run_lines(f"cd {proj_dir} && git log --all --oneline -20 --grep='fix\\|bug\\|error\\|hotfix\\|patch\\|issue' 2>/dev/null", timeout=5)
        for c in commits[:5]:
            parts = c.split(" ", 1)
            if len(parts) == 2:
                issues.append({
                    "project": proj_name,
                    "type": "fix",
                    "hash": parts[0],
                    "message": parts[1],
                    "time": run(f"cd {proj_dir} && git log -1 --format=%ar {parts[0]} 2>/dev/null", timeout=3)
                })
        
        # Check for uncommitted changes
        status = run(f"cd {proj_dir} && git status --short 2>/dev/null", timeout=3)
        if status:
            dirty_count = len([l for l in status.split("\n") if l.strip()])
            if dirty_count > 0:
                issues.append({
                    "project": proj_name,
                    "type": "dirty",
                    "message": f"{dirty_count} uncommitted file(s)",
                    "time": "now"
                })
    
    return issues

# ──────────────────────────────────────────────
# 3. Task history from cron outputs + git
# ──────────────────────────────────────────────
def get_task_history():
    """Compile task history from cron job outputs and recent activity"""
    tasks = []
    
    # Read latest cron outputs
    cron_dir = os.path.join(HERMES_DIR, "cron", "output")
    if os.path.isdir(cron_dir):
        for job_dir in sorted(os.listdir(cron_dir)):
            job_path = os.path.join(cron_dir, job_dir)
            if not os.path.isdir(job_path):
                continue
            reports = sorted(os.listdir(job_path), reverse=True)[:5]
            for report in reports:
                report_path = os.path.join(job_path, report)
                date_str = report.replace(".md", "").replace("_", " ")
                size = os.path.getsize(report_path) if os.path.isfile(report_path) else 0
                if size > 0:
                    tasks.append({
                        "type": "cron",
                        "job": job_dir[:8],
                        "date": date_str,
                        "size": size,
                        "detail": f"Cron job output ({size} bytes)"
                    })
    
    # Latest git commits across projects (last 24h)
    for proj_name in sorted(os.listdir(PROJECTS_DIR)):
        proj_dir = os.path.join(PROJECTS_DIR, proj_name)
        if not os.path.isdir(proj_dir) or proj_name.startswith("."):
            continue
        recent = run_lines(f"cd {proj_dir} && git log --since='24 hours ago' --oneline -5 2>/dev/null", timeout=5)
        for c in recent[:3]:
            parts = c.split(" ", 1)
            if len(parts) == 2:
                tasks.append({
                    "type": "commit",
                    "project": proj_name,
                    "message": parts[1],
                    "hash": parts[0],
                    "time": run(f"cd {proj_dir} && git log -1 --format=%ar {parts[0]} 2>/dev/null", timeout=3)
                })
    
    return tasks

# ──────────────────────────────────────────────
# 4. Recent sessions summary
# ──────────────────────────────────────────────
def get_recent_sessions():
    """Get recent Hermes sessions summary"""
    sessions = []
    state_db = os.path.join(HERMES_DIR, "state.db")
    if os.path.exists(state_db):
        try:
            import sqlite3
            conn = sqlite3.connect(state_db)
            cur = conn.cursor()
            cur.execute("""
                SELECT s.id, s.source, MIN(m.id), MAX(m.id), COUNT(m.id)
                FROM sessions s
                JOIN messages m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY MAX(m.id) DESC
                LIMIT 10
            """)
            for row in cur.fetchall():
                sessions.append({
                    "id": row[0][:20] if row[0] else "?",
                    "source": row[1] or "?",
                    "messages": row[4],
                })
            conn.close()
        except:
            pass
    return sessions

# ──────────────────────────────────────────────
# 5. Error summary
# ──────────────────────────────────────────────
def get_error_summary():
    """Read latest errors from Hermes error logs"""
    errors = []
    logs_dir = os.path.join(HERMES_DIR, "logs")
    if os.path.isdir(logs_dir):
        err_log = os.path.join(logs_dir, "errors.log")
        if os.path.exists(err_log):
            recent = run(f"tail -20 {err_log} 2>/dev/null", timeout=3)
            if recent:
                errors.append({"source": "errors.log", "lines": recent[:1000]})
    return errors

# ──────────────────────────────────────────────
# 6. Status generation & cache
# ──────────────────────────────────────────────
def generate_status():
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "memory": get_memory(),
        "cross_project_issues": get_cross_project_issues(),
        "task_history": sorted(get_task_history(), 
            key=lambda x: x.get("time", ""), reverse=True)[:30],
        "recent_sessions": get_recent_sessions(),
        "errors": get_error_summary(),
    }
    
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    
    print(f"✔ Dashboard status generated → {CACHE_FILE}")
    print(f"  Memory entries: {len(status['memory'])}")
    print(f"  Cross-project issues: {len(status['cross_project_issues'])}")
    print(f"  Task history: {len(status['task_history'])}")
    print(f"  Recent sessions: {len(status['recent_sessions'])}")
    print(f"  Error files: {len(status['errors'])}")

if __name__ == "__main__":
    generate_status()
