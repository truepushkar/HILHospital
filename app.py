import json
import html
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlencode, urlparse
import concurrent.futures
import time
import threading

import requests
from bs4 import BeautifulSoup
import os

from flask import Flask, request, jsonify, session, render_template, Response, stream_with_context

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

BASE = "https://hrfjne8ujy3mixh-hilapex.adb.ap-mumbai-1.oraclecloudapps.com"
LOGIN_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/login"
HOME_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/home"
MAIN_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/main-page"
NEW_REG_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/new-registration"
LOGIN_ACCEPT_URL = f"{BASE}/ords/wwv_flow.accept"
AJAX_URL = f"{BASE}/ords/wwv_flow.ajax"

IST = timezone(timedelta(hours=5, minutes=30))

SLOT_TIMES = {
    'morning':   {'hour': 7,  'minute': 29, 'second': 56, 'label': '7:30 AM (Morning)'},
    'afternoon': {'hour': 13, 'minute': 59, 'second': 56, 'label': '2:00 PM (Afternoon)'},
}

# In-memory session store (keyed by Flask session id)
_sessions: dict = {}
_lock = threading.Lock()

# Server-side schedule store
_schedules: dict = {}
_schedule_lock = threading.Lock()
_schedule_counter = 0


def get_store(sid: str) -> dict:
    with _lock:
        if sid not in _sessions:
            _sessions[sid] = {
                "http_session": requests.Session(),
                "meta": None,
                "dependents": [],
                "main_html": None,
                "newreg_html": None,
                "doctors": [],
                "final_responses": [],
            }
        return _sessions[sid]


def browser_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
        "Referer": BASE + "/",
        "Origin": BASE,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }


def page_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
        "Referer": BASE + "/",
        "Upgrade-Insecure-Requests": "1",
    }


def get_value_from_soup(soup, selector, attr="value"):
    tag = soup.select_one(selector)
    return tag.get(attr) if tag else None


def get_apex_session_data(http_session: requests.Session) -> dict:
    response = http_session.get(LOGIN_URL, headers={"User-Agent": browser_headers()["User-Agent"]})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return {
        "p_instance": get_value_from_soup(soup, "#pInstance"),
        "p_page_submission_id": get_value_from_soup(soup, "#pPageSubmissionId"),
        "pSalt": get_value_from_soup(soup, "#pSalt"),
        "pPageItemsProtected": get_value_from_soup(soup, "#pPageItemsProtected"),
    }


def login_apex(http_session: requests.Session, username: str, password: str, meta: dict) -> requests.Response:
    login_payload = {
        "pageItems": {
            "itemsToSubmit": [
                {"n": "P9999_USERNAME", "v": username},
                {"n": "P9999_PASSWORD", "v": password},
            ],
            "protected": meta["pPageItemsProtected"],
            "rowVersion": "",
            "formRegionChecksums": [],
        },
        "salt": meta["pSalt"],
    }
    data = {
        "p_flow_id": "980",
        "p_flow_step_id": "9999",
        "p_instance": meta["p_instance"],
        "p_debug": "",
        "p_request": "LOGIN",
        "p_reload_on_submit": "S",
        "p_page_submission_id": meta["p_page_submission_id"],
        "p_json": json.dumps(login_payload, separators=(",", ":")),
    }
    return http_session.post(
        f"{LOGIN_ACCEPT_URL}?p_context=hospital-registration-system-renukoot/login/{meta['p_instance']}",
        headers=browser_headers(),
        data=data,
    )


def extract_dependents(html_text: str):
    soup = BeautifulSoup(html_text, "html.parser")
    results = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "new-registration" not in href:
            continue
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        item = {
            "p4_mr_number": params.get("p4_mr_number", [""])[0],
            "p4_mr_name": params.get("p4_mr_name", [""])[0],
            "p4_mr_number_display": params.get("p4_mr_number_display", [""])[0],
            "p4_mr_name_display": params.get("p4_mr_name_display", [""])[0],
            "session": params.get("session", [""])[0],
            "cs": params.get("cs", [""])[0],
        }
        item["label"] = f'{item["p4_mr_name_display"]} ({item["p4_mr_number_display"]})'
        results.append(item)
    return results


