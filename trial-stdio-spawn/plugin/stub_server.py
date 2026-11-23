"""Minimal stdio MCP server for a CI trial. Standard library only."""

import json
import os
import subprocess
import sys


def parent_name(ppid):
    try:
        if sys.platform.startswith("linux"):
            with open(f"/proc/{ppid}/comm") as f:
                return f.read().strip()
        if sys.platform == "darwin":
            return subprocess.run(
                ["ps", "-o", "comm=", "-p", str(ppid)],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {ppid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            return out.split(",")[0].strip('"') if out else ""
    except Exception as exc:  # noqa: BLE001
        return f"? {exc}"
    return "?"


def log_start():
    path = os.environ.get("TRIAL_LOG")
    if not path:
        return
    ppid = os.getppid()
    rec = {
        "form": os.environ.get("TRIAL_FORM"),
        "wrapper": os.environ.get("TRIAL_WRAPPER"),
        "argv": sys.argv,
        "executable": sys.executable,
        "ppid": ppid,
        "parent": parent_name(ppid),
        "PATH": os.environ.get("PATH"),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    log_start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:
            continue
        method = msg.get("method")
        mid = msg["id"]
        if method == "initialize":
            params = msg.get("params") or {}
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "trial-stub", "version": "0.0.0"},
            }})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{
                "name": "echo",
                "description": "Returns its input.",
                "inputSchema": {"type": "object",
                                "properties": {"text": {"type": "string"}}},
            }]}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    main()
