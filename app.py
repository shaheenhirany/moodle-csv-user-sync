# app.py
import csv
import io
import os
import re
import json
import secrets
import random
import string
import unicodedata
from datetime import datetime
from typing import List, Tuple, Optional
from threading import Thread
from queue import Queue, Empty

import requests
from flask import Flask, request, jsonify, send_file, render_template, Response, stream_with_context
from dotenv import load_dotenv

# Load .env (expects MOODLE_URL and MOODLE_TOKEN)
load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------------------
# Config / WS functions
# ---------------------------------------------------------------------
MOODLE_URL   = os.environ.get("MOODLE_URL")   # e.g. https://your-moodle/webservice/rest/server.php
MOODLE_TOKEN = os.environ.get("MOODLE_TOKEN") # token with permission for used functions

WS_GET_SITE_INFO         = "core_webservice_get_site_info"
WS_CREATE_USERS          = "core_user_create_users"
WS_GET_USERS_BY_FIELD    = "core_user_get_users_by_field"
WS_GET_USER_COURSES      = "core_enrol_get_users_courses"
WS_ENROL_MANUAL          = "enrol_manual_enrol_users"
WS_UPDATE_USERS          = "core_user_update_users"

AUTO_FIX_USERNAME_DUPLICATES = True
MOODLE_ROLE_ID = int(os.environ.get("MOODLE_ROLE_ID", "5"))  # Student

# CSV/table columns (unchanged)
FIELDNAMES = [
    "First Name","Last Name","Email Address","Username","Password",
    "Course IDs",
    "Status","Enrol Status","Suspend Status",
    "Existing First Name","Existing Last Name","Existing Username","Existing Email","Existing ID"
]

# ---------------------------------------------------------------------
# Helpers: names / csv
# ---------------------------------------------------------------------
import unicodedata
def remove_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

def ascii_slug(s: str) -> str:
    s = remove_diacritics(s).lower()
    return "".join(ch for ch in s if ch.isalnum())

def cap_words(s: str) -> str:
    s = (s or "").strip().lower()
    if not s: return ""
    return " ".join(w.capitalize() for w in s.split())

def apply_replacements(text: str) -> str:
    t = (text or "").strip()
    if t.lower().startswith(("dr. ", "dr ")): t = t.split(" ", 1)[1]
    t = t.replace("syed ", "s ").replace("Syed ", "s ")
    t = t.replace("syeda ", "s ").replace("Syeda ", "s ")
    return " ".join(t.split())

def clean_email(s: str) -> str:
    return (s or "").replace(" ", "").strip().strip("\"'").lower()

def normalize_row_keys(row: dict) -> dict:
    def norm(k: str) -> str:
        k = (k or "").replace("\ufeff", "").strip().lower()
        return "".join(ch for ch in k if ch.isalpha())  # "first_name" -> "firstname"
    m = {norm(k): k for k in row.keys()}
    fnkey = next((m[c] for c in ("firstname","givenname","forename","first") if c in m), None)
    lnkey = next((m[c] for c in ("lastname","surname","familyname","last") if c in m), None)
    emkey = next((m[c] for c in ("emailaddress","email","mail","emailid","emailaddr","eaddress") if c in m), None)
    cikey = next((m[c] for c in ("courseids","courseid","course") if c in m), None)  # optional
    if not fnkey or not lnkey or not emkey:
        found = ", ".join(row.keys())
        raise ValueError(
            "Missing required columns. Expected at least "
            "'First Name', 'Last Name', 'Email Address'. "
            f"Found: {found}"
        )
    out = {"First Name": row[fnkey], "Last Name": row[lnkey], "Email Address": row[emkey]}
    if cikey: out["Course IDs"] = str(row[cikey])
    return out

def make_usernames(rows: List[dict]) -> List[dict]:
    out, counts, used = [], {}, set()
    for r in rows:
        if not r or all((str(v or "").strip() == "") for v in r.values()):
            continue
        base_row = normalize_row_keys(r)
        first = cap_words(base_row["First Name"])
        last  = cap_words(base_row["Last Name"])
        email = clean_email(base_row["Email Address"])
        course_ids = base_row.get("Course IDs", "").strip()
        username_source = apply_replacements(f"{base_row.get('First Name','')}{base_row.get('Last Name','')}")
        base = ascii_slug(username_source) or ascii_slug(email.split("@")[0]) or "user"
        suffix = counts.get(base, 0)
        candidate = base if suffix == 0 else f"{base}{suffix}"
        while candidate in used:
            suffix += 1
            candidate = f"{base}{suffix}"
        counts[base] = suffix
        used.add(candidate)
        out.append({
            "First Name": first, "Last Name": last, "Email Address": email,
            "Username": candidate, "Password": "",
            "Course IDs": course_ids,
            "Status": "", "Enrol Status": "", "Suspend Status": "",
            "Existing First Name":"", "Existing Last Name":"", "Existing Username":"",
            "Existing Email":"", "Existing ID":""
        })
    return out

