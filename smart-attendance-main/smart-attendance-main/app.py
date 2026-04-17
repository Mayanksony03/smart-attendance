from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timedelta
from face_utils import register_face, recognize_face, mark_absent
from db import sessions_col, attendance_col, students_col, teachers_col, branches_col
from send_email import send_email_async, send_email
import os
import random
import math
import bson
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key     = os.environ.get("SECRET_KEY", "smartattend-secret-2024")
ADMIN_EMAIL        = os.environ.get("ADMIN_EMAIL", "attendancecollege26@gmail.com")
OTP_EXPIRY_MINUTES = 10

COLLEGE_LAT        = float(os.environ.get("COLLEGE_LAT",  "23.2599"))
COLLEGE_LNG        = float(os.environ.get("COLLEGE_LNG",  "77.4126"))
MAX_DISTANCE       = int(os.environ.get("MAX_DISTANCE",   "100"))
ATTENDANCE_MINUTES = 10



WIFI_CHECK_MODE = os.environ.get("WIFI_CHECK_MODE", "whitelist").lower()


COLLEGE_WIFI_IPS = [ip.strip() for ip in os.environ.get("COLLEGE_WIFI_IPS", "103.134.248.238").split(",") if ip.strip()]


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated") or session.get("role") != "admin":
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def teacher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated") or session.get("role") != "teacher":
            return redirect(url_for("teacher_login"))
        return f(*args, **kwargs)
    return decorated


def any_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_client_ip():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    return ip.split(",")[0].strip()


def haversine_distance(lat1, lon1, lat2, lon2):
    """Returns distance in metres between two GPS coordinates."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_private_ip(ip):
    """Returns True if the IP is an RFC-1918 private address."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a = int(parts[0])
        b = int(parts[1])
        return (
            a == 10 or
            (a == 172 and 16 <= b <= 31) or
            (a == 192 and b == 168)
        )
    except ValueError:
        return False


def check_wifi(admin_ip, student_ip):
    """
    Returns (ok: bool, reason: str).
    ok=True  → allow
    ok=False → block with reason

    Modes:
      whitelist → student IP must match COLLEGE_WIFI_IPS (works on Railway/cloud)
      off       → skip WiFi check entirely, GPS only
      lan       → same /24 subnet check (local server only)
      auto      → auto-decide based on admin IP type
    """
    mode = WIFI_CHECK_MODE

    # ── Mode: off ─────────────────────────────────────
    if mode == "off":
        print(f"[WIFI] Mode=off — skipping check")
        return True, "WiFi check disabled"

    # ── Mode: whitelist (recommended for Railway/cloud) ─
    if mode == "whitelist":
        if not COLLEGE_WIFI_IPS:
            print(f"[WIFI] Whitelist mode but COLLEGE_WIFI_IPS not set — skipping")
            return True, "No whitelist IPs configured"

        # Exact match first (IPv4 or full IPv6)
        if student_ip in COLLEGE_WIFI_IPS:
            print(f"[WIFI] Whitelist PASSED — {student_ip} is a college IP")
            return True, "Connected to college network"

        # IPv6 prefix match — first 4 groups must match (same network)
        # e.g. 2401:4900:51d0:7ab7:xxxx:xxxx:xxxx:xxxx
        if ":" in student_ip:
            student_prefix = ":".join(student_ip.split(":")[:4])
            for allowed_ip in COLLEGE_WIFI_IPS:
                if ":" in allowed_ip:
                    allowed_prefix = ":".join(allowed_ip.split(":")[:4])
                    if student_prefix == allowed_prefix:
                        print(f"[WIFI] Whitelist PASSED — IPv6 prefix match {student_prefix}")
                        return True, "Connected to college network"

        print(f"[WIFI] Whitelist BLOCKED — {student_ip} not in {COLLEGE_WIFI_IPS}")
        return False, "Not on college WiFi. Please connect to college WiFi and try again."

    # ── Mode: lan ─────────────────────────────────────
    if mode == "lan":
        if admin_ip.split(".")[:3] == student_ip.split(".")[:3]:
            print(f"[WIFI] Mode=lan PASSED — same subnet")
            return True, "Same subnet"
        print(f"[WIFI] Mode=lan BLOCKED — different subnet")
        return False, "Not on same WiFi network. Connect to college WiFi."

    # ── Mode: auto (fallback) ─────────────────────────
    if not admin_ip:
        print(f"[WIFI] Mode=auto — no admin_ip stored, skipping")
        return True, "No admin IP stored"

    if is_private_ip(admin_ip):
        if admin_ip.split(".")[:3] == student_ip.split(".")[:3]:
            print(f"[WIFI] Mode=auto LAN PASSED — same subnet")
            return True, "Same LAN subnet"
        print(f"[WIFI] Mode=auto LAN BLOCKED — different subnet")
        return False, "Not on same WiFi network. Connect to college WiFi."
    else:
        print(f"[WIFI] Mode=auto PUBLIC — admin on cloud IP ({admin_ip}), skipping WiFi, using GPS only")
        return True, "Public deployment — GPS check enforces location"


