#!/usr/bin/env python3
"""Call Workbuddy/codebuddy once to score a single resume.

Configuration is via environment variables or CLI args. This script contains
no credentials. See ../config.example.md.

Usage:
  WB_WORK=./work WB_CLI=codebuddy WB_MODEL=hy4flash-free \\
    python scripts/run_one.py <candidate_id> [suffix] [max_turns] [timeout_s]

The prompt is read from $WB_WORK/prompts/{id}{suffix}.prompt.txt
Raw outputs are written under $WB_WORK/raw/.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

CID = sys.argv[1]
SUFFIX = sys.argv[2] if len(sys.argv) > 2 else ""
MAX_TURNS = sys.argv[3] if len(sys.argv) > 3 else "1"
TIMEOUT_S = int(sys.argv[4] if len(sys.argv) > 4 else os.environ.get("WB_TIMEOUT_S", "1800"))
MODEL = os.environ.get("WB_MODEL", "hy4flash-free")
WORK = Path(os.environ.get("WB_WORK", ".")).resolve()
CLI = os.environ.get("WB_CLI", "codebuddy")
SESSION_PREFIX = os.environ.get("WB_SESSION_PREFIX", "wb-resume")
SESSION_ID = f"{SESSION_PREFIX}-{CID}{SUFFIX}"

prompt_path = WORK / "prompts" / f"{CID}{SUFFIX}.prompt.txt"
prompt = prompt_path.read_text(encoding="utf-8")

env = os.environ.copy()
env["CODEBUDDY_INTERNET_ENVIRONMENT"] = env.get(
    "CODEBUDDY_INTERNET_ENVIRONMENT", "internal"
)

cmd = [
    CLI, "-p", prompt,
    "--model", MODEL,
    "--output-format", "stream-json",
    "--verbose",
    "--tools", "",
    "--max-turns", str(MAX_TURNS),
    "--session-id", SESSION_ID,
]

raw_dir = WORK / "raw"
raw_dir.mkdir(parents=True, exist_ok=True)

print(
    f"[{CID}{SUFFIX}] starting model={MODEL} prompt_chars={len(prompt)} "
    f"session={SESSION_ID} max_turns={MAX_TURNS} timeout={TIMEOUT_S}",
    flush=True,
)
t0 = time.time()
try:
    p = subprocess.run(
        cmd,
        cwd=str(WORK),
        env=env,
        capture_output=True,
        timeout=TIMEOUT_S,
        start_new_session=True,
    )
except subprocess.TimeoutExpired as e:
    elapsed = time.time() - t0
    stdout = e.stdout or b""
    stderr = e.stderr or b""
    try:
        if getattr(e, "process", None) is not None and e.process.pid:
            os.killpg(e.process.pid, 9)
    except Exception:
        pass
    (raw_dir / f"{CID}{SUFFIX}.stdout.bin").write_bytes(stdout if isinstance(stdout, (bytes, bytearray)) else str(stdout).encode())
    (raw_dir / f"{CID}{SUFFIX}.stderr.bin").write_bytes(stderr if isinstance(stderr, (bytes, bytearray)) else str(stderr).encode())
    out_txt = stdout.decode("utf-8", errors="replace") if isinstance(stdout, (bytes, bytearray)) else str(stdout)
    err_txt = stderr.decode("utf-8", errors="replace") if isinstance(stderr, (bytes, bytearray)) else str(stderr)
    (raw_dir / f"{CID}{SUFFIX}.stdout.txt").write_text(out_txt, encoding="utf-8")
    (raw_dir / f"{CID}{SUFFIX}.stderr.txt").write_text(err_txt, encoding="utf-8")
    meta = {
        "id": CID,
        "suffix": SUFFIX,
        "error": "timeout",
        "elapsed_s": elapsed,
        "returncode": None,
        "session_id": SESSION_ID,
        "model": MODEL,
        "stdout_bytes": len(stdout or b""),
        "stderr_bytes": len(stderr or b""),
    }
    (raw_dir / f"{CID}{SUFFIX}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{CID}{SUFFIX}] TIMEOUT after {elapsed:.1f}s session={SESSION_ID}", flush=True)
    sys.exit(2)

elapsed = time.time() - t0
stdout = p.stdout or b""
stderr = p.stderr or b""
(raw_dir / f"{CID}{SUFFIX}.stdout.bin").write_bytes(stdout)
(raw_dir / f"{CID}{SUFFIX}.stderr.bin").write_bytes(stderr)
(raw_dir / f"{CID}{SUFFIX}.stdout.txt").write_text(stdout.decode("utf-8", errors="replace"), encoding="utf-8")
(raw_dir / f"{CID}{SUFFIX}.stderr.txt").write_text(stderr.decode("utf-8", errors="replace"), encoding="utf-8")
meta = {
    "id": CID,
    "suffix": SUFFIX,
    "returncode": p.returncode,
    "elapsed_s": elapsed,
    "stdout_bytes": len(stdout),
    "stderr_bytes": len(stderr),
    "session_id": SESSION_ID,
    "max_turns": MAX_TURNS,
    "model": MODEL,
}
(raw_dir / f"{CID}{SUFFIX}.meta.json").write_text(
    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    f"[{CID}{SUFFIX}] done rc={p.returncode} elapsed={elapsed:.1f}s "
    f"stdout={len(stdout)} stderr={len(stderr)} session={SESSION_ID}",
    flush=True,
)
sys.exit(0 if p.returncode == 0 else 1)