def fetch_main_page(http_session: requests.Session, p_instance: str) -> str:
    resp = http_session.get(MAIN_URL, params={"session": p_instance}, headers=page_headers())
    resp.raise_for_status()
    return resp.text


def extract_new_registration_page(http_session: requests.Session, p_instance: str, dependent: dict) -> str:
    params = {
        "p4_mr_number": dependent["p4_mr_number"],
        "p4_mr_name": dependent["p4_mr_name"],
        "p4_mr_number_display": dependent["p4_mr_number_display"],
        "p4_mr_name_display": dependent["p4_mr_name_display"],
        "session": p_instance,
        "cs": dependent["cs"],
    }
    resp = http_session.get(NEW_REG_URL, params=params, headers=page_headers())
    resp.raise_for_status()
    return resp.text


def extract_opd_status(html_content):
    soup = BeautifulSoup(html_content, "html.parser")

    results = []

    # Find all OPD rows
    rows = soup.select("table.a-IRR-table tr td div")

    for row in rows:
        text = row.get_text(" ", strip=True)

        # Skip irrelevant rows
        if "Patient No" not in text:
            continue

        # Extract key/value pairs
        pattern = (
            r"Patient No\s*-->\s*(.*?),\s*"
            r"Patient Name\s*-->\s*(.*?),\s*"
            r"Token No\s*-->\s*(.*?),\s*"
            r"Doctor Name\s*-->\s*(.*?),\s*"
            r"Visit No\s*-->\s*(.*?),\s*"
            r"Employee Code\s*-->\s*(.*)"
        )

        match = re.search(pattern, text)

        if match:
            opd_data = {
                "patient_no": match.group(1).strip(),
                "patient_name": match.group(2).strip(),
                "token_no": match.group(3).strip(),
                "doctor_name": match.group(4).strip(),
                "visit_no": match.group(5).strip(),
                "employee_code": match.group(6).strip()
            }

            results.append(opd_data)

    return results