# ── AUTH ─────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("home"))
    error = ""
    if request.method == "POST":
        otp = str(random.randint(100000, 999999))
        session["otp"]        = otp
        session["otp_expiry"] = (datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()
        subject = "SmartAttend — Your Login OTP"
        body    = f"Hello Admin,\n\nYour OTP is: {otp}\n\nValid for {OTP_EXPIRY_MINUTES} minutes.\n\n— SmartAttend"
        send_email_async(ADMIN_EMAIL, subject, body)
        print(f"[OTP] Generated {otp} for {ADMIN_EMAIL}")
        return redirect(url_for("verify_otp"))
    return render_template("login.html", error=error, admin_email=ADMIN_EMAIL)


@app.route("/verify", methods=["GET", "POST"])
def verify_otp():
    if session.get("authenticated"):
        return redirect(url_for("home"))
    if not session.get("otp"):
        return redirect(url_for("login"))
    error = ""
    if request.method == "POST":
        entered = request.form.get("otp", "").strip()
        expiry  = datetime.fromisoformat(session.get("otp_expiry", datetime.now().isoformat()))
        if datetime.now() > expiry:
            session.pop("otp", None)
            session.pop("otp_expiry", None)
            error = "OTP expired. Please request a new one."
        elif entered == session.get("otp"):
            session["authenticated"] = True
            session["role"] = "admin"
            session.pop("otp", None)
            session.pop("otp_expiry", None)
            return redirect(url_for("home"))
        else:
            error = "Incorrect OTP. Please try again."
    return render_template("verify_otp.html", error=error, admin_email=ADMIN_EMAIL)


@app.route("/resend-otp")
def resend_otp():
    otp = str(random.randint(100000, 999999))
    session["otp"]        = otp
    session["otp_expiry"] = (datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()
    send_email_async(ADMIN_EMAIL, "SmartAttend — New OTP", f"Your new OTP is: {otp}")
    return redirect(url_for("verify_otp"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── MAIN ROUTES ───────────────────────────────────────

@app.route("/")
@any_login_required
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
@admin_required
def register():
    if request.method == "POST":
        data          = request.get_json()
        name          = data["name"]
        student_email = data["student_email"]
        parent_email  = data["parent_email"]
        image_data    = data["image"]
        roll_no       = data.get("roll_no")
        branch        = data.get("branch")
        semester      = data.get("semester")
        section       = data.get("section")
        message       = register_face(name, student_email, parent_email, image_data, roll_no, branch, semester, section)
        return jsonify({"message": message})
    branches = list(branches_col.find({}, {"_id": 0, "name": 1}))
    return render_template("register.html", branches=branches)


@app.route("/create_session", methods=["GET", "POST"])
@teacher_required
def create_session():
    if request.method == "POST":
        subject_name = request.form["subject_name"]
        subject_code = request.form["subject_code"]
        branch       = request.form.get("branch")
        semester     = request.form.get("semester")
        section      = request.form.get("section")
        max_students = 0  # Set via live panel by teacher after session starts
        session_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sessions_col.insert_one({
            "subject_name": subject_name,
            "subject_code": subject_code,
            "branch":       branch,
            "semester":     semester,
            "section":      section,
            "teacher_username": session.get("username"),
            "session_time": session_time,
            "max_students": max_students
        })
        return redirect(url_for("sessions"))
    branches = list(branches_col.find({}, {"_id": 0, "name": 1}))
    return render_template("create_session.html", branches=branches)


@app.route("/sessions")
@any_login_required
def sessions():
    query = {}
    if session.get("role") == "teacher":
        query["teacher_username"] = session.get("username")
    raw  = list(sessions_col.find(query).sort("_id", -1))
    data = [(str(s["_id"]), s["subject_name"], s["subject_code"], s["session_time"], s.get("branch", ""), s.get("semester", ""), s.get("section", "")) for s in raw]
    return render_template("sessions.html", data=data)




    print(f"[SESSION] Started by admin IP: {admin_ip} | Expires: {expires_at_ms} | WiFi mode: {WIFI_CHECK_MODE}")

    base_url    = request.host_url.rstrip("/")
    student_url = f"{base_url}/s/{session_id}"

    return render_template("admin_live.html",
        session_id   = session_id,
        subject_name = sess["subject_name"],
        subject_code = sess["subject_code"],
        expires_at   = expires_at_ms,
        student_url  = student_url
    )


# ── ADMIN GPS SAVE — dedicated route to save admin location ──────────────────
@app.route("/save-admin-location/<session_id>", methods=["POST"])
@teacher_required
def save_admin_location(session_id):
    try:
        data = request.get_json()
        lat  = float(data["lat"])
        lng  = float(data["lng"])
        sessions_col.update_one(
            {"_id": bson.ObjectId(session_id)},
            {"$set": {"admin_lat": lat, "admin_lng": lng}}
        )
        print(f"[ADMIN GPS] Saved via dedicated route: {lat}, {lng}")
        return jsonify({"ok": True, "lat": lat, "lng": lng})
    except Exception as e:
        print(f"[ADMIN GPS] Save error: {e}")
        return jsonify({"ok": False, "error": str(e)})


# ── ADMIN GPS API — returns live admin location for a session ────────────────
@app.route("/session-location/<session_id>")
def session_location(session_id):
    try:
        sess = sessions_col.find_one({"_id": bson.ObjectId(session_id)})
    except Exception:
        return jsonify({"ok": False})

    if not sess:
        return jsonify({"ok": False})

    admin_lat = sess.get("admin_lat")
    admin_lng = sess.get("admin_lng")

    if admin_lat is not None and admin_lng is not None:
        return jsonify({
            "ok":       True,
            "lat":      admin_lat,
            "lng":      admin_lng,
            "max_dist": int(os.environ.get("ADMIN_GPS_RANGE", "150")),
            "source":   "admin"
        })
    else:
        return jsonify({
            "ok":       True,
            "lat":      COLLEGE_LAT,
            "lng":      COLLEGE_LNG,
            "max_dist": MAX_DISTANCE,
            "source":   "college"
        })





@app.route("/student-mark/<session_id>", methods=["POST"])
def student_mark(session_id):
    try:
        sess = sessions_col.find_one({"_id": bson.ObjectId(session_id)})
    except Exception:
        return jsonify({"message": "Invalid session"}), 400

    if not sess:
        return jsonify({"message": "Session not found"}), 404

    # ── 1. TIME WINDOW CHECK ──────────────────────────
    expires_at = sess.get("expires_at", 0)
    now_ms     = int(datetime.now().timestamp() * 1000)
    if now_ms > expires_at:
        return jsonify({"message": "Attendance window has expired"})

    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"message": "No image received"})

    # ── 2. ATTENDANCE LIMIT CHECK ────────────────────
    max_students = sess.get("max_students", 0)
    if max_students and max_students > 0:
        present_count = attendance_col.count_documents({
            "session_id": session_id,
            "status":     "PRESENT"
        })
        print(f"[LIMIT] Present: {present_count} / Max: {max_students}")
        if present_count >= max_students:
            return jsonify({
                "message": f"Attendance limit reached! Maximum {max_students} students allowed. Contact your teacher."
            })

    # ── 3. WIFI / NETWORK CHECK ───────────────────────
    # Behaviour is controlled by WIFI_CHECK_MODE env var (default: "auto")
    # In "auto" mode: only enforced when admin is on a private LAN IP.
    # When deployed to Railway/Render/cloud, admin IP is public → check skipped.
    # Set WIFI_CHECK_MODE=off to disable entirely (recommended for multi-WiFi setups).
    admin_ip   = sess.get("admin_ip", "")
    student_ip = get_client_ip()
    wifi_ok, wifi_reason = check_wifi(admin_ip, student_ip)

    if not wifi_ok:
        return jsonify({"message": wifi_reason})

    # ── 3. GPS / LOCATION CHECK ───────────────────────
    # WiFi check already confirms student is on campus network.
    # GPS is logged for record but NOT used to block attendance.
    student_lat = data.get("lat")
    student_lng = data.get("lng")

    admin_lat = sess.get("admin_lat")
    admin_lng = sess.get("admin_lng")

    if student_lat is not None and student_lng is not None and admin_lat is not None and admin_lng is not None:
        try:
            dist = haversine_distance(float(student_lat), float(student_lng), admin_lat, admin_lng)
            print(f"[GPS] Student distance from teacher: {dist:.0f}m (logged only, not enforced)")
        except Exception as e:
            print(f"[GPS] Distance calc error: {e}")
    else:
        print(f"[GPS] Skipping distance check — lat/lng missing")

    # ── 4. FACE RECOGNITION ───────────────────────────
    image_data = data["image"]
    message    = recognize_face(sess, image_data)
    print(f"[FACE] Result: {message}")
    return jsonify({"message": message})


# ── UPDATE ATTENDANCE LIMIT ──────────────────────────
@app.route("/update-limit/<session_id>", methods=["POST"])
@teacher_required
def update_limit(session_id):
    try:
        data        = request.get_json()
        new_limit   = int(data.get("max_students", 0))
        sessions_col.update_one(
            {"_id": bson.ObjectId(session_id)},
            {"$set": {"max_students": new_limit}}
        )
        print(f"[LIMIT] Updated max_students to {new_limit} for session {session_id}")
        return jsonify({"ok": True, "max_students": new_limit})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── DELETE STUDENT ATTENDANCE ─────────────────────────
@app.route("/delete-attendance/<session_id>/<student_name>", methods=["POST"])
@teacher_required
def delete_attendance(session_id, student_name):
    try:
        result = attendance_col.delete_one({
            "session_id":   session_id,
            "student_name": student_name
        })
        if result.deleted_count:
            print(f"[DELETE] Removed attendance for {student_name} in session {session_id}")
            return jsonify({"ok": True, "message": f"{student_name} attendance removed"})
        return jsonify({"ok": False, "message": "Record not found"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── LIVE POLL ─────────────────────────────────────────

@app.route("/live-attendance/<session_id>")
@teacher_required
def live_attendance(session_id):
    records = list(attendance_col.find(
        {"session_id": session_id, "status": "PRESENT"},
        {"student_name": 1, "time": 1, "_id": 0}
    ))
    present = [{"name": r["student_name"], "time": r.get("time", "")} for r in records]
    sess        = sessions_col.find_one({"_id": bson.ObjectId(session_id)})
    max_students = sess.get("max_students", 0) if sess else 0
    print(f"[LIVE POLL] Session {session_id} — {len(present)} present / max {max_students}")
    return jsonify({"present": present, "count": len(present), "max_students": max_students})


# ── REPORT ────────────────────────────────────────────

@app.route("/report/<session_id>")
@any_login_required
def report(session_id):
    sess = sessions_col.find_one({"_id": bson.ObjectId(session_id)})
    if not sess: return "Session not found", 404

    query = {}
    if sess.get("branch"): query["branch"] = sess["branch"]
    if sess.get("semester"): query["semester"] = str(sess["semester"])
    if sess.get("section"): query["section"] = sess["section"]

    all_students = [s["name"] for s in students_col.find(query, {"name": 1})]
    attendance_records = {
        r["student_name"]: r["status"]
        for r in attendance_col.find({"session_id": session_id})
    }
    data = [(name, attendance_records.get(name, "ABSENT")) for name in all_students]
    return render_template("report.html", data=data)


@app.route("/end/<session_id>")
@teacher_required
def end(session_id):
    sess = sessions_col.find_one({"_id": bson.ObjectId(session_id)})
    mark_absent(session_id, sess)
    return "Session Ended and Emails Sent"


@app.route("/delete", methods=["GET", "POST"])
@admin_required
def delete():
    message = ""
    if request.method == "POST":
        name   = request.form["name"]
        result = students_col.delete_one({"name": name})
        message = f"{name} deleted" if result.deleted_count else "Student not found"
    return render_template("delete.html", message=message)


# ── DEBUG ROUTES ──────────────────────────────────────

@app.route("/test-email")
def test_email():
    from send_email import send_email
    test_to   = request.args.get("email", ADMIN_EMAIL)
    brevo_api = os.environ.get("BREVO_API_KEY", "")
    success   = send_email(test_to, "SmartAttend Test Email", "Brevo API is working correctly.")
    return f"""<pre>
BREVO_API_KEY : {'SET (' + str(len(brevo_api)) + ' chars)' if brevo_api else 'NOT SET'}
ADMIN_EMAIL   : {ADMIN_EMAIL}
Test to       : {test_to}
Result        : {'SUCCESS' if success else 'FAILED'}
</pre>"""


@app.route("/debug-session/<session_id>")
@any_login_required
def debug_session(session_id):
    """Debug route — check stored session info and WiFi mode."""
    try:
        sess = sessions_col.find_one({"_id": bson.ObjectId(session_id)})
    except Exception:
        return "Invalid ID"
    records    = list(attendance_col.find({"session_id": session_id}))
    admin_ip   = sess.get("admin_ip", "NOT SET") if sess else "SESSION NOT FOUND"
    my_ip      = get_client_ip()
    wifi_ok, wifi_reason = check_wifi(admin_ip, my_ip)
    return f"""<pre>
Session ID       : {session_id}
WIFI_CHECK_MODE  : {WIFI_CHECK_MODE}
COLLEGE_WIFI_IPS : {COLLEGE_WIFI_IPS}
Admin IP         : {admin_ip}
Your IP          : {my_ip}
Admin private    : {is_private_ip(admin_ip) if admin_ip else 'N/A'}
WiFi result      : {'OK' if wifi_ok else 'BLOCKED'} — {wifi_reason}
COLLEGE_LAT      : {COLLEGE_LAT}
COLLEGE_LNG      : {COLLEGE_LNG}
MAX_DISTANCE     : {MAX_DISTANCE}m
Expires at       : {sess.get('expires_at', 'NOT SET') if sess else 'N/A'}
Expired          : {int(datetime.now().timestamp()*1000) > sess.get('expires_at', 0) if sess else 'N/A'}
Total records    : {len(records)}
Present          : {[r['student_name'] for r in records if r['status']=='PRESENT']}
Absent           : {[r['student_name'] for r in records if r['status']=='ABSENT']}
</pre>"""

# ── NEW ROUTES for TEACHER and BRANCHES ─────────────────────────────

@app.route("/admin/branches", methods=["GET", "POST"])
@admin_required
def admin_branches():
    if request.method == "POST":
        branch_name = request.form.get("name")
        if branch_name:
            try:
                branches_col.insert_one({"name": branch_name})
            except Exception as e:
                pass
        return redirect(url_for("admin_branches"))
    
    branches = list(branches_col.find({}, {"_id": 0, "name": 1}))
    return render_template("branches.html", branches=branches)


@app.route("/admin/teachers", methods=["GET", "POST"])
@admin_required
def admin_teachers():
    if request.method == "POST":
        name = request.form.get("name")
        employee_id = request.form.get("employee_id")
        branch = request.form.get("branch")
        username = request.form.get("username")
        password = request.form.get("password")
        
        try:
            teachers_col.insert_one({
                "name": name,
                "employee_id": employee_id,
                "branch": branch,
                "username": username,
                "password_hash": generate_password_hash(password)
            })
        except Exception as e:
            pass
        return redirect(url_for("admin_teachers"))
        
    teachers = list(teachers_col.find({}, {"_id": 0}))
    branches = list(branches_col.find({}, {"_id": 0, "name": 1}))
    return render_template("teachers.html", teachers=teachers, branches=branches)


@app.route("/teacher/login", methods=["GET", "POST"])
def teacher_login():
    if session.get("authenticated"):
        return redirect(url_for("home"))
        
    error = ""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        teacher = teachers_col.find_one({"username": username})
        if teacher and check_password_hash(teacher.get("password_hash", ""), password):
            session["authenticated"] = True
            session["role"] = "teacher"
            session["username"] = username
            session["name"] = teacher.get("name")
            return redirect(url_for("home"))
        else:
            error = "Invalid username or password"
            
    return render_template("teacher_login.html", error=error)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
