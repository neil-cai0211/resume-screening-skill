"""Private intake, preview, and per-recipient delivery state."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from rubric import ROOT, PROFILE_ID, canonical, digest, evaluate, read_json, require, safe_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    role TEXT, candidate TEXT, revision INTEGER, sha TEXT, source TEXT,
    name TEXT, employer TEXT, directory TEXT, evaluation TEXT, batch TEXT,
    PRIMARY KEY (role, candidate, revision), UNIQUE (role, sha)
);
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY, role TEXT, policy TEXT, directory TEXT, manifest TEXT
);
CREATE TABLE IF NOT EXISTS authorizations (
    role TEXT PRIMARY KEY, policy TEXT, batch TEXT, record TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
    batch TEXT, recipient TEXT, part TEXT, state TEXT, attempt TEXT, receipt TEXT, manual_confirmation TEXT,
    PRIMARY KEY (batch, recipient, part)
);
CREATE TABLE IF NOT EXISTS numbering (role TEXT PRIMARY KEY, next INTEGER);
"""
SHANGHAI = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")


@contextmanager
def ledger(path, demo=False):
    work = Path(path).resolve()
    require(not work.is_relative_to(ROOT), "工作目录必须在发布仓库外")
    workspace = work / ("demo" if demo else "live")
    require(not workspace.resolve().is_relative_to(ROOT), "工作目录必须在发布仓库外")
    workspace.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(workspace / "screening.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        yield db, workspace
        db.commit()
    finally:
        db.close()


def role_allowed(profile, demo):
    require(demo or profile["status"] == "approved", "正式筛选须使用已确认的岗位版本")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_part(value):
    safe_text(value, "名称")
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip(" .")
    require(bool(safe), "文件名缺少有效字符")
    return safe[:70]


def register(db, workspace, profile, candidate, name, employer, pdf, resume_text, source):
    require(PROFILE_ID.fullmatch(candidate), "候选人编号无效")
    resume = Path(resume_text).read_text(encoding="utf-8-sig")
    safe_text(resume, "脱敏简历")
    raw = Path(pdf).read_bytes()
    require(raw.startswith(b"%PDF-"), "推荐包只接收 PDF，请先转换并核对")
    sha = hashlib.sha256(raw).hexdigest()
    role = profile["id"]
    previous = db.execute("SELECT candidate,revision,directory FROM submissions WHERE role=? AND sha=?",
                          (role, sha)).fetchone()
    if previous:
        return {"status": "duplicate" if previous["candidate"] == candidate else "id_conflict",
                "candidate": previous["candidate"], "revision": previous["revision"],
                "resume_text": str(Path(previous["directory"]) / "resume.txt")}
    revision = db.execute(
        "SELECT COALESCE(MAX(revision),0)+1 FROM submissions WHERE role=? AND candidate=?",
        (role, candidate)).fetchone()[0]
    directory = workspace / "submissions" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    (directory / "resume.pdf").write_bytes(raw)
    (directory / "resume.txt").write_text(resume, encoding="utf-8")
    db.execute("INSERT INTO submissions VALUES (?,?,?,?,?,?,?,?,NULL,NULL)",
               (role, candidate, revision, sha, source, file_part(name), file_part(employer), str(directory)))
    return {"status": "registered", "candidate": candidate, "revision": revision,
            "resume_text": str(directory / "resume.txt")}


def get_current(db, role, candidate, revision):
    submission = db.execute(
        "SELECT * FROM submissions WHERE role=? AND candidate=? ORDER BY revision DESC LIMIT 1",
        (role, candidate)).fetchone()
    require(submission is not None and submission["revision"] == revision, "候选人编号或简历版本已变化")
    return submission


def record(db, profile, candidate, revision, result):
    row = get_current(db, profile["id"], candidate, revision)
    require(row["batch"] is None, "该版本已打包，评分记录随批次冻结")
    resume = (Path(row["directory"]) / "resume.txt").read_text(encoding="utf-8")
    result = evaluate(profile, resume, result)
    db.execute("UPDATE submissions SET evaluation=? WHERE role=? AND candidate=? AND revision=?",
               (canonical(result), profile["id"], candidate, revision))
    return result


def load_route(path, profile, demo):
    route = read_json(path)
    require(isinstance(route, dict) and route.get("role") == profile["id"]
            and route.get("channel") == "dingtalk-dm", "岗位和钉钉单聊配置不匹配")
    require(demo or not Path(path).resolve().is_relative_to(ROOT), "发送配置只能放在私有工作区")
    recipients = route.get("recipients")
    require(isinstance(recipients, list) and recipients, "至少配置一位面试官")
    for recipient in recipients:
        require(isinstance(recipient, dict) and all(isinstance(recipient.get(key), str)
                and recipient[key].strip() for key in ("id", "label", "query")), "面试官身份配置不完整")
    require(len({recipient["id"] for recipient in recipients}) == len(recipients), "面试官重复")
    route["recipients"] = sorted(recipients, key=lambda recipient: recipient["id"])
    schedule = route.get("schedule", {})
    require(schedule.get("timezone") == "Asia/Shanghai"
            and isinstance(schedule.get("at"), str)
            and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", schedule["at"])
            and type(schedule.get("window_minutes")) is int
            and 0 <= schedule["window_minutes"] <= 60
            and isinstance(schedule.get("weekdays"), list) and schedule["weekdays"]
            and all(type(day) is int and 1 <= day <= 7 for day in schedule["weekdays"]),
            "发送时段无效")
    require(type(route.get("first_sequence", 1)) is int and route.get("first_sequence", 1) >= 1,
            "推荐起始序号无效")
    return route


def policy_for(profile, route):
    return digest({"rubric": profile["fingerprint"], "route": route})


def render(profile, candidates, date, archive):
    result = [
        f"## {profile['id']} {profile['title']} 简历推荐（{date.isoformat()}）",
        f"本轮推荐 {len(candidates)} 人，简历见附件压缩包 {archive}。",
    ]
    for candidate in candidates:
        evaluation = candidate["evaluation"]
        result.append(f"### No.{candidate['sequence']} {candidate['name']}")
        for field in profile["output"]["fields"]:
            result.append(f"**{field}：** {evaluation['comments'][field]}")
        if profile["output"]["include_total"]:
            result.append(f"**总分：** {evaluation['total']}")
    return "\n\n".join(result) + "\n"


def preview(db, workspace, profile, route):
    role = profile["id"]
    rows = db.execute("""
        SELECT s.* FROM submissions s
        WHERE s.role=? AND s.batch IS NULL AND s.evaluation IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM submissions n WHERE n.role=s.role
                          AND n.candidate=s.candidate AND n.revision>s.revision)
        ORDER BY s.rowid
        """, (role,)).fetchall()
    next_row = db.execute("SELECT next FROM numbering WHERE role=?", (role,)).fetchone()
    sequence = next_row[0] if next_row else route.get("first_sequence", 1)
    candidates = []
    for row in rows:
        evaluation = json.loads(row["evaluation"])
        if (evaluation["conclusion"] == "推荐面试"
                and evaluation["rubric_fingerprint"] == profile["fingerprint"]):
            number = f"{sequence:03}"
            candidates.append({"candidate": row["candidate"], "revision": row["revision"],
                               "name": row["name"], "sequence": number, "evaluation": evaluation,
                               "filename": f"{number}_{row['name']}_{row['employer']}.pdf",
                               "pdf": str(Path(row["directory"]) / "resume.pdf"), "sha": row["sha"]})
            sequence += 1
    if not candidates:
        return {"status": "empty"}
    date = dt.datetime.now(SHANGHAI).date()
    batch = uuid.uuid4().hex
    directory = workspace / "batches" / batch
    directory.mkdir(parents=True)
    db.execute("DELETE FROM authorizations WHERE role=? AND policy!=?", (role, policy_for(profile, route)))
    filename = f"{role}_简历推荐_{date:%Y%m%d}.zip"
    archive = directory / filename
    message = directory / "message.md"
    message.write_text(render(profile, candidates, date, filename), encoding="utf-8")
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for candidate in candidates:
            payload = Path(candidate["pdf"]).read_bytes()
            require(hashlib.sha256(payload).hexdigest() == candidate["sha"], "简历 PDF 已变化")
            bundle.writestr(candidate["filename"], payload)
            db.execute("UPDATE submissions SET batch=? WHERE role=? AND candidate=? AND revision=?",
                       (batch, role, candidate["candidate"], candidate["revision"]))
    manifest = {"batch": batch, "role": role, "version": profile["version"],
                "policy": policy_for(profile, route), "recipients": route["recipients"],
                "files": {"message": {"name": message.name, "sha256": file_sha(message)},
                          "attachment": {"name": archive.name, "sha256": file_sha(archive)}},
                "candidates": [{key: row[key] for key in ("candidate", "revision", "sequence", "filename")}
                               for row in candidates]}
    db.execute("INSERT INTO batches VALUES (?,?,?,?,?)",
               (batch, role, manifest["policy"], str(directory), canonical(manifest)))
    db.execute("INSERT INTO numbering VALUES (?,?) ON CONFLICT(role) DO UPDATE SET next=excluded.next",
               (role, sequence))
    db.executemany("INSERT INTO deliveries VALUES (?,?,?,'pending',NULL,NULL,NULL)",
                   [(batch, recipient["id"], part) for recipient in route["recipients"]
                    for part in ("message", "attachment")])
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(canonical(manifest), encoding="utf-8")
    return {"status": "preview", "manifest": str(manifest_path), "batch": batch,
            "approval_code": digest(manifest), "message": str(message), "attachment": str(archive),
            "recipients": [{"label": person["label"], "query": person["query"]}
                           for person in route["recipients"]]}


def verified_batch(db, profile, route, batch):
    row = db.execute("SELECT rowid AS ordinal,* FROM batches WHERE id=?", (batch,)).fetchone()
    require(row is not None and row["policy"] == policy_for(profile, route),
            "批次与当前标准或面试官配置不同，请重新预览")
    require(db.execute("SELECT 1 FROM deliveries WHERE batch=? AND state!='cancelled'", (batch,)).fetchone(),
            "该预览已释放")
    manifest = json.loads(row["manifest"])
    for artifact in manifest["files"].values():
        require(file_sha(Path(row["directory"]) / artifact["name"]) == artifact["sha256"],
                "批次文件已变化，请停止发送")
    return row, manifest


def authorize(db, profile, route, batch, code, approval_record):
    _, manifest = verified_batch(db, profile, route, batch)
    require(code == digest(manifest) and bool(approval_record.strip()), "需要该批次的预览校验码和确认记录")
    for member in manifest["candidates"]:
        get_current(db, profile["id"], member["candidate"], member["revision"])
    db.execute("""
        INSERT INTO authorizations VALUES (?,?,?,?)
        ON CONFLICT(role) DO UPDATE SET policy=excluded.policy,batch=excluded.batch,record=excluded.record
        """, (manifest["role"], manifest["policy"], batch, approval_record))
    return {"status": "authorized", "batch": batch, "policy": manifest["policy"]}


def in_window(schedule, now):
    expected = dt.datetime.combine(now.date(), dt.time.fromisoformat(schedule["at"]), tzinfo=now.tzinfo)
    return now.isoweekday() in schedule["weekdays"] and (
        abs((now - expected).total_seconds()) <= 60 * schedule["window_minutes"])


def reserve(db, profile, route, batch, recipient, part, manual_record):
    row, manifest = verified_batch(db, profile, route, batch)
    authorized = db.execute("""
        SELECT b.rowid FROM authorizations a JOIN batches b ON b.id=a.batch
        WHERE a.role=? AND a.policy=?
        """, (profile["id"], row["policy"])).fetchone()
    require(authorized is not None and row["ordinal"] >= authorized[0],
            "先预览并确认此版本与收件人；更早批次须重新预览")
    require(bool(manual_record and manual_record.strip()) or
            in_window(route["schedule"], dt.datetime.now(SHANGHAI)), "当前不在授权发送时段")
    delivery = db.execute("SELECT * FROM deliveries WHERE batch=? AND recipient=? AND part=?",
                          (batch, recipient, part)).fetchone()
    require(delivery is not None, "收件人和材料类型须与预览批次一致")
    if delivery["state"] not in {"pending", "failed"}:
        return {"status": delivery["state"]}
    if part == "attachment":
        message = db.execute("SELECT state FROM deliveries WHERE batch=? AND recipient=? AND part='message'",
                             (batch, recipient)).fetchone()
        require(message["state"] == "sent", "先确认同一收件人的评价消息已送达")
    started = db.execute("SELECT 1 FROM deliveries WHERE batch=? AND state IN ('sending','sent')", (batch,)).fetchone()
    if not started:
        for member in manifest["candidates"]:
            get_current(db, profile["id"], member["candidate"], member["revision"])
    attempt = uuid.uuid4().hex
    db.execute("UPDATE deliveries SET state='sending',attempt=?,receipt=NULL,manual_confirmation=? WHERE batch=? AND recipient=? AND part=?",
               (attempt, manual_record, batch, recipient, part))
    artifact = manifest["files"][part]
    person = next(person for person in manifest["recipients"] if person["id"] == recipient)
    return {"status": "ready", "attempt": attempt, "target": person, "channel": route["channel"],
            "file": str(Path(row["directory"]) / artifact["name"]), "sha256": artifact["sha256"]}


def acknowledge(db, batch, recipient, part, attempt, status, receipt):
    require(status in {"sent", "failed"} and bool(receipt.strip()), "须提供明确送达或未送达的回执")
    cursor = db.execute("""
        UPDATE deliveries SET state=?,receipt=?
        WHERE batch=? AND recipient=? AND part=? AND attempt=? AND state='sending'
        """, (status, receipt, batch, recipient, part, attempt))
    require(cursor.rowcount == 1, "该发送操作已处理或回执不对应")
    return delivery_status(db, batch)


def delivery_status(db, batch):
    parts = [dict(row) for row in db.execute(
        "SELECT recipient,part,state,attempt,receipt,manual_confirmation FROM deliveries WHERE batch=? ORDER BY recipient,part",
        (batch,))]
    require(parts, "未找到批次")
    row = db.execute("SELECT directory,manifest FROM batches WHERE id=?", (batch,)).fetchone()
    manifest = json.loads(row["manifest"])
    return {"batch": batch, "role": manifest["role"], "version": manifest["version"],
            "approval_code": digest(manifest), "directory": row["directory"],
            "delivered": all(row["state"] == "sent" for row in parts), "parts": parts}


def release_preview(db, batch):
    status = delivery_status(db, batch)
    require(all(item['state'] in {'pending', 'failed'} for item in status['parts']),
            "已有已送达、正在发送或已释放的内容，先核对回执")
    db.execute("UPDATE deliveries SET state='cancelled' WHERE batch=?", (batch,))
    db.execute("UPDATE submissions SET batch=NULL WHERE batch=?", (batch,))
    db.execute("DELETE FROM authorizations WHERE batch=?", (batch,))
    return {"status": "released", "batch": batch}

def queue(db, profile):
    role = profile["id"]
    rows = db.execute("""
        SELECT s.* FROM submissions s
        WHERE s.role=? AND s.batch IS NULL
          AND NOT EXISTS (SELECT 1 FROM submissions n WHERE n.role=s.role
                          AND n.candidate=s.candidate AND n.revision>s.revision)
        ORDER BY s.rowid
        """, (role,)).fetchall()
    scoring = []
    for row in rows:
        if row["evaluation"] is None or json.loads(row["evaluation"])["rubric_fingerprint"] != profile["fingerprint"]:
            scoring.append({"candidate": row["candidate"], "revision": row["revision"],
                            "job_key": digest([role, row["candidate"], row["revision"], profile["fingerprint"]])[:32],
                            "resume_text": str(Path(row["directory"]) / "resume.txt")})
    batches = [row[0] for row in db.execute("""
        SELECT DISTINCT b.id FROM batches b JOIN deliveries d ON b.id=d.batch
        WHERE b.role=? AND d.state IN ('pending','failed','sending') ORDER BY b.rowid
        """, (role,))]
    return {"scoring": scoring, "batches": batches}