#!/usr/bin/env python3
"""Command line entry point for role-based resume screening."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from rubric import canonical, load_profile, make_prompt, read_json, require, require_resume_storage, route_role
from workflow import (acknowledge, authorize, delivery_status, ledger, load_route,
                      preview, queue, record, register, release_preview, reserve, role_allowed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", help="Private workspace outside this repository")
    parser.add_argument("--demo", action="store_true", help="Isolated simulated intake and previews")
    commands = parser.add_subparsers(dest="command", required=True)

    route = commands.add_parser("route")
    route.add_argument("profile", nargs="+", help="Only pass profiles configured for this intake")
    route.add_argument("--role")
    route.add_argument("--signal", action="append", default=[])
    prompt = commands.add_parser("prompt")
    prompt.add_argument("profile")
    prompt.add_argument("resume_text")

    intake = commands.add_parser("register")
    intake.add_argument("profile")
    intake.add_argument("candidate")
    intake.add_argument("name")
    intake.add_argument("employer")
    intake.add_argument("pdf")
    intake.add_argument("resume_text")
    intake.add_argument("--source", required=True, help="Private mail attachment or local intake ID")

    evaluation = commands.add_parser("record")
    evaluation.add_argument("profile")
    evaluation.add_argument("candidate")
    evaluation.add_argument("revision", type=int)
    evaluation.add_argument("result")

    for name in ("preview", "authorize", "reserve"):
        command = commands.add_parser(name)
        command.add_argument("profile")
        command.add_argument("delivery_config")
        if name != "preview":
            command.add_argument("batch")
        if name == "authorize":
            command.add_argument("approval_code")
            command.add_argument("--confirmation", required=True)
        if name == "reserve":
            command.add_argument("recipient")
            command.add_argument("part", choices=["message", "attachment"])
            command.add_argument("--manual-confirmation")

    ack = commands.add_parser("ack")
    ack.add_argument("batch")
    ack.add_argument("recipient")
    ack.add_argument("part", choices=["message", "attachment"])
    ack.add_argument("attempt")
    ack.add_argument("state", choices=["sent", "failed"])
    ack.add_argument("--receipt", required=True)
    commands.add_parser("queue").add_argument("profile")
    commands.add_parser("status").add_argument("batch")
    commands.add_parser("release").add_argument("batch")

    args = parser.parse_args()
    operation = args.command
    if operation == "route":
        profiles = [load_profile(path) for path in args.profile]
        for profile in profiles:
            role_allowed(profile, args.demo)
        role = route_role(profiles, args.role, args.signal)
        return {"status": "matched" if role else "needs_confirmation", "role": role}
    profile = None
    if hasattr(args, "profile"):
        profile = load_profile(args.profile)
        role_allowed(profile, args.demo)
    if operation == "prompt":
        require(not profile.get("original_resume"), "原始简历请走私有评分入口，避免在终端输出原文")
        print(make_prompt(profile, Path(args.resume_text).read_text(encoding="utf-8-sig")), end="")
        return None
    if not args.work:
        parser.error("--work is required for this command")
    if profile:
        require_resume_storage(profile, args.work)
    if args.demo and operation in {"authorize", "reserve", "ack"}:
        parser.error("demo workspace does not permit sending")
    route_config = (load_route(args.delivery_config, profile, args.demo)
                    if hasattr(args, "delivery_config") else None)
    with ledger(args.work, args.demo) as (db, workspace):
        if operation == "queue":
            return queue(db, profile)
        if operation == "register":
            return register(db, workspace, profile, args.candidate, args.name, args.employer,
                            args.pdf, args.resume_text, args.source)
        if operation == "record":
            require_resume_storage(profile, args.result)
            evaluation = record(db, profile, args.candidate, args.revision, read_json(args.result))
            if profile.get("original_resume"):
                fields = ("role", "version", "total", "bonus", "screening_score", "conclusion", "reason")
                return {key: evaluation[key] for key in fields if key in evaluation}
            return evaluation
        if operation == "preview":
            return preview(db, workspace, profile, route_config)
        if operation == "authorize":
            return authorize(db, profile, route_config, args.batch, args.approval_code, args.confirmation)
        if operation == "reserve":
            return reserve(db, profile, route_config, args.batch, args.recipient, args.part,
                           args.manual_confirmation)
        if operation == "ack":
            return acknowledge(db, args.batch, args.recipient, args.part, args.attempt,
                               args.state, args.receipt)
        if operation == "release":
            return release_preview(db, args.batch)
        return delivery_status(db, args.batch)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        result = main()
        if result is not None:
            print(canonical(result))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"操作停止：{exc}", file=sys.stderr)
        sys.exit(1)
