#!/usr/bin/env python3
"""
Hermes Agent Status API — lightweight data collector for Hermes dashboard
Runs on VPS port 8504, serves JSON for Hermes dashboard on Vercel
"""
import json
import os
import subprocess
import time
import glob
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HOME = os.path.expanduser("~")
HERMES_DIR = os.path.join(HOME, ".hermes")
PROJECTS_DIR = os.path.join(HOME, "projects")

class HermesAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        
        if path == "/api/hermes/system":
            data = self.get_system_info()
        elif path == "/api/hermes/hermes":
            data = self.get_hermes_info()
        elif path == "/api/hermes/projects":
            data = self.get_projects()
        elif path == "/api/hermes/services":
            data = self.get_services()
        elif path == "/api/hermes/recent":
            data = self.get_recent_activity()
        elif path == "/api/hermes/agent-files":
            data = self.get_agent_files()
        elif path == "/api/hermes/all":
            data = {
                "system": self.get_system_info(),
                "hermes": self.get_hermes_info(),
                "projects": self.get_projects(),
                "services": self.get_services(),
                "recent": self.get_recent_activity(),
                "soul_md": self.get_soul_md(),
                "agents_md": self.get_agents_md(),
                "dashboard_status": self.get_dashboard_status(),
                "timestamp": time.time()
            }
        elif path == "/healthz" or path == "/api/hermes/health":
            data = {"status": "ok"}
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())
            return
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def _run(self, cmd, timeout=5):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()
        except:
            return None
    
    def get_system_info(self):
        mem = self._run("free -b | awk 'NR==2{print $2,$3,$4,$7}'")
        mem_parts = mem.split() if mem else ["0","0","0","0"]
        disk = self._run("df -B1 / | awk 'NR==2{print $2,$3,$4}'")
        disk_parts = disk.split() if disk else ["0","0","0"]
        load = self._run("cat /proc/loadavg")
        load_parts = load.split()[:3] if load else ["0","0","0"]
        uptime_secs = self._run("cat /proc/uptime | cut -d' ' -f1")
        
        return {
            "hostname": self._run("hostname"),
            "platform": self._run("uname -sr"),
            "uptime": float(uptime_secs or 0),
            "cpu": {
                "cores": int(self._run("nproc") or 0),
                "load_1m": float(load_parts[0]),
                "load_5m": float(load_parts[1]),
                "load_15m": float(load_parts[2]),
            },
            "memory": {
                "total": int(mem_parts[0]),
                "used": int(mem_parts[1]),
                "free": int(mem_parts[2]),
                "available": int(mem_parts[3]),
            },
            "disk": {
                "total": int(disk_parts[0]),
                "used": int(disk_parts[1]),
                "free": int(disk_parts[2]),
            }
        }
    
    def get_hermes_info(self):
        config_path = os.path.join(HERMES_DIR, "config.yaml")
        config_data = {}
        try:
            import yaml
            with open(config_path) as f:
                config_data = yaml.safe_load(f) or {}
        except:
            pass
        
        model_cfg = config_data.get("model", {})
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", "?")
            provider = model_cfg.get("provider", config_data.get("provider", "?"))
        else:
            model_name = str(model_cfg)
            provider = config_data.get("provider", "?")
        
        skills_dir = os.path.join(HERMES_DIR, "skills")
        skills_count = len(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else 0
        
        logs_dir = os.path.join(HERMES_DIR, "logs")
        error_size = 0
        gateway_size = 0
        if os.path.isdir(logs_dir):
            for f in os.listdir(logs_dir):
                fp = os.path.join(logs_dir, f)
                if os.path.isfile(fp):
                    if "error" in f.lower():
                        error_size += os.path.getsize(fp)
                    elif "gateway" in f.lower():
                        gateway_size += os.path.getsize(fp)
        
        memory_count = self._run("grep -c '§' " + os.path.join(HOME, ".hermes", "SOUL.md") + " 2>/dev/null") if os.path.exists(os.path.join(HOME, ".hermes", "SOUL.md")) else 0
        
        return {
            "model": model_name,
            "provider": provider,
            "skills": {
                "total": skills_count,
            },
            "logs": {
                "error_log_bytes": error_size,
                "gateway_log_bytes": gateway_size,
            },
            "aesculap": {
                "installed": os.path.isdir(os.path.join(HOME, "Aesculap-hermes")),
                "service_active": self._run("systemctl --user is-active aesculap.service 2>/dev/null") == "active",
            },
            "memory_entries": int(memory_count or 0),
        }
    
    def get_projects(self):
        projects = []
        if not os.path.isdir(PROJECTS_DIR):
            return projects
        for name in sorted(os.listdir(PROJECTS_DIR)):
            d = os.path.join(PROJECTS_DIR, name)
            if not os.path.isdir(d) or name.startswith("."):
                continue
            
            git_log = self._run(f"cd {d} && git log --oneline -1 2>/dev/null")
            git_branch = self._run(f"cd {d} && git rev-parse --abbrev-ref HEAD 2>/dev/null")
            git_remote = self._run(f"cd {d} && git remote -v 2>/dev/null | head -1 | awk '{{print $2}}'")
            
            projects.append({
                "name": name,
                "git": {
                    "branch": git_branch,
                    "last_commit": git_log,
                    "remote": git_remote,
                }
            })
        
        return projects
    
    def get_services(self):
        pm2_list = self._run("pm2 list 2>/dev/null | grep -v '┬\\|─\\|┌\\|└' | grep '│' | head -10")
        services = []
        if pm2_list:
            for line in pm2_list.split("\n"):
                parts = [p.strip() for p in line.split("│") if p.strip()]
                if len(parts) >= 4:
                    services.append({
                        "name": parts[1] if len(parts) > 1 else "?",
                        "status": parts[4] if len(parts) > 4 else "?",
                        "cpu": parts[5] if len(parts) > 5 else "?",
                        "memory": parts[6] if len(parts) > 6 else "?",
                    })
        return services
    
    def get_dashboard_status(self):
        """Read cached dashboard status generated by cron"""
        cache_file = os.path.join(HERMES_DIR, "data", "dashboard", "status.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {"task_history": [], "cross_project_issues": [], "recent_sessions": [], "memory": [], "errors": []}

    def get_soul_md(self):
        """Read SOUL.md key sections"""
        path = os.path.join(HERMES_DIR, "SOUL.md")
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        return {
            "total_lines": len(lines),
            "version": self._extract_section(content, "文件版本"),
            "sections": [
                {"title": "1. 身份", "summary": "认知与行动助手"},
                {"title": "2. 根本目标", "summary": "更快看见本质，更少犯高代价错误"},
                {"title": "4. 第一性原理", "summary": "分解到基本前提，自底向上形成判断"},
                {"title": "6. 不可绕过的硬约束", "summary": "真实 > 效率，禁止拟构，禁止流畅型欺骗"},
                {"title": "7. 反幻觉协议", "summary": "先证据后结论，无依据不补洞"},
                {"title": "12. 最高执行口令", "summary": "宁可慢一点，绝不编造"},
            ]
        }

    def _extract_section(self, content, keyword):
        for line in content.split("\n"):
            if keyword in line:
                return line.strip()
        return ""

    def get_agents_md(self):
        """Read AGENTS.md key sections"""
        path = os.path.join(HERMES_DIR, "AGENTS.md")
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        return {
            "total_lines": len(lines),
            "summary": self._extract_section(content, "猪猪微"),
            "description": content[:500] if len(content) > 500 else content,
        }

    def get_recent_activity(self):
        recent = []
        
        # Recent git commits across projects — collect all then sort by time
        for name in sorted(os.listdir(PROJECTS_DIR)):
            d = os.path.join(PROJECTS_DIR, name)
            if not os.path.isdir(d) or name.startswith("."):
                continue
            
            commits = self._run(f"cd {d} && git log --oneline -5 --format='%h|%s|%at|%ar' 2>/dev/null")
            if commits:
                for line in commits.split("\n")[:5]:
                    parts = line.split("|")
                    if len(parts) >= 4:
                        recent.append({
                            "project": name,
                            "hash": parts[0],
                            "message": parts[1],
                            "timestamp": int(parts[2]),
                            "ago": parts[3],
                        })
        # Sort by timestamp descending (newest first)
        recent.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return recent[:30]


if __name__ == "__main__":
    port = 8504
    server = HTTPServer(("0.0.0.0", port), HermesAPIHandler)
    print(f"Hermes API server running on http://0.0.0.0:{port}")
    print(f"Endpoints:")
    print(f"  GET /api/hermes/all       — full status")
    print(f"  GET /api/hermes/system    — system info")
    print(f"  GET /api/hermes/hermes    — hermes info")
    print(f"  GET /api/hermes/projects  — project list")
    print(f"  GET /api/hermes/services  — services status")
    print(f"  GET /api/hermes/recent    — recent activity")
    server.serve_forever()
