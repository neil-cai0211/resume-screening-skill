#!/usr/bin/env python3
"""Extract a Workbuddy score JSON for one candidate.

Looks at, in order:
  1. $WB_SESSION_DIR/{session-prefix}-{id}{suffix}*.jsonl
  2. $WB_WORK/raw/{id}{suffix}.stdout.txt (stream-json)

Writes $WB_WORK/raw/{id}{suffix}.result.json and prints a one-line summary.
Contains no credentials and no hard-coded candidate sessions.

Usage:
  WB_WORK=./work python scripts/extract_result.py <candidate_id> [suffix]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CID = sys.argv[1]
SUFFIX = sys.argv[2] if len(sys.argv) > 2 else ""
WORK = Path(os.environ.get("WB_WORK", ".")).resolve()
SESSION_DIR = Path(os.environ.get("WB_SESSION_DIR", "")).expanduser() if os.environ.get("WB_SESSION_DIR") else None
SESSION_PREFIX = os.environ.get("WB_SESSION_PREFIX", "wb-resume")


def parse_score(text: str):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1]
        if t.endswith("```"):
            t = t[: t.rfind("```")]
        t = t.strip()
        if t.startswith("json"):
            t = t[4:].strip()
    i = t.find("{")
    j = t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no json braces")
    return json.loads(t[i : j + 1])


def find_session() -> Path | None:
    if SESSION_DIR is None or not SESSION_DIR.exists():
        return None
    candidates = []
    exact = SESSION_DIR / f"{SESSION_PREFIX}-{CID}{SUFFIX}.jsonl"
    if exact.exists():
        candidates.append(exact)
    candidates.extend(
        sorted(
            SESSION_DIR.glob(f"{SESSION_PREFIX}-{CID}{SUFFIX}*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    )
    return next((p for p in candidates if p.exists()), None)


path = find_session()
score = None
err = None
asst = None
pd = {}
ru = {}
users = []
text = ""

if path is not None:
    lines = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assts = [o for o in lines if o.get("type") == "message" and o.get("role") == "assistant"]
    users = [o for o in lines if o.get("type") == "message" and o.get("role") == "user"]
    if assts:
        asst = assts[-1]
        pd = asst.get("providerData") or {}
        ru = pd.get("rawUsage") or {}
        content = asst.get("content")
        texts = []
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    texts.append(c.get("text") or "")
        elif isinstance(content, str):
            texts.append(content)
        text = "\n".join(texts).strip()
        try:
            score = parse_score(text)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

if score is None:
    stdout_path = WORK / "raw" / f"{CID}{SUFFIX}.stdout.txt"
    if stdout_path.exists():
        for ln in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                ev = json.loads(ln)
            except Exception:
                continue
            if ev.get("type") == "result":
                r = ev.get("result") or ""
                try:
                    score = parse_score(r)
                    err = None if score else err
                except Exception as e:
                    err = err or f"stdout {type(e).__name__}: {e}"

delta_ms = None
if asst and users and asst.get("timestamp") and users[0].get("timestamp"):
    delta_ms = asst["timestamp"] - users[0]["timestamp"]

meta_p = WORK / "raw" / f"{CID}{SUFFIX}.meta.json"
meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}

out = {
    "candidate_id": CID,
    "suffix": SUFFIX,
    "session_file": str(path) if path else None,
    "status": (asst or {}).get("status"),
    "requestModelId": pd.get("requestModelId") or meta.get("model"),
    "model": pd.get("model") or pd.get("requestModelId") or meta.get("model"),
    "requestModelName": pd.get("requestModelName"),
    "duration_ms_session": delta_ms,
    "elapsed_s": meta.get("elapsed_s"),
    "rawUsage": {
        "prompt_tokens": ru.get("prompt_tokens"),
        "completion_tokens": ru.get("completion_tokens"),
        "total_tokens": ru.get("total_tokens"),
        "reasoning_tokens": (ru.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "cached_tokens": (ru.get("prompt_tokens_details") or {}).get("cached_tokens") or ru.get("cached_tokens"),
        "credit": ru.get("credit"),
        "original_credit": ru.get("original_credit"),
        "quota": ru.get("quota"),
    },
    "score": score,
    "error": err if score is None else None,
    "raw_text_head": (text[:500] if text and score is None else None),
}

out_path = WORK / "raw" / f"{CID}{SUFFIX}.result.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    json.dumps(
        {
            "id": CID,
            "suffix": SUFFIX,
            "ok": score is not None,
            "total": (score or {}).get("总分"),
            "结论": (score or {}).get("结论"),
            "error": out["error"],
            "model": out["model"],
            "elapsed_s": out["elapsed_s"],
        },
        ensure_ascii=False,
    )
)
sys.exit(0 if score is not None else 1)
