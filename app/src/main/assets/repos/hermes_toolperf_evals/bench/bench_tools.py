#!/usr/bin/env python3
"""Tool-performance benchmark harness for Hermes core tools.

Runs a battery of realistic tasks through `hermes chat` with NeMo Relay
ATOF/ATIF tracing enabled, then scores each trajectory:
  - total turns (LLM calls), tool calls, tool errors
  - wasted turns (tool call retried after error, exact-duplicate calls)
  - wall time, tool-result bytes fed to model

Usage:
  python bench_tools.py run  --tag baseline --repeat 2
  python bench_tools.py score --tag baseline

Environment:
  BENCH_ROOT   working/results root                  (default: ./bench-workspace)
  BENCH_REPO   hermes-agent tree to put on PYTHONPATH (required for `run`)
  BENCH_HOME   HERMES_HOME for runs                   (default: $BENCH_ROOT/home)
Results land in $BENCH_ROOT/results/<tag>/.
"""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path
from collections import Counter

ROOT = Path(os.environ.get("BENCH_ROOT", "bench-workspace")).resolve()
REPO = Path(os.environ["BENCH_REPO"]).resolve() if os.environ.get("BENCH_REPO") else None
HOME = Path(os.environ.get("BENCH_HOME", str(ROOT / "home"))).resolve()

# Task battery: each exercises core terminal/file tool behavior where the DB
# mining showed waste. Fresh sandbox dir per run.
TASKS = {
    # patch-heavy: multi-edit in one file, tests unique-match failures
    "edit_dedup": "In {WORK}/proj/util.py there are three identical helper functions block_a, block_b, block_c each containing the line `value = value + 1`. Change ONLY block_b's line to `value = value + 2` using the patch tool (not write_file). Then print the file with read_file and reply DONE.",
    # read pagination: big file forces offset/limit navigation
    "big_file_nav": "Find the definition of the function `charlie_9000` in {WORK}/proj/big.py and report the exact line number and the constant it returns. The file is large. Reply with LINE=<n> CONST=<value>.",
    # search across tree with a typo'd dir (models often guess wrong paths)
    "search_misc": "Search the project at {WORK}/proj for every file containing the string TOKEN_ALPHA and list their relative paths. One of the matches is in a hidden dir. Reply with the sorted list.",
    # terminal state persistence: venv + env vars, models often re-source
    "term_state": "In {WORK}/proj run these steps: create a python venv at .venv, activate it, pip install a local wheel-less package by running `pip install -e ./pkg`, then run `python -c \"import minipkg; print(minipkg.VERSION)\"`. Reply with the version printed.",
    # background process lifecycle
    "bg_server": "Start the server {WORK}/proj/server.py (it binds 127.0.0.1:8765 and prints 'READY' when up) in the background, wait until it is ready, curl http://127.0.0.1:8765/ping, kill the server, and reply with the ping response body.",
    # multi-file refactor: rename symbol across files
    "refactor": "In {WORK}/proj rename the function `old_name` to `new_name` everywhere it appears (definition + call sites, 3 files). Use search and patch tools. Then run `python -m proj_check` from {WORK}/proj (it exits 0 printing OK if the rename is complete). Reply OK when it passes.",
    # error recovery: command that fails needs diagnosis
    "diag_fail": "Run the script {WORK}/proj/build.sh. It will fail. Diagnose why from the error, fix the problem (a missing file the script expects — create it with the exact content the script checks for), re-run, and reply with the final line it prints on success.",
    # git workflow
    "git_flow": "In {WORK}/proj/repo make a git commit: stage the modified file, commit with message 'fix: adjust rate', and reply with the short SHA of the new commit.",
    # --- hint-targeted tasks (A/B for terminal_hints PR) ---
    # bare `python` in instructions on a python3-only system
    "hint_python": "Run the data pipeline in {WORK}/proj by executing exactly what its README.md says to run, from that directory. Reply with the final number it prints.",
    # module import error due to venv confusion
    "hint_module": "A venv already exists at {WORK}/proj/venv with the package 'miniyaml' installed into it. Run the script {WORK}/proj/consume.py with the right interpreter so it works, and reply with the value it prints.",
    # gh-style field drift simulation: local CLI rejects a field and prints valid list
    "hint_fields": "Use the CLI tool {WORK}/proj/repotool (already executable) to print the 'title' and 'state' of item 7 as JSON. It takes --json <fields>. Reply with the state value.",
}

