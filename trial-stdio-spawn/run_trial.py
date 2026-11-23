"""CI trial driver: register stdio server forms with the Claude Code CLI and
record what `claude mcp list` reports. Never fails the job."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = sys.platform == "win32"
FORMS = ["f1", "f2", "f3", "f4", "f5", "f6", "f7"]


def banner(text):
    print("\n" + "=" * 70 + "\n" + text + "\n" + "=" * 70, flush=True)


def run(cmd, env, cwd, timeout=180):
    print(f"\n$ {cmd}", flush=True)
    try:
        p = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True,
                           timeout=timeout)
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        code = p.returncode
    except Exception as exc:  # noqa: BLE001
        out, err, code = "", f"<exception {exc!r}>", -999
    if out:
        print(out.rstrip())
    if err:
        print("[stderr] " + err.rstrip())
    print(f"[exit {code}]", flush=True)
    return code, out, err


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    label = sys.argv[1]
    strip_git_sh = "--strip-git-sh" in sys.argv
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    env["PYTHONIOENCODING"] = "utf-8"

    if strip_git_sh:
        kept, dropped = [], []
        for entry in env["PATH"].split(os.pathsep):
            low = entry.lower().rstrip("\\")
            if "\\git\\" in low + "\\" and not low.endswith("\\git\\cmd"):
                dropped.append(entry)
            else:
                kept.append(entry)
        env["PATH"] = os.pathsep.join(kept)
        print("Dropped PATH entries:", json.dumps(dropped, indent=1))
    os.environ["PATH"] = env["PATH"]

    cfg = tempfile.mkdtemp(prefix=f"claude-cfg-{label}-")
    work = tempfile.mkdtemp(prefix=f"claude-work-{label}-")
    log = os.path.join(tempfile.mkdtemp(prefix="triallog-"), "spawn.log")
    env["CLAUDE_CONFIG_DIR"] = cfg
    env["TRIAL_LOG"] = log

    banner(f"PASS {label} on {sys.platform}")
    print("calling PATH:", env["PATH"])
    if WIN:
        run(["where", "sh"], env, work)
        run(["where", "bash"], env, work)
    else:
        run(["sh", "-c", "command -v sh; command -v bash"], env, work)

    claude = shutil.which("claude", path=env["PATH"])
    print("claude resolved to:", claude)
    if not claude:
        print("RESULT: claude not found")
        return
    c = [claude]
    run(c + ["--version"], env, work)
    if label.endswith("main"):
        run(c + ["--help"], env, work)
        run(c + ["mcp", "add", "--help"], env, work)

    py = sys.executable
    stub = os.path.join(HERE, "stub")
    forms = {
        "f1": ([py, os.path.join(HERE, "stub_server.py")], []),
        "f2": ([stub], []),
        "f3": (["sh", os.path.join(HERE, "stub.sh")], []),
        "f4": ([os.path.join(HERE, "stub.cmd")], []),
        "f5": ([os.path.join(HERE, "both", "stub")], []),
        "f6": (["trialstubenv"],
               ["PATH=" + os.path.join(HERE, "onlyenv") + os.pathsep
                + env["PATH"]]),
        "f7": (["trial-no-such-command-xyz"], []),
        "f8": ([os.path.join(HERE, "lone", "stub")], []),
    }
    for name, (cmd, extra_env) in forms.items():
        envflags = ["-e", f"TRIAL_FORM={name}", "-e", f"TRIAL_LOG={log}"]
        for kv in extra_env:
            envflags += ["-e", kv]
        code, _, _ = run(c + ["mcp", "add", name] + envflags + ["--"] + cmd,
                         env, work)
        if code != 0:
            print(f"(mcp add failed for {name}; trying add-json)")
            spec = {"type": "stdio", "command": cmd[0], "args": cmd[1:],
                    "env": dict(kv.split("=", 1) for kv in
                                [f"TRIAL_FORM={name}", f"TRIAL_LOG={log}"] + extra_env)}
            run(c + ["mcp", "add-json", name, json.dumps(spec)], env, work)

    for f in os.listdir(cfg):
        print("config dir has:", f)
    _, listing, listerr = run(c + ["mcp", "list"], env, work, timeout=300)
    for name in forms:
        run(c + ["mcp", "get", name], env, work)

    banner(f"STUB SPAWN LOG {label}")
    spawned = []
    if os.path.exists(log):
        with open(log, encoding="utf-8") as fh:
            for line in fh:
                print(line.rstrip())
                try:
                    rec = json.loads(line)
                    spawned.append(rec.get("form"))
                    sp = rec.get("PATH") or ""
                    if sp == env["PATH"]:
                        print(f"  -> {rec.get('form')}: PATH same as caller")
                    else:
                        cp = env["PATH"].split(os.pathsep)
                        added = [p for p in sp.split(os.pathsep)
                                 if p not in cp]
                        missing = [p for p in cp
                                   if p not in sp.split(os.pathsep)]
                        print(f"  -> {rec.get('form')}: PATH differs; "
                              f"added={added} missing={missing}")
                except ValueError:
                    pass
    else:
        print("no spawn log written")

    plugin(c, env, work, label)
    banner(f"SPAWN LOG AFTER PLUGIN {label}")
    if os.path.exists(log):
        with open(log, encoding="utf-8") as fh:
            for line in fh:
                if '"plugin' in line:
                    print(line.rstrip())

    banner(f"RESULTS {label} ({sys.platform})")
    lines = (listing + "\n" + listerr).splitlines()
    for name in forms:
        hit = [ln for ln in lines if ln.strip().startswith(name + ":")]
        print(f"| {label} | {name} | {hit[0].strip() if hit else '<no line>'}"
              f" | spawn-log: {spawned.count(name)} |")


def plugin(c, env, work, label):
    banner(f"PLUGIN {label}")
    for sub in ("plugin", "plugin-lone"):
        pdir = os.path.join(HERE, sub)
        run(c + ["plugin", "validate", pdir], env, work)
        run(c + ["--plugin-dir", pdir, "mcp", "list"], env, work, timeout=300)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print("driver exception:", repr(exc))
    sys.exit(0)
