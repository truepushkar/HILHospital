import json
import html
import re
from urllib.parse import parse_qs, urlencode, urlparse
import concurrent.futures
import time

import requests
import streamlit as st
from bs4 import BeautifulSoup


BASE = "https://hrfjne8ujy3mixh-hilapex.adb.ap-mumbai-1.oraclecloudapps.com"
LOGIN_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/login"
HOME_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/home"
MAIN_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/main-page"
NEW_REG_URL = f"{BASE}/ords/r/xxhilapxprd01/hospital-registration-system-renukoot/new-registration"
LOGIN_ACCEPT_URL = f"{BASE}/ords/wwv_flow.accept"
AJAX_URL = f"{BASE}/ords/wwv_flow.ajax"


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


def get_value_from_soup(soup: BeautifulSoup, selector: str, attr: str = "value"):
    tag = soup.select_one(selector)
    return tag.get(attr) if tag else None


def get_apex_session_data(session: requests.Session) -> dict:
    response = session.get(LOGIN_URL, headers={"User-Agent": browser_headers()["User-Agent"]})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return {
        "p_instance": get_value_from_soup(soup, "#pInstance"),
        "p_page_submission_id": get_value_from_soup(soup, "#pPageSubmissionId"),
        "pSalt": get_value_from_soup(soup, "#pSalt"),
        "pPageItemsProtected": get_value_from_soup(soup, "#pPageItemsProtected"),
    }


