#!/usr/bin/env python3
"""Score one sanitized resume with the signed-in Codex CLI."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from rubric import ROOT, STATUSES, evaluate, load_profile, make_prompt, require


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def response_schema(profile):
    text = {"type": "string"}
    score = object_schema({"points": {"type": "integer"}, "evidence": text})
    check = object_schema({"status": {"type": "string", "enum": sorted(STATUSES)}, "evidence": text})
    return object_schema({
        "scores": object_schema(dict.fromkeys(profile["dimensions"], score)),
        "checks": object_schema(dict.fromkeys(profile["checks"], check)),
        "comments": object_schema(dict.fromkeys(profile["output"]["fields"], text)),
    })


def score(profile, resume, output, cli, model, timeout):
    prompt = "只使用下方提供的材料，整个评分过程中无需调用工具。\n\n" + make_prompt(profile, resume)
    output = Path(output).resolve()
    require(not output.is_relative_to(ROOT), "评分输出必须存放在发布仓库外")
    require(not output.exists(), "评分结果已存在，重试请使用新的文件名")
    executable = shutil.which(cli)
    require(executable is not None, "找不到 Codex 命令，请指定已安装的 CLI 路径")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        scratch = Path(scratch)
        schema = scratch / "response-schema.json"
        schema.write_text(json.dumps(response_schema(profile), ensure_ascii=False), encoding="utf-8")
        response = scratch / "response.json"
        command = [executable, "-a", "never", "exec", "-s", "read-only",
                   "--skip-git-repo-check", "--ephemeral", "--output-schema", str(schema),
                   "--output-last-message", str(response)]
        if model:
            command.extend(["--model", model])
        command.append("-")
        process = subprocess.run(command, input=prompt, cwd=scratch, capture_output=True,
                                 encoding="utf-8", errors="replace", timeout=timeout)
        if process.returncode != 0 or not response.is_file():
            diagnostic = process.stderr.casefold()
            if any(signal in diagnostic for signal in ("401 unauthorized", "please log in", "not logged in")):
                raise ValueError("Codex 评分失败，请先确认 Codex CLI 已登录")
            raise ValueError("Codex 未返回可用评分，请检查本机运行状态、模型和账户额度")
        model_result = json.loads(response.read_text(encoding="utf-8-sig"))
        evaluation = evaluate(profile, resume, model_result)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(model_result, stream, ensure_ascii=False, indent=2)
    return evaluation["total"], evaluation["conclusion"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile")
    parser.add_argument("resume_text")
    parser.add_argument("--output", required=True)
    parser.add_argument("--cli", default=os.environ.get("SCREENING_CODEX_CLI", "codex"))
    parser.add_argument("--model", default=os.environ.get("SCREENING_CODEX_MODEL"))
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        require(args.timeout > 0, "超时秒数必须为正数")
        profile = load_profile(args.profile)
        resume = Path(args.resume_text).read_text(encoding="utf-8-sig")
        total, conclusion = score(profile, resume, args.output, args.cli, args.model, args.timeout)
        print(json.dumps({"total": total, "conclusion": conclusion}, ensure_ascii=False))
    except subprocess.TimeoutExpired:
        parser.exit(1, "评分停止：Codex 请求超时\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"评分停止：{exc}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