def extract_departments(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    select = soup.select_one("#P4_DEPARTMENTS")
    if not select:
        return [
            ("A003", "Anaesthesia"), ("C004", "Cardiology"), ("C008", "Chest"),
            ("D001", "Dental"), ("E004", "ENT"), ("G001", "Gastroenterology"),
            ("M002", "General Medicine"), ("G002", "General Surgery"),
            ("G003", "Gynaecology & Obstetrics"), ("N002", "Nephrology"),
            ("N004", "Neurology"), ("OH01", "Occupational Health"),
            ("O003", "Ophthalmology"), ("O004", "Orthopaedic"),
            ("P006", "Paediatrics"), ("P004", "Psychiatry"),
            ("R002", "Radiology"), ("P009", "Visitors Ophthalmology"),
        ]
    out = []
    for opt in select.find_all("option"):
        value = (opt.get("value") or "").strip()
        text = opt.get_text(" ", strip=True)
        if value:
            out.append((value, text))
    return out


def get_doctor_plugin(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    for script in soup.find_all("script"):
        txt = script.get_text()
        if 'apex.widget.selectList("#P4_DOCTORS"' in txt:
            m = re.search(
                r'apex\.widget\.selectList\("#P4_DOCTORS".*?ajaxIdentifier":"([^"]+)"',
                txt, re.S,
            )
            if m:
                return html.unescape(m.group(1)).replace("\\u002F", "/")
    return None

def get_opd_status(http_session: requests.Session, p_instance: str):
    params = {
        'session': f'{p_instance}',
    }

    response = http_session.get(
        'https://hrfjne8ujy3mixh-hilapex.adb.ap-mumbai-1.oraclecloudapps.com/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/opd-status',
        params=params,
        headers=browser_headers(),
    )
    return extract_opd_status(response.text)

def fetch_doctors(http_session: requests.Session, p_instance: str, department_code: str, page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    salt = soup.select_one("#pSalt")["value"]
    protected = html.unescape(soup.select_one("#pPageItemsProtected")["value"])
    plugin = get_doctor_plugin(page_html)
    if not plugin:
        raise RuntimeError("Could not locate doctor selectList plugin identifier.")

    payload = {
        "pageItems": {
            "itemsToSubmit": [{"n": "P4_DEPARTMENTS", "v": department_code}],
            "protected": protected,
            "rowVersion": "",
            "formRegionChecksums": [],
        },
        "salt": salt,
    }
    form = {
        "p_flow_id": "980",
        "p_flow_step_id": "4",
        "p_instance": p_instance,
        "p_debug": "",
        "p_request": f"PLUGIN={plugin}",
        "p_json": json.dumps(payload, separators=(",", ":")),
    }
    resp = http_session.post(
        f"{AJAX_URL}?p_context=hospital-registration-system-renukoot/new-registration/{p_instance}",
        headers=browser_headers(),
        data=form,
    )
    resp.raise_for_status()
    data = resp.json()
    return [{"label": row.get("d", ""), "value": row.get("r", "")} for row in data.get("values", [])]


def build_final_submit(http_session, p_instance, page_html, department_code, doctor_code, doctor_name):
    soup = BeautifulSoup(page_html, "html.parser")

    def get_value(id_):
        tag = soup.find(id=id_)
        return html.unescape(tag["value"]) if tag and tag.has_attr("value") else ""

    def get_ck(field_id):
        field = soup.find(id=field_id)
        if not field:
            return ""
        nxt = field.find_next("input", attrs={"data-for": field_id})
        return nxt["value"] if nxt and nxt.has_attr("value") else ""

    payload_json = {
        "pageItems": {
            "itemsToSubmit": [
                {"n": "P4_MR_NUMBER_DISPLAY", "v": get_value("P4_MR_NUMBER_DISPLAY"), "ck": get_ck("P4_MR_NUMBER_DISPLAY")},
                {"n": "P4_MR_NAME_DISPLAY", "v": get_value("P4_MR_NAME_DISPLAY"), "ck": get_ck("P4_MR_NAME_DISPLAY")},
                {"n": "P4_MR_NUMBER", "v": get_value("P4_MR_NUMBER"), "ck": get_ck("P4_MR_NUMBER")},
                {"n": "P4_MR_NAME", "v": get_value("P4_MR_NAME"), "ck": get_ck("P4_MR_NAME")},
                {"n": "P4_DEPARTMENTS", "v": department_code},
                {"n": "P4_DOCTORS", "v": doctor_code},
                {"n": "P4_OP_NUMBER", "v": ""},
                {"n": "P4_VISIT_NO", "v": ""},
                {"n": "P4_ERROR_MESSAGE", "v": ""},
                {"n": "P4_DOCTOR_NAME", "v": doctor_name},
            ],
            "protected": get_value("pPageItemsProtected"),
            "rowVersion": "",
            "formRegionChecksums": [],
        },
        "salt": get_value("pSalt"),
    }
    return urlencode({
        "p_flow_id": "980",
        "p_flow_step_id": "4",
        "p_instance": p_instance,
        "p_debug": "",
        "p_request": "REGISTER_PATIENT",
        "p_reload_on_submit": "S",
        "p_page_submission_id": get_value("pPageSubmissionId"),
        "p_json": json.dumps(payload_json, separators=(",", ":")),
    })


def submit_final(http_session, p_instance, final_data):
    resp = http_session.post(
        f"{LOGIN_ACCEPT_URL}?p_context=hospital-registration-system-renukoot/new-registration/{p_instance}",
        headers=browser_headers(),
        data=final_data,
    )
    resp.raise_for_status()
    return resp


# ─── Scheduling helpers ───────────────────────────────────────────────────────

def next_slot_ist(slot_key: str):
    """Return (target datetime in IST, delay_seconds) for the next valid slot."""
    slot = SLOT_TIMES[slot_key]
    now = datetime.now(IST)
    target = now.replace(hour=slot['hour'], minute=slot['minute'],
                         second=slot['second'], microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    for _ in range(8):
        wd = target.weekday()  # Mon=0 … Sun=6
        if wd == 6 or (wd == 5 and slot_key == 'afternoon'):
            target += timedelta(days=1)
        else:
            break
    delay = max((target - datetime.now(IST)).total_seconds(), 1)
    return target, delay


def execute_schedule(schedule_id: int):
    with _schedule_lock:
        sched = _schedules.get(schedule_id)
        if not sched or sched['status'] != 'pending':
            return
        sched['status'] = 'running'

    store = get_store(sched['sid'])
    meta = store.get('meta')

    if not meta:
        with _schedule_lock:
            sched['status'] = 'error'
            sched['message'] = 'Session expired. Please log in again.'
        return

    try:
        dep_idx = sched['dep_idx']
        dependents = store.get('dependents', [])
        if dep_idx >= len(dependents):
            raise RuntimeError('Dependent index out of range.')

        newreg_html = extract_new_registration_page(
            store['http_session'], meta['p_instance'], dependents[dep_idx]
        )
        final_data = build_final_submit(
            store['http_session'], meta['p_instance'],
            newreg_html, sched['dept_code'], sched['doc_value'], sched['doc_label']
        )

        success_found = False
        last_error = 'Registration window is closed or unknown error.'

        def make_req(req_id):
            try:
                resp = submit_final(store['http_session'], meta['p_instance'], final_data)
                return {'id': req_id, 'status': resp.status_code, 'text': resp.text}
            except Exception as ex:
                return {'id': req_id, 'status': 'Error', 'text': str(ex)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futs = [executor.submit(make_req, i) for i in range(1, 31)]
            for f in concurrent.futures.as_completed(futs):
                res = f.result()
                if not success_found and str(res.get('status')) == '200':
                    try:
                        parsed = json.loads(res['text'])
                        if parsed.get('redirectURL'):
                            success_found = True
                        elif parsed.get('errors'):
                            last_error = parsed['errors'][0].get('message', last_error)
                    except Exception:
                        pass

        with _schedule_lock:
            sched['status'] = 'done'
            sched['success'] = success_found
            sched['message'] = 'Appointment registered!' if success_found else last_error

    except Exception as e:
        with _schedule_lock:
            sched['status'] = 'error'
            sched['success'] = False
            sched['message'] = str(e)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    session.setdefault("sid", str(id(session)))
    return render_template("index.html")

@app.route("/api/opd_status")
def api_opd_status():
    sid = session.get("sid")
    store = get_store(sid)
    meta = store.get("meta")
    if not meta:
        return jsonify({"ok": False, "error": "Not logged in."}), 400
    try:
        response = get_opd_status(store["http_session"], meta["p_instance"])
        return jsonify({"ok": True, "status": response})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/login", methods=["POST"])
def api_login():
    sid = session.setdefault("sid", str(id(session)))
    store = get_store(sid)
    body = request.get_json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password required."}), 400
    try:
        meta = get_apex_session_data(store["http_session"])
        login_resp = login_apex(store["http_session"], username, password, meta)
        store["meta"] = meta
        store["main_html"] = fetch_main_page(store["http_session"], meta["p_instance"])
        store["dependents"] = extract_dependents(store["main_html"])
        store["newreg_html"] = None
        store["doctors"] = []
        store["final_responses"] = []
        return jsonify({
            "ok": True,
            "status": login_resp.status_code,
            "dependents": [{"label": d["label"], "idx": i} for i, d in enumerate(store["dependents"])],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/departments", methods=["POST"])
def api_departments():
    sid = session.get("sid")
    store = get_store(sid)
    body = request.get_json()
    dep_idx = int(body.get("dep_idx", 0))
    meta = store.get("meta")
    if not meta:
        return jsonify({"ok": False, "error": "Not logged in."}), 400
    dependents = store["dependents"]
    if dep_idx >= len(dependents):
        return jsonify({"ok": False, "error": "Invalid dependent index."}), 400
    try:
        store["newreg_html"] = extract_new_registration_page(
            store["http_session"], meta["p_instance"], dependents[dep_idx]
        )
        store["doctors"] = []
        depts = extract_departments(store["newreg_html"])
        return jsonify({"ok": True, "departments": [{"code": c, "name": n} for c, n in depts]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/doctors", methods=["POST"])
def api_doctors():
    sid = session.get("sid")
    store = get_store(sid)
    body = request.get_json()
    dept_code = body.get("dept_code", "")
    meta = store.get("meta")
    if not meta or not store["newreg_html"]:
        return jsonify({"ok": False, "error": "Load departments first."}), 400
    try:
        doctors = fetch_doctors(store["http_session"], meta["p_instance"], dept_code, store["newreg_html"])
        store["doctors"] = doctors
        return jsonify({"ok": True, "doctors": doctors})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/submit", methods=["POST"])
def api_submit():
    sid = session.get("sid")
    store = get_store(sid)
    body = request.get_json()
    dept_code = body.get("dept_code", "")
    doc_value = body.get("doc_value", "")
    doc_label = body.get("doc_label", "")
    meta = store.get("meta")
    if not meta or not store["newreg_html"]:
        return jsonify({"ok": False, "error": "Session not ready."}), 400

    def generate():
        try:
            final_data = build_final_submit(
                store["http_session"], meta["p_instance"],
                store["newreg_html"], dept_code, doc_value, doc_label
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"
            return

        results = [None] * 30

        def make_req(req_id):
            try:
                resp = submit_final(store["http_session"], meta["p_instance"], final_data)
                return {"id": req_id, "status": resp.status_code, "text": resp.text}
            except Exception as ex:
                return {"id": req_id, "status": "Error", "text": str(ex)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = {}
            for i in range(1, 31):
                f = executor.submit(make_req, i)
                futures[f] = i
                time.sleep(0.25)
                # Report progress after each submission
                yield f"data: {json.dumps({'type': 'progress', 'submitted': i})}\n\n"

            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                results[res["id"] - 1] = res
                yield f"data: {json.dumps({'type': 'result', 'id': res['id'], 'status': str(res['status']), 'text': res['text'][:500]})}\n\n"

        store["final_responses"] = results
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/schedule", methods=["POST"])
def api_schedule_create():
    sid = session.get("sid")
    store = get_store(sid)
    meta = store.get("meta")
    if not meta:
        return jsonify({"ok": False, "error": "Not logged in."}), 400

    body = request.get_json()
    slot_key = body.get("slot_key", "morning")
    dept_code = body.get("dept_code", "")
    doc_value = body.get("doc_value", "")
    doc_label = body.get("doc_label", "")
    dep_idx = int(body.get("dep_idx", 0))

    if slot_key not in SLOT_TIMES:
        return jsonify({"ok": False, "error": "Invalid slot."}), 400
    if not dept_code or not doc_value:
        return jsonify({"ok": False, "error": "Department and doctor required."}), 400

    target, delay = next_slot_ist(slot_key)

    global _schedule_counter
    with _schedule_lock:
        _schedule_counter += 1
        schedule_id = _schedule_counter

    sched = {
        "id": schedule_id,
        "sid": sid,
        "slot_key": slot_key,
        "slot_label": SLOT_TIMES[slot_key]["label"],
        "dept_code": dept_code,
        "doc_value": doc_value,
        "doc_label": doc_label,
        "dep_idx": dep_idx,
        "target_time": target.strftime("%a %d %b %H:%M:%S IST"),
        "status": "pending",
        "success": None,
        "message": None,
    }

    timer = threading.Timer(delay, execute_schedule, args=[schedule_id])
    timer.daemon = True
    timer.start()
    sched["timer"] = timer

    with _schedule_lock:
        _schedules[schedule_id] = sched

    return jsonify({
        "ok": True,
        "id": schedule_id,
        "target_time": sched["target_time"],
        "slot_label": sched["slot_label"],
        "delay_seconds": round(delay),
    })


@app.route("/api/schedules", methods=["GET"])
def api_schedules_list():
    sid = session.get("sid")
    with _schedule_lock:
        items = [
            {
                "id": s["id"],
                "slot_key": s["slot_key"],
                "slot_label": s["slot_label"],
                "dept_code": s["dept_code"],
                "doc_label": s["doc_label"],
                "target_time": s["target_time"],
                "status": s["status"],
                "success": s.get("success"),
                "message": s.get("message"),
            }
            for s in _schedules.values()
            if s["sid"] == sid
        ]
    return jsonify({"ok": True, "schedules": items})


@app.route("/api/schedule/<int:schedule_id>", methods=["DELETE"])
def api_schedule_delete(schedule_id):
    sid = session.get("sid")
    with _schedule_lock:
        sched = _schedules.get(schedule_id)
        if not sched or sched["sid"] != sid:
            return jsonify({"ok": False, "error": "Schedule not found."}), 404
        if sched["status"] == "pending":
            sched["timer"].cancel()
        del _schedules[schedule_id]
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0",port=8000, threaded=True)