def rows_to_csv_bytes(rows: List[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    for r in rows: writer.writerow(r)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")  # BOM for Excel

# ---------------------------------------------------------------------
# Validation & Moodle helpers
# ---------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def validate_row(u: dict) -> Optional[str]:
    un = (u.get("Username") or "").strip().lower()
    fn = (u.get("First Name") or "").strip()
    ln = (u.get("Last Name") or "").strip()
    em = (u.get("Email Address") or "").strip().lower()
    if not un or not fn or not ln or not em: return "Missing required field(s)"
    if not EMAIL_RE.match(em): return "Invalid email format"
    if len(un) > 100: return "Username too long (>100)"
    if not re.fullmatch(r"[a-z0-9._-]+", un): return "Username has disallowed characters"
    return None

def strong_password() -> str:
    specials = "!@#$%^&*()-_=+[]{}"
    all_chars = string.ascii_letters + string.digits + specials
    pw = [random.choice(string.ascii_lowercase), random.choice(string.ascii_uppercase),
          random.choice(string.digits), random.choice(specials)]
    pw += [secrets.choice(all_chars) for _ in range(12)]
    random.shuffle(pw)
    return "".join(pw)

def ws_post(function: str, form: List[Tuple[str, str | int]]):
    params = {"wstoken": MOODLE_TOKEN, "wsfunction": function, "moodlewsrestformat": "json"}
    r = requests.post(MOODLE_URL, params=params, data=form, timeout=30)
    r.raise_for_status()
    return r.json()

def moodle_get_users_by_field(field: str, values: List[str]) -> List[dict]:
    form = [("field", field)] + [(f"values[{i}]", v) for i, v in enumerate(values)]
    try:
        data = ws_post(WS_GET_USERS_BY_FIELD, form)
        return data if isinstance(data, list) else []
    except requests.RequestException:
        return []

def moodle_username_exists(username: str) -> bool:
    try:
        res = moodle_get_users_by_field("username", [username])
        return any(isinstance(x, dict) and x.get("username","").lower()==username.lower() for x in res)
    except Exception:
        return True  # conservative

def next_available_username(base: str, used_local: set[str]) -> Tuple[str, Optional[str]]:
    suffix = 0
    candidate = base
    while True:
        conflict_local = candidate in used_local
        conflict_remote = moodle_username_exists(candidate)
        if not conflict_local and not conflict_remote:
            note = None if suffix == 0 else f"username adjusted to '{candidate}' (base '{base}' exists)"
            return candidate, note
        suffix += 1
        candidate = f"{base}{suffix}"

def parse_course_ids(value: str) -> List[int]:
    ids = [int(x) for x in re.findall(r"\d+", value or "")]
    seen, out = set(), []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out

def is_user_enrolled(userid: int, courseid: int) -> bool:
    try:
        data = ws_post(WS_GET_USER_COURSES, [("userid", userid)])
        if isinstance(data, list):
            return any(int(c.get("id", -1)) == int(courseid) for c in data if isinstance(c, dict))
        return False
    except Exception:
        return False

def enrol_user(userid: int, courseid: int, roleid: int = MOODLE_ROLE_ID) -> str:
    if is_user_enrolled(userid, courseid):
        return "Already enrolled"
    form = [
        ("enrolments[0][roleid]", roleid),
        ("enrolments[0][userid]", userid),
        ("enrolments[0][courseid]", courseid),
    ]
    try:
        data = ws_post(WS_ENROL_MANUAL, form)
        if isinstance(data, dict) and data.get("exception"):
            msg = data.get("message","exception"); ec = data.get("errorcode",""); dbg = data.get("debuginfo")
            return f"❌ {ec}: {msg}" + (f" — {dbg}" if dbg else "")
        return "🎓 Enrolled"
    except requests.RequestException as e:
        return f"❌ Enrol request error: {e}"

def unsuspend_user_if_needed(user_record: dict) -> str:
    try:
        suspended = user_record.get("suspended", 0)
        uid = int(user_record.get("id"))
    except Exception:
        return "Unknown"
    if str(suspended) in ("1", "true", "True"):
        form = [("users[0][id]", uid), ("users[0][suspended]", 0)]
        try:
            data = ws_post(WS_UPDATE_USERS, form)
            if isinstance(data, dict) and data.get("exception"):
                msg = data.get("message","exception"); ec = data.get("errorcode",""); dbg = data.get("debuginfo")
                return f"❌ Unsuspend failed: {ec}: {msg}" + (f" — {dbg}" if dbg else "")
            return "Unsuspended"
        except requests.RequestException as e:
            return f"❌ Unsuspend request error: {e}"
    else:
        return "Active"

def _attempt_create_single(u: dict, variant: int) -> tuple[bool, str, Optional[int]]:
    base = [
        ("users[0][username]",  u["Username"]),
        ("users[0][firstname]", u["First Name"]),
        ("users[0][lastname]",  u["Last Name"]),
        ("users[0][email]",     u["Email Address"]),
    ]
    form = list(base)
    if variant in (1, 2):
        form.append(("users[0][createpassword]", 1))
    else:
        pw = strong_password()
        u["Password"] = pw
        form.append(("users[0][password]", pw))
    if variant in (1, 3):
        form.append(("users[0][auth]", "manual"))
    try:
        data = ws_post(WS_CREATE_USERS, form)
        if isinstance(data, list) and data and isinstance(data[0], dict) and "id" in data[0]:
            suffix = " (password emailed by Moodle)" if variant in (1,2) else ""
            return True, f"✅ Created (id={data[0]['id']}) via variant {variant}{suffix}", int(data[0]["id"])
        if isinstance(data, dict) and data.get("exception"):
            msg = data.get("message","exception"); ec = data.get("errorcode",""); dbg = data.get("debuginfo")
            detail = f"❌ {ec or 'exception'}: {msg}" + (f" — {dbg}" if dbg else "")
            return False, f"{detail} [variant {variant}]", None
        return False, f"ℹ️ Unexpected: {str(data)[:200]} [variant {variant}]", None
    except requests.RequestException as e:
        return False, f"❌ Network error: {e} [variant {variant}]", None

# ---------------------------------------------------------------------
# SSE job machinery
# ---------------------------------------------------------------------
JOBS: dict[str, dict] = {}  # job_id -> {"q": Queue, "done": bool, "result_rows": list}

def sse(event: str, payload: dict) -> str:
    """Pack an SSE message."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

def _process_job(job_id: str, rows_in: List[dict]):
    q: Queue = JOBS[job_id]["q"]

    # Prepare rows (validate + auto-rename baseline)
    rows = []
    for u in rows_in:
        u = {**u}
        u["Username"] = (u.get("Username") or "").lower()
        u["Enrol Status"] = u.get("Enrol Status","")
        u["Suspend Status"] = u.get("Suspend Status","")
        u["_rename_note"] = None
        err = validate_row(u)
        if err:
            u["Status"] = f"❌ Client-side validation: {err}"
        rows.append(u)

    # Auto-fix local+remote username duplicates (simple local uniqueness now; remote check when needed)
    used_local: set[str] = set()
    if AUTO_FIX_USERNAME_DUPLICATES:
        for u in rows:
            if u.get("Status"): continue
            base = u["Username"]
            cand, note = next_available_username(base, used_local)
            used_local.add(cand)
            if cand != base:
                u["Username"] = cand
                u["_rename_note"] = note

    # Prefetch existing by email once (stream stage)
    emails_to_check = [u["Email Address"] for u in rows if not u.get("Status")]
    q.put(sse("stage", {"message": f"Checking {len(emails_to_check)} emails on Moodle…"}))
    existing_list = moodle_get_users_by_field("email", emails_to_check)
    existing_by_email = {str(x.get("email","")).lower(): x for x in existing_list if isinstance(x, dict)}

    total = len(rows)
    processed = 0

    # Process each row
    for idx, u in enumerate(rows):
        try:
            if u.get("Status"):
                # Already invalid earlier
                pass
            else:
                # Determine course ids for this user
                course_ids = parse_course_ids((u.get("Course IDs") or "").strip())
                enrol_msgs: List[str] = []
                existing = existing_by_email.get(u["Email Address"].lower())
                user_id_for_actions: Optional[int] = None

                if existing:
                    # Fill existing details + unsuspend
                    u["Existing First Name"] = existing.get("firstname","") or ""
                    u["Existing Last Name"]  = existing.get("lastname","")  or ""
                    u["Existing Username"]   = existing.get("username","")  or ""
                    u["Existing Email"]      = existing.get("email","")     or ""
                    u["Existing ID"]         = str(existing.get("id","") or "")
                    u["Status"] = "already exist"
                    u["Suspend Status"] = unsuspend_user_if_needed(existing)
                    try:
                        user_id_for_actions = int(existing.get("id"))
                    except Exception:
                        user_id_for_actions = None
                else:
                    # Create (variants)
                    created_ok, msg, created_id = False, "", None
                    for variant in (1, 2, 3, 4):
                        ok, m, uid = _attempt_create_single(u, variant)
                        created_ok, msg, created_id = ok, m, uid
                        if ok: break
                    if created_ok and u.get("_rename_note"):
                        msg = f"{msg} — {u['_rename_note']}"
                    u["Status"] = msg or "❌ Unknown outcome"
                    user_id_for_actions = created_id
                    u["Suspend Status"] = "Active" if created_ok else (u["Suspend Status"] or "")

                # Enrol
                if not course_ids:
                    enrol_msgs.append("No course id provided")
                elif user_id_for_actions is None:
                    enrol_msgs.append("❌ No user id for enrolment")
                else:
                    for cid in course_ids:
                        enrol_msgs.append(f"{cid}: {enrol_user(user_id_for_actions, cid, MOODLE_ROLE_ID)}")

                u["Enrol Status"] = " | ".join(enrol_msgs) if enrol_msgs else u.get("Enrol Status","")

        except Exception as e:
            u["Status"] = f"❌ Server error: {e}"

        finally:
            u.pop("_rename_note", None)
            # Push a row_update event so UI can update table incrementally
            q.put(sse("row_update", {"index": idx, "row": u}))

            # Progress %
            processed += 1
            pct = int(processed * 100 / max(total, 1))
            q.put(sse("progress", {"processed": processed, "total": total, "percent": pct}))

    # All done
    JOBS[job_id]["result_rows"] = rows
    JOBS[job_id]["done"] = True
    q.put(sse("done", {"percent": 100, "total": total}))
    # Close stream by sending a sentinel comment (some proxies like a final newline)
    q.put(":\n\n")

# ---------------------------------------------------------------------
# Routes: UI + basic endpoints
# ---------------------------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/ping")
def api_ping():
    if not MOODLE_URL or not MOODLE_TOKEN:
        return {"ok": False, "error": "Missing MOODLE_URL or MOODLE_TOKEN on server"}, 400
    try:
        r = requests.get(MOODLE_URL, params={
            "wstoken": MOODLE_TOKEN, "wsfunction": WS_GET_SITE_INFO, "moodlewsrestformat": "json"
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("exception"):
            return {"ok": False, "error": data.get("message"), "raw": data}, 400
        return {"ok": True, "data": data, "role_id": MOODLE_ROLE_ID}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.post("/api/preview")
def api_preview():
    try:
        if "file" not in request.files: return {"error": "Missing file"}, 400
        text = request.files["file"].read().decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        out = make_usernames(rows)
        return jsonify({"rows": out, "count": len(out)})
    except ValueError as e:
        return {"error": str(e)}, 400
    except Exception as e:
        return {"error": f"Server error: {e}"}, 500

# -------- Streaming job API --------
import uuid

@app.post("/api/moodle/start")
def api_moodle_start():
    """Start a streaming job; returns job_id."""
    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    if not isinstance(rows, list) or not rows:
        return {"error": "Invalid or empty 'rows'"}, 400
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"q": Queue(), "done": False, "result_rows": []}
    t = Thread(target=_process_job, args=(job_id, rows), daemon=True)
    t.start()
    return {"job_id": job_id}

@app.get("/api/moodle/stream/<job_id>")
def api_moodle_stream(job_id):
    """SSE stream for a given job_id."""
    if job_id not in JOBS:
        return {"error": "Unknown job"}, 404
    q: Queue = JOBS[job_id]["q"]

    @stream_with_context
    def gen():
        # initial ping & retry hint
        yield "retry: 1500\n\n"
        yield sse("hello", {"job_id": job_id})
        while True:
            try:
                msg = q.get(timeout=25)
                yield msg
                # stop if job is done and queue drained
                if JOBS[job_id]["done"] and q.empty():
                    break
            except Empty:
                # keep-alive comment
                yield ":\n\n"
        # optional: cleanup
        # del JOBS[job_id]  # uncomment if you don't need /result after done

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",  # for nginx
        "Connection": "keep-alive",
    }
    return Response(gen(), headers=headers)

@app.get("/api/moodle/result/<job_id>")
def api_moodle_result(job_id):
    """Fetch final rows for a job (after done)."""
    if job_id not in JOBS:
        return {"error": "Unknown job"}, 404
    return {"rows": JOBS[job_id].get("result_rows", [])}

# Non-stream (download) remains the same
@app.post("/api/download")
def api_download():
    try:
        data = request.get_json(silent=True) or {}
        rows = data.get("rows", [])
        if not isinstance(rows, list) or not rows:
            return {"error": "Invalid or empty 'rows'"}, 400
        csv_bytes = rows_to_csv_bytes(rows)
        return send_file(io.BytesIO(csv_bytes), mimetype="text/csv; charset=utf-8",
                         as_attachment=True,
                         download_name=f"usernames_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv")
    except Exception as e:
        return {"error": f"Server error: {e}"}, 500

# ---------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # Flask dev server is fine for SSE demos; behind nginx/Apache, keep buffering off for the SSE route.
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