def login(session: requests.Session, username: str, password: str, meta: dict) -> requests.Response:
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
    return session.post(
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


def fetch_main_page(session: requests.Session, p_instance: str) -> str:
    resp = session.get(
        MAIN_URL,
        params={"session": p_instance},
        headers=page_headers(),
    )
    resp.raise_for_status()
    return resp.text


def extract_new_registration_page(session: requests.Session, p_instance: str, dependent: dict) -> str:
    params = {
        "p4_mr_number": dependent["p4_mr_number"],
        "p4_mr_name": dependent["p4_mr_name"],
        "p4_mr_number_display": dependent["p4_mr_number_display"],
        "p4_mr_name_display": dependent["p4_mr_name_display"],
        "session": p_instance,
        "cs": dependent["cs"],
    }
    resp = session.get(NEW_REG_URL, params=params, headers=page_headers())
    resp.raise_for_status()
    return resp.text


def extract_departments(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    select = soup.select_one("#P4_DEPARTMENTS")
    if not select:
        return [
            ("A003", "Anaesthesia"),
            ("C004", "Cardiology"),
            ("C008", "Chest"),
            ("D001", "Dental"),
            ("E004", "ENT"),
            ("G001", "Gastroenterology"),
            ("M002", "General Medicine"),
            ("G002", "General Surgery"),
            ("G003", "Gynaecology & Obstetrics"),
            ("N002", "Nephrology"),
            ("N004", "Neurology"),
            ("OH01", "Occupational Health"),
            ("O003", "Ophthalmology"),
            ("O004", "Orthopaedic"),
            ("P006", "Paediatrics"),
            ("P004", "Psychiatry"),
            ("R002", "Radiology"),
            ("P009", "Visitors Ophthalmology"),
        ]
    out = []
    for opt in select.find_all("option"):
        value = (opt.get("value") or "").strip()
        text = opt.get_text(" ", strip=True)
        if value:
            out.append((value, text))
    return out


def get_doctor_plugin(page_html: str) -> str | None:
    soup = BeautifulSoup(page_html, "html.parser")
    for script in soup.find_all("script"):
        txt = script.get_text()
        if 'apex.widget.selectList("#P4_DOCTORS"' in txt:
            m = re.search(
                r'apex\.widget\.selectList\("#P4_DOCTORS".*?ajaxIdentifier":"([^"]+)"',
                txt,
                re.S,
            )
            if m:
                return html.unescape(m.group(1)).replace("\\u002F", "/")
    return None


def fetch_doctors(session: requests.Session, p_instance: str, department_code: str, page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    salt = soup.select_one("#pSalt")["value"]
    protected = html.unescape(soup.select_one("#pPageItemsProtected")["value"])
    plugin = get_doctor_plugin(page_html)

    if not plugin:
        raise RuntimeError("Could not locate doctor selectList plugin identifier in page HTML.")

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

    resp = session.post(
        f"{AJAX_URL}?p_context=hospital-registration-system-renukoot/new-registration/{p_instance}",
        headers=browser_headers(),
        data=form,
    )
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        data = json.loads(resp.text)

    values = data.get("values", [])
    doctors = []
    for row in values:
        doctors.append({"label": row.get("d", ""), "value": row.get("r", "")})
    return doctors


def build_final_submit(session: requests.Session, p_instance: str, page_html: str, department_code: str, doctor_code: str, doctor_name: str) -> str:
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

    submission_id = get_value("pPageSubmissionId")
    salt = get_value("pSalt")
    protected = get_value("pPageItemsProtected")

    mr_number_display = get_value("P4_MR_NUMBER_DISPLAY")
    mr_name_display = get_value("P4_MR_NAME_DISPLAY")
    mr_number = get_value("P4_MR_NUMBER")
    mr_name = get_value("P4_MR_NAME")

    payload_json = {
        "pageItems": {
            "itemsToSubmit": [
                {"n": "P4_MR_NUMBER_DISPLAY", "v": mr_number_display, "ck": get_ck("P4_MR_NUMBER_DISPLAY")},
                {"n": "P4_MR_NAME_DISPLAY", "v": mr_name_display, "ck": get_ck("P4_MR_NAME_DISPLAY")},
                {"n": "P4_MR_NUMBER", "v": mr_number, "ck": get_ck("P4_MR_NUMBER")},
                {"n": "P4_MR_NAME", "v": mr_name, "ck": get_ck("P4_MR_NAME")},
                {"n": "P4_DEPARTMENTS", "v": department_code},
                {"n": "P4_DOCTORS", "v": doctor_code},
                {"n": "P4_OP_NUMBER", "v": ""},
                {"n": "P4_VISIT_NO", "v": ""},
                {"n": "P4_ERROR_MESSAGE", "v": ""},
                {"n": "P4_DOCTOR_NAME", "v": doctor_name},
            ],
            "protected": protected,
            "rowVersion": "",
            "formRegionChecksums": [],
        },
        "salt": salt,
    }

    form_data = {
        "p_flow_id": "980",
        "p_flow_step_id": "4",
        "p_instance": p_instance,
        "p_debug": "",
        "p_request": "REGISTER_PATIENT",
        "p_reload_on_submit": "S",
        "p_page_submission_id": submission_id,
        "p_json": json.dumps(payload_json, separators=(",", ":")),
    }

    return urlencode(form_data)


def submit_final(session: requests.Session, p_instance: str, final_data: str):
    resp = session.post(
        f"{LOGIN_ACCEPT_URL}?p_context=hospital-registration-system-renukoot/new-registration/{p_instance}",
        headers=browser_headers(),
        data=final_data,
    )
    resp.raise_for_status()
    return resp


st.set_page_config(page_title="Hospital Registration UI", layout="wide")
import streamlit.components.v1 as components

st.title("Hospital Registration UI")

components.html(
    """
    <div id="clock-container">
        <div id="clock">Loading...</div>
    </div>

    <style>
    body{
        margin:0;
        padding:0;
        background:#000;
    }

    #clock-container{
        display:flex;
        justify-content:center;
        align-items:center;
        width:100%;
    }

    #clock{
        font-size:26px;
        font-weight:700;
        padding:10px 20px;
        border-radius:12px;
        text-align:center;

        background:#000000;     /* black background */
        color:#ffffff;          /* white text */

        border:1px solid #333;
        box-shadow:0 0 10px rgba(255,255,255,0.15);
        font-family:monospace;
    }
    </style>

    <script>
    function updateClock() {
        const now = new Date();

        const h = String(now.getHours()).padStart(2,'0');
        const m = String(now.getMinutes()).padStart(2,'0');
        const s = String(now.getSeconds()).padStart(2,'0');

        document.getElementById("clock").innerHTML =
            "🕒 " + h + ":" + m + ":" + s;
    }

    updateClock();
    setInterval(updateClock,1000);
    </script>
    """,
    height=80
)

with st.sidebar:
    st.header("Login")
    username = st.text_input("Username", value="")
    password = st.text_input("Password", value="", type="password")
    start = st.button("Start session", type="primary")

if "session" not in st.session_state:
    st.session_state.session = requests.Session()
if "meta" not in st.session_state:
    st.session_state.meta = None
if "dependents" not in st.session_state:
    st.session_state.dependents = []
if "main_html" not in st.session_state:
    st.session_state.main_html = None
if "newreg_html" not in st.session_state:
    st.session_state.newreg_html = None
if "doctors" not in st.session_state:
    st.session_state.doctors = []
if "final_responses" not in st.session_state:
    st.session_state.final_responses = []

if start:
    if not username or not password:
        st.error("Enter username and password.")
    else:
        try:
            meta = get_apex_session_data(st.session_state.session)
            login_resp = login(st.session_state.session, username, password, meta)
            st.session_state.meta = meta
            st.session_state.main_html = fetch_main_page(st.session_state.session, meta["p_instance"])
            st.session_state.dependents = extract_dependents(st.session_state.main_html)
            st.session_state.newreg_html = None
            st.session_state.doctors = []
            st.session_state.final_responses = []
            st.success(f"Session started. HTTP {login_resp.status_code}")
        except Exception as e:
            st.error(f"Login failed: {e}")

meta = st.session_state.meta

if not meta:
    st.info("Start the session from the sidebar.")
    st.stop()

if not st.session_state.dependents:
    st.warning("No dependents found.")
    st.stop()

dep_labels = [d["label"] for d in st.session_state.dependents]
selected_dep_label = st.selectbox("Select dependent", dep_labels, index=0)
selected_dep = next(d for d in st.session_state.dependents if d["label"] == selected_dep_label)

if st.button("Load departments"):
    try:
        st.session_state.newreg_html = extract_new_registration_page(
            st.session_state.session, meta["p_instance"], selected_dep
        )
        st.session_state.doctors = []
        st.session_state.final_responses = []
        st.success("Department list loaded.")
    except Exception as e:
        st.error(f"Could not load departments: {e}")

if st.session_state.newreg_html:
    dept_options = extract_departments(st.session_state.newreg_html)
    dept_labels = [f"{code} - {name}" for code, name in dept_options]
    selected_dept_label = st.selectbox("Select department", dept_labels, index=0)
    selected_dept_code, selected_dept_name = next(
        (code, name) for code, name in dept_options if f"{code} - {name}" == selected_dept_label
    )

    if st.button("Load doctors"):
        try:
            st.session_state.doctors = fetch_doctors(
                st.session_state.session,
                meta["p_instance"],
                selected_dept_code,
                st.session_state.newreg_html,
            )
            st.session_state.final_responses = []
            st.success("Doctor list loaded.")
        except Exception as e:
            st.error(f"Could not load doctors: {e}")

    if st.session_state.doctors:
        doc_labels = [f'{d["value"]} - {d["label"]}' for d in st.session_state.doctors]
        selected_doc_label = st.selectbox("Select doctor", doc_labels, index=0)
        selected_doc = next(
            d for d in st.session_state.doctors if f'{d["value"]} - {d["label"]}' == selected_doc_label
        )
        
        if st.button("Submit appointment", type="primary"):
            try:
                final_data = build_final_submit(
                    st.session_state.session,
                    meta["p_instance"],
                    st.session_state.newreg_html,
                    selected_dept_code,
                    selected_doc["value"],
                    selected_doc["label"],
                )
                
                st.info("Sending requests every second for 20 seconds...")
                progress_bar = st.progress(0)
                status_placeholder = st.empty()
                st.session_state.final_responses = []
                
                # EXTRACT VARIABLES FOR THE BACKGROUND THREAD
                http_session = st.session_state.session
                p_instance = meta["p_instance"]
                
                # Background function - strictly pass in required objects
                def make_req(req_id, req_session, req_p_instance, req_final_data):
                    try:
                        resp = submit_final(req_session, req_p_instance, req_final_data)
                        return {"id": req_id, "status": resp.status_code, "text": resp.text}
                    except Exception as e:
                        return {"id": req_id, "status": "Error", "text": str(e)}

                futures = []
                
                # Execute asynchronously
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    for i in range(1, 21):
                        # Start background thread, explicitly passing the session
                        futures.append(
                            executor.submit(make_req, i, http_session, p_instance, final_data)
                        )
                        
                        # Update UI natively
                        progress_bar.progress(i / 20.0)
                        
                        lines = []
                        for idx, f in enumerate(futures, 1):
                            if f.done():
                                res = f.result()
                                lines.append(f"Request {idx:02d} | Status: {res['status']}")
                            else:
                                lines.append(f"Request {idx:02d} | Pending...")
                                
                        status_placeholder.code("\n".join(lines))
                        
                        # Wait 1 second before the next request
                        time.sleep(1)
                    
                    concurrent.futures.wait(futures)
                    
                    # Store final results in session state
                    final_lines = []
                    for idx, f in enumerate(futures, 1):
                        res = f.result()
                        final_lines.append(f"Request {idx:02d} | Status: {res['status']}")
                        st.session_state.final_responses.append(res)
                    
                    status_placeholder.code("\n".join(final_lines))
                    st.success("All 20 simultaneous requests finished!")
                    
            except Exception as e:
                st.error(f"Submit failed: {e}")

if st.session_state.final_responses:
    st.subheader("Appointment Responses (Last 20)")
    for res in st.session_state.final_responses:
        with st.expander(f"Request {res['id']} - Status: {res['status']}"):
            st.code(res["text"], language="json")