def make_sandbox(work: Path):
    proj = work / "proj"
    if proj.exists(): shutil.rmtree(proj)
    proj.mkdir(parents=True)
    # util.py with 3 identical blocks
    block = "def block_{n}(value):\n    # increment helper {n}\n    value = value + 1\n    return value\n\n"
    (proj / "util.py").write_text("".join(block.format(n=x) for x in "abc"))
    # big.py ~3500 lines with target at a deep line
    lines = []
    for i in range(1, 3500):
        lines.append(f"def filler_{i}():\n    return {i}\n")
        if i == 2887:
            lines.append("def charlie_9000():\n    return 424242\n")
    (proj / "big.py").write_text("\n".join(lines))
    # TOKEN_ALPHA files incl hidden dir
    (proj / "a.txt").write_text("TOKEN_ALPHA here\n")
    (proj / "sub").mkdir()
    (proj / "sub" / "b.py").write_text("x = 'TOKEN_ALPHA'\n")
    (proj / ".hidden").mkdir()
    (proj / ".hidden" / "c.cfg").write_text("key=TOKEN_ALPHA\n")
    # pkg for venv task
    pkg = proj / "pkg"
    (pkg / "minipkg").mkdir(parents=True)
    (pkg / "minipkg" / "__init__.py").write_text("VERSION = '7.7.7'\n")
    (pkg / "pyproject.toml").write_text(
        "[project]\nname='minipkg'\nversion='7.7.7'\n[build-system]\nrequires=['setuptools']\nbuild-backend='setuptools.build_meta'\n"
        "[tool.setuptools]\npackages=['minipkg']\n")
    # server.py
    (proj / "server.py").write_text(
        "import http.server, socketserver, sys\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        body=b'pong_bench_77' if self.path=='/ping' else b'ok'\n"
        "        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)\n"
        "    def log_message(self, *a): pass\n"
        "srv = socketserver.TCPServer(('127.0.0.1', 8765), H)\n"
        "print('READY', flush=True)\n"
        "srv.serve_forever()\n")
    # refactor: old_name in 3 files + checker
    (proj / "m1.py").write_text("def old_name(x):\n    return x * 2\n")
    (proj / "m2.py").write_text("from m1 import old_name\n\ndef use():\n    return old_name(21)\n")
    (proj / "m3.py").write_text("import m2\nRESULT = m2.use()\n")
    (proj / "proj_check.py").write_text(
        "import pathlib,sys\ntxt=''.join(p.read_text() for p in [pathlib.Path('m1.py'),pathlib.Path('m2.py'),pathlib.Path('m3.py')])\n"
        "if 'old_name' in txt: print('FAIL old_name still present'); sys.exit(1)\n"
        "if txt.count('new_name') < 3: print('FAIL new_name missing'); sys.exit(1)\n"
        "import m3\nassert m3.RESULT == 42\nprint('OK')\n")
    # build.sh failure scenario
    (proj / "build.sh").write_text(
        "#!/bin/bash\nset -e\nif [ ! -f manifest.lock ]; then\n  echo 'ERROR: manifest.lock missing (expected checksum line: sha256:cafebabe)' >&2\n  exit 3\nfi\ngrep -q 'sha256:cafebabe' manifest.lock || { echo 'ERROR: bad checksum in manifest.lock' >&2; exit 4; }\necho BUILD_SUCCESS_9931\n")
    os.chmod(proj / "build.sh", 0o755)
    # git repo
    repo = proj / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=b@b", "-c", "user.name=bench", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    (repo / "rate.py").write_text("RATE = 1\n")
    subprocess.run(["git", "add", "rate.py"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=b@b", "-c", "user.name=bench", "commit", "-q", "-m", "add rate"], cwd=repo, check=True)
    (repo / "rate.py").write_text("RATE = 2\n")
    # hint_python: README instructs bare `python`
    (proj / "README.md").write_text(
        "# Pipeline\n\nTo run the pipeline:\n\n```\npython pipeline.py --full\n```\n")
    (proj / "pipeline.py").write_text(
        "import sys\nassert '--full' in sys.argv\nprint('PIPELINE_RESULT=31337')\n")
    # hint_module: venv with a private package; consume.py imports it
    venv_dir = proj / "venv"
    import venv as venv_mod
    venv_mod.create(venv_dir, with_pip=False, symlinks=True)
    # install miniyaml straight into site-packages (no pip needed)
    sp = next((venv_dir / "lib").glob("python*")) / "site-packages"
    (sp / "miniyaml.py").write_text("MAGIC = 'MY_5150'\n")
    (proj / "consume.py").write_text("import miniyaml\nprint(miniyaml.MAGIC)\n")
    # hint_fields: CLI that rejects unknown json fields like gh does
    (proj / "repotool").write_text(
        "#!/usr/bin/env python3\n"
        "import sys, json\n"
        "VALID = ['id', 'name', 'status', 'headline', 'created']\n"
        "args = sys.argv[1:]\n"
        "if '--json' in args:\n"
        "    fields = args[args.index('--json')+1].split(',')\n"
        "    for f in fields:\n"
        "        if f not in VALID:\n"
        "            sys.stderr.write('Unknown JSON field: \"%s\"\\nAvailable fields:\\n' % f)\n"
        "            sys.stderr.write('\\n'.join('  '+v for v in VALID)+'\\n')\n"
        "            sys.exit(1)\n"
        "    out = {'id': 7, 'name': 'Rate limiter fix', 'status': 'MERGED_OK_991', 'headline': 'Rate limiter fix', 'created': '2026-01-01'}\n"
        "    print(json.dumps({f: out[f] for f in fields}))\n"
        "else:\n"
        "    sys.exit(2)\n")
    os.chmod(proj / "repotool", 0o755)
    return proj

def run(tag: str, repeat: int, only=None):
    if REPO is None:
        sys.exit("BENCH_REPO must point at a hermes-agent tree for `run`")
    resdir = ROOT / "results" / tag
    resdir.mkdir(parents=True, exist_ok=True)
    meta = []
    for rep in range(repeat):
        for name, prompt in TASKS.items():
            if only and name not in only: continue
            run_id = f"{name}-r{rep}"
            work = ROOT / "runs" / tag / run_id
            work.mkdir(parents=True, exist_ok=True)
            make_sandbox(work)
            atof = resdir / f"{run_id}.atof.jsonl"
            atif_dir = resdir / f"{run_id}.atif"
            atif_dir.mkdir(exist_ok=True)
            env = dict(os.environ)
            env.update({
                "PYTHONPATH": str(REPO),
                "HERMES_HOME": str(HOME),
                "HERMES_NEMO_RELAY_ATOF_ENABLED": "1",
                "HERMES_NEMO_RELAY_ATOF_OUTPUT_DIRECTORY": str(atof.parent),
                "HERMES_NEMO_RELAY_ATOF_FILENAME": atof.name,
                "HERMES_NEMO_RELAY_ATOF_MODE": "overwrite",
                "HERMES_NEMO_RELAY_ATIF_ENABLED": "1",
                "HERMES_NEMO_RELAY_ATIF_OUTPUT_DIRECTORY": str(atif_dir),
            })
            q = prompt.replace("{WORK}", str(work))
            model_args = []
            bench_model = os.environ.get("BENCH_MODEL")
            if bench_model:
                model_args = ["--model", bench_model]
            t0 = time.time()
            p = subprocess.run(
                [sys.executable, "-m", "hermes_cli.main", "chat", "--query", q,
                 "--quiet", "--max-turns", "40", "--accept-hooks", *model_args],
                cwd=work, env=env, capture_output=True, text=True, timeout=900)
            dt = time.time() - t0
            out = (p.stdout or "").strip().splitlines()
            meta.append({"run_id": run_id, "task": name, "rep": rep, "wall_s": round(dt, 1),
                         "exit": p.returncode, "last_line": out[-1] if out else "",
                         "tail": "\n".join(out[-15:]),
                         "stderr_tail": (p.stderr or "")[-500:]})
            print(f"[{run_id}] {dt:.0f}s exit={p.returncode} last={out[-1][:80] if out else ''!r}", flush=True)
    (resdir / "meta.json").write_text(json.dumps(meta, indent=2))

SUCCESS_MARKERS = {
    "edit_dedup": lambda t, w: "value = value + 2" in (w/"proj"/"util.py").read_text() and (w/"proj"/"util.py").read_text().count("value = value + 1") == 2,
    "big_file_nav": lambda t, w: "424242" in t,
    "search_misc": lambda t, w: "c.cfg" in t and "b.py" in t,
    "term_state": lambda t, w: "7.7.7" in t,
    "bg_server": lambda t, w: "pong_bench_77" in t,
    "refactor": lambda t, w: "OK" in t,
    "diag_fail": lambda t, w: "BUILD_SUCCESS_9931" in t,
    "git_flow": lambda t, w: bool(re.search(r"\b[0-9a-f]{7,12}\b", t)),
    "hint_python": lambda t, w: "31337" in t,
    "hint_module": lambda t, w: "MY_5150" in t,
    "hint_fields": lambda t, w: "MERGED_OK_991" in t,
}

def score(tag: str):
    resdir = ROOT / "results" / tag
    meta = json.loads((resdir / "meta.json").read_text())
    rows = []
    for m in meta:
        run_id = m["run_id"]
        atof = resdir / f"{run_id}.atof.jsonl"
        llm_calls = tool_calls = tool_errors = 0
        dup_calls = retry_after_err = 0
        result_bytes = 0
        seen_last = None
        last_err_tool = None
        per_tool = Counter(); per_tool_err = Counter()
        if atof.exists():
            for line in atof.read_text().splitlines():
                try: ev = json.loads(line)
                except Exception: continue
                kind = ev.get("kind"); cat = ev.get("category"); sc = ev.get("scope_category")
                if kind == "scope" and cat == "llm" and sc == "end":
                    llm_calls += 1
                elif kind == "scope" and cat == "tool" and sc == "start":
                    name = ev.get("name"); data = json.dumps(ev.get("data", ""), sort_keys=True)
                    sig = f"{name}|{data}"
                    tool_calls += 1; per_tool[name] += 1
                    if sig == seen_last: dup_calls += 1
                    if last_err_tool == name: retry_after_err += 1
                    seen_last = sig
                elif kind == "scope" and cat == "tool" and sc == "end":
                    name = ev.get("name")
                    md = ev.get("metadata", {})
                    d = ev.get("data")
                    ds = d if isinstance(d, str) else json.dumps(d or "")
                    result_bytes += len(ds)
                    is_err = md.get("status") not in (None, "ok")
                    if not is_err and isinstance(ds, str):
                        if re.search(r'"error":\s*"(?!null)', ds) or re.search(r'"exit_code":\s*[1-9-]', ds) or ds.startswith('"Error') or "not found" in ds[:200]:
                            is_err = True
                    if is_err:
                        tool_errors += 1; per_tool_err[name] += 1
                        last_err_tool = name
                    else:
                        last_err_tool = None
        work = ROOT / "runs" / tag / run_id
        try:
            ok = SUCCESS_MARKERS[m["task"]](m.get("tail") or m["last_line"], work)
        except Exception:
            ok = False
        rows.append({**m, "ok": ok, "llm_calls": llm_calls, "tool_calls": tool_calls,
                     "tool_errors": tool_errors, "dup_calls": dup_calls,
                     "retry_after_err": retry_after_err, "result_kb": result_bytes // 1024,
                     "per_tool": dict(per_tool), "per_tool_err": dict(per_tool_err)})
    (resdir / "scores.json").write_text(json.dumps(rows, indent=2))
    # summary table
    print(f"\n{'run':22s} {'ok':3s} {'llm':>4s} {'tools':>5s} {'errs':>4s} {'dup':>3s} {'retry':>5s} {'kb':>5s} {'wall':>5s}")
    agg = Counter()
    for r in rows:
        print(f"{r['run_id']:22s} {str(r['ok']):3s} {r['llm_calls']:4d} {r['tool_calls']:5d} {r['tool_errors']:4d} {r['dup_calls']:3d} {r['retry_after_err']:5d} {r['result_kb']:5d} {r['wall_s']:5.0f}")
        agg['ok'] += r['ok']; agg['llm'] += r['llm_calls']; agg['tools'] += r['tool_calls']
        agg['errs'] += r['tool_errors']; agg['kb'] += r['result_kb']; agg['wall'] += r['wall_s']
    n = len(rows)
    print(f"\nTOTAL n={n} ok={agg['ok']}/{n} llm={agg['llm']} tools={agg['tools']} errs={agg['errs']} kb={agg['kb']} wall={agg['wall']:.0f}s")

if __name__ == "__main__":
    if len(sys.argv) < 2 or "--tag" not in sys.argv:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    tag = sys.argv[sys.argv.index("--tag") + 1]
    if cmd == "run":
        rep = int(sys.argv[sys.argv.index("--repeat") + 1]) if "--repeat" in sys.argv else 1
        only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
        run(tag, rep, only)
    elif cmd == "score":
        score(tag)
