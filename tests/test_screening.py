from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rubric import evaluate, load_profile, route_role
from score_codex import score
from workflow import (SHANGHAI, acknowledge, authorize, in_window, ledger, load_route, preview,
                      queue, record, register, release_preview, reserve)

P001 = ROOT / "examples/P001.json"
SALES = ROOT / "examples/DEMO-SALES.json"
DELIVERY = ROOT / "examples/delivery.demo.json"
SALES_TEXT = "在示例公司做电话销售。日均外呼60通。整理客户需求并二次跟进。每月独立转化八位客户。"


def minimal_pdf(note):
    header = b"%PDF-1.4\n"
    content = header + b"%" + note.encode("ascii") + b"\n"
    offsets = [0]
    for i, obj in enumerate([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>"
    ], 1):
        offsets.append(len(content))
        content += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    position = len(content)
    content += b"xref\n0 4\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        content += f"{offset:010d} 00000 n \n".encode()
    return content + f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{position}\n%%EOF\n".encode()


def sales_result():
    return {
        "scores": {
            "outreach": {"points": 30, "evidence": "日均外呼60通"},
            "followup": {"points": 30, "evidence": "整理客户需求并二次跟进"},
            "results": {"points": 25, "evidence": "每月独立转化八位客户"},
        },
        "checks": {"outbound": {"status": "met", "evidence": "在示例公司做电话销售"}},
        "comments": {"推荐理由": "有可量化的电话销售经历", "匹配经历": "有需求整理和复访经验",
                     "待核实": "班次接受度待初面核实"},
    }


class ScreeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.pdf = self.work / "fake.pdf"
        self.pdf.write_bytes(minimal_pdf("fictional version 1"))
        self.txt = self.work / "fake.txt"
        self.txt.write_text(SALES_TEXT, encoding="utf-8")
        self.sales = load_profile(SALES)
        self.delivery = load_route(DELIVERY, self.sales, True)

    def command(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/screen.py"), *map(str, args)],
            encoding="utf-8", capture_output=True)
        self.assertEqual(result.returncode, expect, result.stderr)
        return result.stdout

    def test_sales_through_public_cli(self):
        demo = ("--work", self.work, "--demo")
        matched = json.loads(self.command("--demo", "route", SALES, P001, "--signal", "电话销售"))
        self.assertEqual(matched["role"], "DEMO-SALES")
        first = json.loads(self.command(*demo, "register", SALES, "001", "候选人甲", "示例公司",
                                        self.pdf, self.txt, "--source", "demo-intake"))
        tasks = json.loads(self.command(*demo, "queue", SALES))
        self.assertEqual(len(tasks["scoring"]), 1)
        task = tasks["scoring"][0]
        self.assertEqual(task["revision"], first["revision"])
        prompt = self.command("--demo", "prompt", SALES, task["resume_text"])
        self.assertIn("日均外呼60通", prompt)
        result = self.work / "codex-result.json"
        result.write_text(json.dumps(sales_result(), ensure_ascii=False), encoding="utf-8")
        scored = json.loads(self.command(*demo, "record", SALES, "001", 1, result))
        self.assertEqual((scored["conclusion"], scored["total"]), ("推荐面试", 85))
        batch = json.loads(self.command(*demo, "preview", SALES, DELIVERY))
        self.assertEqual(batch["recipients"][0]["label"], "示例面试官")
        with ZipFile(batch["attachment"]) as archive:
            self.assertEqual(archive.namelist(), ["001_候选人甲_示例公司.pdf"])
            self.assertEqual(archive.read(archive.namelist()[0]), self.pdf.read_bytes())
        message = Path(batch["message"]).read_text(encoding="utf-8")
        self.assertIn("需求整理和复访", message)
        self.assertNotIn("总分", message)
        self.assertNotIn("学历年龄", message)
        self.command(*demo, "authorize", SALES, DELIVERY, batch["batch"], batch["approval_code"],
                     "--confirmation", "mock", expect=2)
        self.command("prompt", SALES, self.txt, expect=1)

    def test_legacy_p001_decisions_and_summary(self):
        profile = load_profile(P001)
        text = "最近一段工作至今。负责订单和支付改造。带过六人小组。本科起止可算出四年。"
        result = {
            "scores": {key: {"points": points, "evidence": "负责订单和支付改造" if points else ""}
                       for key, points in zip(profile["dimensions"], (9, 3, 3, 3, 1, 6, 15, 5, 15, 10))},
            "checks": {key: {"status": "unknown", "evidence": ""} for key in profile["checks"]},
            "comments": {"技能知识": "有订单改造经验", "过往履历匹配度": "带过六人小组",
                         "学历年龄": "本科四年，简历未写年龄"},
        }
        base = json.dumps(result)
        cases = [
            ("推荐面试", None, None),
            ("待定（履历未更新）", "freshness", "met"),
            ("不合适", "x3", "met"),
            ("待定", "x1", "suspected"),
            ("待定", "x4", "met"),
            ("不合适（本科5年疑专升本）", "g2_five_years", "met"),
        ]
        for outcome, check, status in cases:
            with self.subTest(outcome=outcome, check=check):
                candidate_result = json.loads(base)
                if check:
                    candidate_result["checks"][check] = {"status": status, "evidence": "负责订单和支付改造"}
                self.assertEqual(evaluate(profile, text, candidate_result)["conclusion"], outcome)
        for key in ("modernization", "consistency"):
            result["scores"][key] = {"points": 0, "evidence": ""}
        result["scores"]["company"]["points"] = 12
        scored = evaluate(profile, text, result)
        self.assertEqual((scored["total"], scored["conclusion"]), (55, "不合适"))
        self.assertIn("均为 0", scored["reason"])
        original = json.loads(base)
        original["scores"]["company"]["points"] = 0
        original["scores"]["company"]["evidence"] = ""
        self.assertEqual(evaluate(profile, text, original)["total"], 55)
        self.assertEqual(evaluate(profile, text, original)["conclusion"], "推荐面试")
        original["scores"]["industry"]["points"] -= 1
        self.assertEqual(evaluate(profile, text, original)["total"], 54)
        self.assertEqual(evaluate(profile, text, original)["conclusion"], "不合适")
        self.txt.write_text(text, encoding="utf-8")
        delivery = dict(self.delivery, role="P001", first_sequence=6)
        with ledger(self.work, demo=True) as (db, ws):
            register(db, ws, profile, "001", "候选人甲", "示例公司", self.pdf, self.txt, "demo")
            record(db, profile, "001", 1, json.loads(base))
            batch = preview(db, ws, profile, delivery)
        message = Path(batch["message"]).read_text(encoding="utf-8")
        self.assertIn("### No.006 候选人甲", message)
        for heading in ("技能知识", "过往履历匹配度", "学历年龄"):
            self.assertIn(f"**{heading}：**", message)
        self.assertNotIn("总分", message)

    def test_role_conflict_duplicate_and_update(self):
        p001 = load_profile(P001)
        self.assertIsNone(route_role([p001, self.sales], None, ["P001", "DEMO-SALES"]))
        self.assertEqual(route_role([p001, self.sales], "P001", ["电话销售"]), "P001")
        with ledger(self.work, demo=True) as (db, ws):
            def submit(profile, candidate):
                return register(db, ws, profile, candidate, "候选人甲", "示例公司",
                                self.pdf, self.txt, "demo")
            self.assertEqual(submit(self.sales, "001")["status"], "registered")
            self.assertEqual(submit(self.sales, "001")["status"], "duplicate")
            self.assertEqual(submit(self.sales, "002")["status"], "id_conflict")
            self.assertEqual(submit(p001, "001")["status"], "registered")
            record(db, self.sales, "001", 1, sales_result())
            self.pdf.write_bytes(minimal_pdf("fictional version 2"))
            self.assertEqual(submit(self.sales, "001")["revision"], 2)
            self.assertEqual(preview(db, ws, self.sales, self.delivery)["status"], "empty")
            self.assertEqual(queue(db, self.sales)["scoring"][0]["revision"], 2)
            with self.assertRaises(ValueError):
                record(db, self.sales, "001", 1, sales_result())

    def test_unknown_and_invalid_evidence(self):
        result = sales_result()
        result["checks"]["outbound"] = {"status": "unknown", "evidence": ""}
        self.assertEqual(evaluate(self.sales, SALES_TEXT, result)["conclusion"], "推荐面试")
        result["scores"]["results"]["evidence"] = "不存在的证明"
        with self.assertRaisesRegex(ValueError, "找不到"):
            evaluate(self.sales, SALES_TEXT, result)
        result = sales_result()
        result["checks"]["outbound"] = {"status": "unmet", "evidence": ""}
        with self.assertRaisesRegex(ValueError, "缺少证据"):
            evaluate(self.sales, SALES_TEXT, result)

    def test_partial_delivery_and_receipt_reconciliation(self):
        person = "demo-only"
        with ledger(self.work, demo=True) as (db, ws):
            register(db, ws, self.sales, "001", "候选人甲", "示例公司", self.pdf, self.txt, "demo")
            record(db, self.sales, "001", 1, sales_result())
            batch = preview(db, ws, self.sales, self.delivery)
            batch_id = batch["batch"]

            def take(part, route=self.delivery):
                return reserve(db, self.sales, route, batch_id, person, part, "simulated urgent request")

            with self.assertRaisesRegex(ValueError, "预览"):
                take("message")
            authorize(db, self.sales, self.delivery, batch_id, batch["approval_code"], "fictional approval")
            altered = dict(self.delivery, recipients=[{"id": "other", "label": "示例", "query": "示例"}])
            with self.assertRaisesRegex(ValueError, "面试官配置不同"):
                take("message", altered)
            with self.assertRaisesRegex(ValueError, "评价消息"):
                take("attachment")
            first = take("message")
            self.assertEqual(take("message")["status"], "sending")
            summary_status = acknowledge(db, batch_id, person, "message", first["attempt"], "sent", "mock1")
            self.assertFalse(summary_status["delivered"])
            attachment = take("attachment")
            self.assertEqual(take("attachment")["status"], "sending")
            acknowledge(db, batch_id, person, "attachment", attachment["attempt"], "failed", "mock2")
            self.assertEqual(take("message")["status"], "sent")
            retry = take("attachment")
            self.assertNotEqual(retry["attempt"], attachment["attempt"])
            with self.assertRaises(ValueError):
                acknowledge(db, batch_id, person, "attachment", attachment["attempt"], "sent", "stale")
            status = acknowledge(db, batch_id, person, "attachment", retry["attempt"], "sent", "mock3")
            self.assertTrue(status["delivered"])
            self.assertEqual(queue(db, self.sales)["batches"], [])
            self.assertEqual(preview(db, ws, self.sales, self.delivery)["status"], "empty")

    def test_release_before_send_and_verified_batch(self):
        with ledger(self.work, demo=True) as (db, ws):
            register(db, ws, self.sales, "001", "候选人甲", "示例公司", self.pdf, self.txt, "demo")
            record(db, self.sales, "001", 1, sales_result())
            batch = preview(db, ws, self.sales, self.delivery)
            Path(batch["message"]).write_text("changed preview", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "批次文件已变化"):
                authorize(db, self.sales, self.delivery, batch["batch"], batch["approval_code"], "demo")
            release_preview(db, batch["batch"])
            revised = preview(db, ws, self.sales, self.delivery)
            self.assertNotEqual(revised["batch"], batch["batch"])
            self.assertNotEqual(revised["approval_code"], batch["approval_code"])

    def test_codex_adapter_uses_structured_response_and_checks_evidence(self):
        result = self.work / "score.json"

        def fake_codex(command, *, input, cwd, **kwargs):
            self.assertIn("read-only", command)
            self.assertIn("--ephemeral", command)
            self.assertIn("日均外呼60通", input)
            schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text(encoding="utf-8"))
            self.assertEqual(set(schema["properties"]), {"scores", "checks", "comments"})
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text(json.dumps(sales_result(), ensure_ascii=False), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("score_codex.subprocess.run", side_effect=fake_codex):
            total, conclusion = score(self.sales, SALES_TEXT, result, sys.executable, None, 30)
        self.assertEqual((total, conclusion), (85, "推荐面试"))
        self.assertEqual(json.loads(result.read_text(encoding="utf-8")), sales_result())

    def test_send_windows(self):
        schedule = self.delivery["schedule"]
        self.assertTrue(in_window(schedule, dt.datetime(2026, 11, 19, 17, 40, tzinfo=SHANGHAI)))
        self.assertFalse(in_window(schedule, dt.datetime(2026, 11, 19, 10, 0, tzinfo=SHANGHAI)))
        self.assertFalse(in_window(schedule, dt.datetime(2026, 11, 21, 17, 30, tzinfo=SHANGHAI)))


if __name__ == "__main__":
    unittest.main()
