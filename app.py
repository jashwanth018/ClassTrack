import hmac
import os
from datetime import date
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from database.db import (
    get_dashboard_attendance,
    get_students,
    get_attendance_records_for_date,
    get_attendance_summary,
    get_recent_attendance,
    init_db,
    load_attendance_for_date,
    save_attendance_for_date,
    total_students,
    import_students_from_excel,
)

load_dotenv(override=True)

passcode = os.getenv("CLASSTRACK_PASSCODE")
secret_key = os.getenv("FLASK_SECRET_KEY")

if not passcode or not secret_key:
    raise RuntimeError("CLASSTRACK_PASSCODE and FLASK_SECRET_KEY must be set in .env")

app = Flask(__name__)
app.config["SECRET_KEY"] = secret_key
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

init_db()


def current_application_date() -> date:
    """Return the real date, or a developer-only date override for testing."""
    test_date = os.getenv("CLASSTRACK_TEST_DATE", "").strip()
    if test_date:
        try:
            return date.fromisoformat(test_date)
        except ValueError as exc:
            raise RuntimeError("CLASSTRACK_TEST_DATE must use YYYY-MM-DD format.") from exc
    return date.today()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("home"))

    error = None
    if request.method == "POST":
        entered_passcode = request.form.get("passcode", "")
        if hmac.compare_digest(entered_passcode, passcode):
            session.clear()
            session["authenticated"] = True
            return redirect(url_for("home"))
        error = "Invalid passcode."

    return render_template("login.html", error=error)


@app.after_request
def prevent_dynamic_caching(response):
    """Prevent browsers from reusing protected dynamic pages after logout."""
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/")
@login_required
def home():
    today = current_application_date()
    today_iso = today.isoformat()
    today_attendance = get_dashboard_attendance(today_iso)
    recent_attendance = [
        {
            **record,
            "date_display": date.fromisoformat(record["date"]).strftime("%d %B %Y"),
        }
        for record in get_recent_attendance()
    ]
    return render_template(
        "dashboard.html",
        today_attendance=today_attendance,
        recent_attendance=recent_attendance,
    )


@app.route("/attendance")
@login_required
def attendance():
    students = get_students("")
    today = current_application_date()
    today_iso = today.isoformat()
    saved_attendance = load_attendance_for_date(today_iso)
    return render_template(
        "attendance.html",
        students=students,
        saved_attendance=saved_attendance,
        attendance_date=today_iso,
        attendance_date_display=today.strftime("%d %B %Y"),
    )


@app.route("/api/attendance/<attendance_date>", methods=["GET"])
@login_required
def get_attendance(attendance_date):
    try:
        attendance = load_attendance_for_date(attendance_date)
        summary = get_attendance_summary(attendance_date)
        return jsonify({"date": attendance_date, "attendance": attendance, "summary": summary})
    except Exception:  # pragma: no cover - defensive backend validation
        return jsonify({"error": "Unable to load attendance."}), 400


@app.route("/api/attendance/save", methods=["POST"])
@login_required
def save_attendance():
    payload = request.get_json(silent=True) or {}
    attendance_items = payload.get("attendance")

    if not isinstance(attendance_items, list):
        return jsonify({"error": "Attendance data is missing or malformed."}), 400

    try:
        parsed_date = current_application_date()
        attendance_date = parsed_date.isoformat()

        attendance_map = {}
        for item in attendance_items:
            if not isinstance(item, dict):
                raise ValueError("Each attendance entry must be an object.")
            student_id = item.get("student_id")
            status = item.get("status")
            if student_id is None or status is None:
                raise ValueError("Each attendance entry must include a student_id and status.")
            if int(student_id) in attendance_map:
                raise ValueError("Each student may appear only once in attendance data.")
            attendance_map[int(student_id)] = status

        all_student_ids = {student["id"] for student in get_students("")}
        if set(attendance_map) != all_student_ids:
            raise ValueError("Attendance must include every active student for the selected date.")

        summary = save_attendance_for_date(attendance_date, attendance_map)
        return jsonify(
            {
                "success": True,
                "message": "Attendance saved successfully.",
                "date": parsed_date.strftime("%d %B %Y"),
                "present": summary["present"],
                "absent": summary["absent"],
                "total": summary["total"],
            }
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:  # pragma: no cover - defensive backend validation
        return jsonify({"error": "Unable to save attendance right now."}), 500


@app.route("/records")
@login_required
def records():
    return render_template("records.html")


@app.route("/api/records/<attendance_date>", methods=["GET"])
@login_required
def get_records(attendance_date):
    try:
        parsed_date = date.fromisoformat(attendance_date)
        if parsed_date.isoformat() != attendance_date:
            raise ValueError
    except ValueError:
        return jsonify({"error": "A valid date is required."}), 400

    records = get_attendance_records_for_date(attendance_date)
    if not records:
        return jsonify(
            {
                "date": parsed_date.strftime("%d %B %Y"),
                "has_records": False,
                "records": [],
            }
        )

    summary = {
        "total": total_students(),
        "present": sum(record["status"] == "present" for record in records),
        "absent": sum(record["status"] == "absent" for record in records),
    }
    summary["percentage"] = round(
        (summary["present"] / summary["total"] * 100) if summary["total"] else 0,
        2,
    )
    return jsonify(
        {
            "date": parsed_date.strftime("%d %B %Y"),
            "has_records": True,
            "summary": summary,
            "records": [
                {
                    "roll_number": record["roll_number"],
                    "name": record["name"],
                    "status": record["status"],
                }
                for record in records
            ],
        }
    )


@app.route("/students", methods=["GET", "POST"])
@login_required
def students():
    message = None
    message_type = "info"
    search_term = request.args.get("q", "").strip()

    if request.method == "POST":
        uploaded_file = request.files.get("excel_file")

        if not uploaded_file or uploaded_file.filename == "":
            message = "Please select an Excel file."
            message_type = "error"
        else:
            filename = secure_filename(uploaded_file.filename)
            if not filename.lower().endswith(".xlsx"):
                message = "Invalid Excel format."
                message_type = "error"
            else:
                temp_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                uploaded_file.save(temp_path)
                try:
                    success, import_message, imported_count = import_students_from_excel(temp_path)
                    if success:
                        message = import_message
                        message_type = "success"
                    else:
                        message = import_message
                        message_type = "error"
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

    students_data = get_students(search_term)
    total = total_students()
    return render_template(
        "students.html",
        students=students_data,
        total_students=total,
        search_term=search_term,
        message=message,
        message_type=message_type,
    )


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )