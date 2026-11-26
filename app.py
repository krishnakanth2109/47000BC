
import os
import io
import csv
import json
import base64
import uuid
import sqlite3
import xml.etree.ElementTree as ET

from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, Response, jsonify, make_response, redirect,
    render_template, request, send_from_directory,
    url_for, session
)

from werkzeug.utils import secure_filename

from db import (
    initialize_database,
    authenticate_user,
    create_user,
    add_activity_log
)

from face_recognition import (
    start_camera_worker,
    stop_camera_worker,
    generate_video_frames,
    get_camera_status
)


# ============================================================
# 1. APPLICATION CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EMPLOYEE_FOLDER = os.path.join(BASE_DIR, "employees")
TRAINING_FOLDER = os.path.join(EMPLOYEE_FOLDER, "training_photos")
DATABASE_FOLDER = os.path.join(BASE_DIR, "database")
DATABASE = os.path.join(DATABASE_FOLDER, "attendance.db")
DOCUMENT_FOLDER = os.path.join(BASE_DIR, "employee_documents")

os.makedirs(EMPLOYEE_FOLDER, exist_ok=True)
os.makedirs(TRAINING_FOLDER, exist_ok=True)
os.makedirs(DATABASE_FOLDER, exist_ok=True)
os.makedirs(DOCUMENT_FOLDER, exist_ok=True)

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY",
    ""
)

app.config["UPLOAD_FOLDER"] = EMPLOYEE_FOLDER
app.config["DOCUMENT_FOLDER"] = DOCUMENT_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "FLASK_COOKIE_SECURE", "0"
).strip().lower() in ("1", "true", "yes")
if not app.config["SECRET_KEY"]:
    app.config["SECRET_KEY"] = os.urandom(32).hex()


# ============================================================
# 2. DATABASE CONNECTION
# ============================================================

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize_app_database():
    initialize_database()
    print("Database initialized successfully.")


# ============================================================
# 3. COMMON HELPERS
# ============================================================

def valid_iso_date(value, fallback=None):
    value = value or fallback or date.today().isoformat()

    try:
        date.fromisoformat(value)
        return value
    except (TypeError, ValueError):
        return None


def valid_month(value):
    try:
        datetime.strptime(value, "%Y-%m")
        return True
    except (TypeError, ValueError):
        return False


def json_error(message, status=400):
    return jsonify({
        "success": False,
        "error": message
    }), status


def log_activity(user_id, action, description):
    try:
        add_activity_log(
            user_id=user_id,
            action=action,
            description=description
        )
    except Exception:
        app.logger.exception("Activity log could not be saved.")


def get_logged_in_user():
    return session.get("user")


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not get_logged_in_user():
            return json_error("Please log in first.", 401)
        return function(*args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            user = get_logged_in_user()

            if not user:
                return json_error("Please log in first.", 401)

            if user.get("role") not in allowed_roles:
                return json_error(
                    "You do not have permission to perform this action.",
                    403
                )

            return function(*args, **kwargs)
        return wrapper
    return decorator


def admin_or_manager_required(function):
    """Apply the common management role guard to a page/API view."""
    return role_required("Admin", "Manager")(function)


def get_employee_name(employee_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ============================================================
# 4. DATABASE STARTUP
# ============================================================

def create_table():
    initialize_app_database()


@app.route("/api/admin/train-face-model", methods=["POST"])
@role_required("Admin", "Manager")
def api_train_face_model():
    try:
        from face_recognition import train_model
        train_model()
    except Exception as error:
        app.logger.exception("Face model training failed.")
        return json_error(str(error), 400)

    user = get_logged_in_user()
    log_activity(user["user_id"], "TRAIN_FACE_MODEL", "Face model retrained.")
    return jsonify({"success": True, "message": "Face model trained successfully."})


# ============================================================
# 5. LOGIN AND USER MANAGEMENT
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return jsonify({
            "message": "Submit username and password using POST /login."
        })

    payload = request.get_json(silent=True) or request.form

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    if not username or not password:
        return json_error("Username and password are required.")

    user = authenticate_user(username, password)

    if not user:
        return json_error("Invalid username or password.", 401)

    user_data = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "employee_id": user["employee_id"]
    }

    session["user"] = user_data

    log_activity(
        user_data["user_id"],
        "LOGIN",
        f"{username} logged in."
    )

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": user_data
    })


@app.route("/logout", methods=["POST"])
def logout():
    user = get_logged_in_user()

    if user:
        log_activity(
            user.get("user_id"),
            "LOGOUT",
            f"{user.get('username')} logged out."
        )

    session.clear()

    return jsonify({
        "success": True,
        "message": "Logged out successfully."
    })


@app.route("/api/me")
@login_required
def api_current_user():
    return jsonify({
        "success": True,
        "user": get_logged_in_user()
    })


@app.route("/api/users", methods=["POST"])
@role_required("Admin")
def api_create_user():
    payload = request.get_json(silent=True) or {}

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "")).strip()
    employee_id = payload.get("employee_id") or None

    if not username or not password:
        return json_error("Username and password are required.")

    if role not in ("Admin", "Manager", "Employee"):
        return json_error("Invalid user role.")

    if role == "Employee" and not employee_id:
        return json_error("Employee ID is required for employee users.")

    try:
        create_user(
            username=username,
            password=password,
            role=role,
            employee_id=employee_id
        )
    except Exception as error:
        return json_error(str(error), 400)

    user = get_logged_in_user()

    log_activity(
        user.get("user_id"),
        "CREATE_USER",
        f"Created user {username} with role {role}."
    )

    return jsonify({
        "success": True,
        "message": "User created successfully."
    }), 201


# ============================================================
# 6. FIRST ADMIN SETUP
# ============================================================

@app.route("/api/setup-admin", methods=["POST"])
def setup_admin():
    payload = request.get_json(silent=True) or {}

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    if not username or len(password) < 8:
        return json_error(
            "Username and a password of at least 8 characters are required."
        )

    conn = get_db()

    try:
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        if count > 0:
            conn.rollback()
            return json_error(
                "Admin setup is already completed.",
                403
            )

        created = create_user(
            username=username,
            password=password,
            role="Admin",
            employee_id=None,
            connection=conn
        )
        if not created:
            conn.rollback()
            return json_error("Could not create administrator account.", 409)
        conn.commit()
    except Exception as error:
        conn.rollback()
        app.logger.exception("First administrator setup failed.")
        return json_error(str(error), 400)
    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": "First administrator created. Please log in."
    }), 201


# ============================================================
# 7. EMPLOYEE PHOTO
# ============================================================

@app.route("/employee_photo/<employee_id>")
@login_required
def employee_photo(employee_id):
    conn = get_db()

    try:
        row = conn.execute(
            "SELECT photo FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        return "Employee photo not found.", 404

    filename = os.path.basename(
        str(row[0]).replace("\\", "/")
    )

    if not filename:
        return "Invalid employee photo path.", 404

    if not os.path.isfile(os.path.join(EMPLOYEE_FOLDER, filename)):
        return "Employee photo file does not exist.", 404

    return send_from_directory(EMPLOYEE_FOLDER, filename)


# ============================================================
# 8. HOME PAGE
# ============================================================

@app.route("/")
@admin_or_manager_required
def home():
    return render_template("register.html")


# ============================================================
# 9. EMPLOYEE REGISTRATION
# ============================================================

@app.route("/register", methods=["POST"])
@admin_or_manager_required
def register():

    employee_id = request.form.get("employee_id", "").strip()
    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    designation = request.form.get("designation", "").strip()
    phone = request.form.get("phone", "").strip()
    joining_date = request.form.get("joining_date", "").strip()

    photo = request.files.get("photo")
    captured_data = request.form.get("captured_photos", "")

    if not all([
        employee_id, name, department,
        designation, phone, joining_date
    ]):
        return "Please fill all employee details.", 400

    if not phone.isdigit() or len(phone) != 10:
        return "Please enter a valid 10-digit phone number.", 400

    try:
        datetime.strptime(joining_date, "%Y-%m-%d")
    except ValueError:
        return "Please enter a valid joining date.", 400

    if not photo or not photo.filename:
        return "Please upload an employee photo.", 400

    safe_employee_id = secure_filename(employee_id)
    safe_original = secure_filename(photo.filename)
    extension = os.path.splitext(safe_original)[1].lower()

    if not safe_employee_id:
        return "Invalid employee ID.", 400

    if extension not in (".jpg", ".jpeg", ".png"):
        return "Upload a JPG, JPEG or PNG photo.", 400

    try:
        captured_photos = json.loads(captured_data)

        if (
            not isinstance(captured_photos, list)
            or not 3 <= len(captured_photos) <= 10
        ):
            return "Capture between 3 and 10 training photos.", 400

        training_images = []

        for image_data in captured_photos:
            if (
                not isinstance(image_data, str)
                or not image_data.startswith("data:image/")
            ):
                return "Invalid camera photo format.", 400

            header, encoded = image_data.split(",", 1)

            if ";base64" not in header:
                return "Invalid image encoding.", 400

            image_bytes = base64.b64decode(
                encoded,
                validate=True
            )

            if not image_bytes or len(image_bytes) > 5 * 1024 * 1024:
                return "Each training photo must be under 5 MB.", 400

            training_images.append(image_bytes)

    except (ValueError, TypeError):
        return "Could not process camera photos.", 400

    unique_id = uuid.uuid4().hex
    filename = f"{safe_employee_id}_{unique_id}{extension}"

    photo_path = os.path.join(
        "employees",
        filename
    ).replace("\\", "/")

    full_photo_path = os.path.join(
        EMPLOYEE_FOLDER,
        filename
    )

    employee_training_folder = os.path.join(
        TRAINING_FOLDER,
        safe_employee_id
    )

    saved_files = []
    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO employees (
                employee_id, name, department, phone,
                photo, designation, joining_date,
                employment_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            employee_id,
            name,
            department,
            phone,
            photo_path,
            designation,
            joining_date,
            "Active"
        ))

        photo.save(full_photo_path)
        saved_files.append(full_photo_path)

        os.makedirs(employee_training_folder, exist_ok=True)

        for index, image_bytes in enumerate(training_images, start=1):
            training_name = (
                f"{safe_employee_id}_{index}_{unique_id}.jpg"
            )

            training_path = os.path.join(
                employee_training_folder,
                training_name
            )

            with open(training_path, "wb") as image_file:
                image_file.write(image_bytes)

            saved_files.append(training_path)

        conn.commit()

    except sqlite3.IntegrityError:
        conn.rollback()

        for path in saved_files:
            if os.path.exists(path):
                os.remove(path)

        return "Employee ID already exists.", 409

    except Exception:
        conn.rollback()

        for path in saved_files:
            if os.path.exists(path):
                os.remove(path)

        app.logger.exception("Employee registration failed.")
        return "Employee registration failed.", 500

    finally:
        conn.close()

    return redirect(url_for("employee_list"))


# ============================================================
# 10. EMPLOYEE DIRECTORY
# ============================================================

@app.route("/employees")
@login_required
def employee_list():
    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT
                employee_id, name, department, phone,
                photo, designation, joining_date,
                employment_status
            FROM employees
            ORDER BY name
        """).fetchall()
    finally:
        conn.close()

    return render_template(
        "employees.html",
        employees=rows
    )


@app.route("/api/employees", methods=["GET"])
@login_required
def api_employees():
    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT
                employee_id, name, department, phone,
                photo, designation, joining_date,
                employment_status
            FROM employees
            ORDER BY name
        """).fetchall()
    finally:
        conn.close()

    keys = [
        "employee_id", "name", "department", "phone",
        "photo", "designation", "joining_date",
        "employment_status"
    ]

    return jsonify([
        dict(zip(keys, row))
        for row in rows
    ])


@app.route("/api/employees/<employee_id>", methods=["GET"])
@login_required
def api_employee_profile(employee_id):
    conn = get_db()

    try:
        row = conn.execute("""
            SELECT *
            FROM employees
            WHERE employee_id = ?
        """, (employee_id,)).fetchone()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(employees)"
            ).fetchall()
        ]
    finally:
        conn.close()

    if not row:
        return json_error("Employee not found.", 404)

    return jsonify(dict(zip(columns, row)))


@app.route("/api/employees/<employee_id>/status", methods=["PUT"])
@role_required("Admin", "Manager")
def update_employee_status(employee_id):
    payload = request.get_json(silent=True) or {}
    status = payload.get("employment_status")

    if status not in ("Active", "Inactive"):
        return json_error(
            "Status must be Active or Inactive."
        )

    conn = get_db()

    try:
        cursor = conn.execute("""
            UPDATE employees
            SET employment_status = ?
            WHERE employee_id = ?
        """, (status, employee_id))

        conn.commit()

        if cursor.rowcount == 0:
            return json_error("Employee not found.", 404)

    finally:
        conn.close()

    user = get_logged_in_user()

    log_activity(
        user["user_id"],
        "EMPLOYEE_STATUS",
        f"Employee {employee_id} changed to {status}."
    )

    return jsonify({
        "success": True,
        "message": "Employee status updated."
    })


# ============================================================
# 11. T A P O  C 5 0 0  CAMERA
# ============================================================

@app.route("/video_feed")
@role_required("Admin", "Manager")
def video_feed():
    return Response(
        generate_video_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )


@app.route("/camera_status")
@role_required("Admin", "Manager")
def camera_status():
    return jsonify(get_camera_status())


@app.route("/start_camera", methods=["POST"])
@role_required("Admin", "Manager")
def start_camera():
    started = start_camera_worker()

    return jsonify({
        "success": True,
        "message": (
            "Camera start requested."
            if started
            else "Camera is already running."
        ),
        **get_camera_status()
    })


@app.route("/stop_camera", methods=["POST"])
@role_required("Admin", "Manager")
def stop_camera():
    status = stop_camera_worker()

    return jsonify({
        "success": True,
        "status": status,
        "message": "Stop requested."
    })


# ============================================================
# 12. ATTENDANCE DASHBOARD
# ============================================================

@app.route("/attendance")
@login_required
def attendance_dashboard():

    today = date.today().isoformat()

    selected_date = valid_iso_date(
        request.args.get("date"),
        today
    )

    if selected_date is None:
        return "Invalid date.", 400

    search_query = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "all").lower()

    allowed_filters = [
        "all", "present", "absent", "late", "inside"
    ]

    if status_filter not in allowed_filters:
        status_filter = "all"

    pattern = f"%{search_query}%"

    conn = get_db()

    try:
        total_employees = conn.execute("""
            SELECT COUNT(*)
            FROM employees
            WHERE COALESCE(employment_status, 'Active') = 'Active'
        """).fetchone()[0]

        present = conn.execute("""
            SELECT COUNT(DISTINCT employee_id)
            FROM attendance
            WHERE date = ?
              AND status = 'Present'
        """, (today,)).fetchone()[0]

        currently_inside = conn.execute("""
            SELECT COUNT(DISTINCT employee_id)
            FROM attendance
            WHERE date = ?
              AND check_in IS NOT NULL
              AND check_out IS NULL
        """, (today,)).fetchone()[0]

        absent = max(0, total_employees - present)

        late_count = conn.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT employee_id
                FROM attendance
                WHERE date = ?
                  AND check_in IS NOT NULL
                  AND status = 'Present'
                GROUP BY employee_id
                HAVING MIN(check_in) > '09:00:00'
            )
        """, (today,)).fetchone()[0]

        query = """
            SELECT
                e.employee_id,
                e.name,
                ? AS attendance_date,
                a.check_in,
                a.check_out,
                a.total_hours,
                CASE
                    WHEN a.id IS NULL THEN 'Absent'
                    ELSE COALESCE(a.status, 'Present')
                END AS attendance_status,
                e.photo
            FROM employees e
            LEFT JOIN attendance a
                ON e.employee_id = a.employee_id
                AND a.date = ?
            WHERE COALESCE(e.employment_status, 'Active') = 'Active'
              AND (
                e.employee_id LIKE ?
                OR e.name LIKE ?
              )
        """

        params = [
            selected_date,
            selected_date,
            pattern,
            pattern
        ]

        if status_filter == "present":
            query += """
                AND a.id IS NOT NULL
                AND a.status = 'Present'
            """

        elif status_filter == "absent":
            query += """
                AND (
                    a.id IS NULL
                    OR a.status = 'Absent'
                )
            """

        elif status_filter == "late":
            query += """
                AND a.check_in > '09:00:00'
                AND a.status = 'Present'
            """

        elif status_filter == "inside":
            query += """
                AND a.check_in IS NOT NULL
                AND a.check_out IS NULL
            """

        query += " ORDER BY e.name"

        records = conn.execute(query, params).fetchall()

    finally:
        conn.close()

    return render_template(
        "attendance.html",
        total_employees=total_employees,
        present=present,
        absent=absent,
        currently_inside=currently_inside,
        late_count=late_count,
        attendance_records=records,
        today=today,
        search_query=search_query,
        selected_date=selected_date,
        status_filter=status_filter
    )


# ============================================================
# 13. DAILY AND MONTHLY REPORT DATA
# ============================================================

def get_report_data(report_type, selected_date, selected_month):

    conn = get_db()

    try:
        if report_type == "monthly":

            rows = conn.execute("""
                SELECT
                    e.employee_id,
                    e.name,
                    COUNT(DISTINCT a.date) AS present_days,
                    ROUND(COALESCE(SUM(a.total_hours), 0), 2),
                    CASE
                        WHEN COUNT(a.id) > 0 THEN 'Present'
                        ELSE 'Absent'
                    END
                FROM employees e
                LEFT JOIN attendance a
                    ON e.employee_id = a.employee_id
                    AND strftime('%Y-%m', a.date) = ?
                    AND a.status = 'Present'
                GROUP BY e.employee_id, e.name
                ORDER BY e.name
            """, (selected_month,)).fetchall()

            headers = [
                "Employee ID",
                "Employee Name",
                "Present Days",
                "Total Working Hours",
                "Status"
            ]

        else:

            rows = conn.execute("""
                SELECT
                    e.employee_id,
                    e.name,
                    ?,
                    a.check_in,
                    a.check_out,
                    a.total_hours,
                    COALESCE(a.status, 'Absent')
                FROM employees e
                LEFT JOIN attendance a
                    ON e.employee_id = a.employee_id
                    AND a.date = ?
                ORDER BY e.name
            """, (
                selected_date,
                selected_date
            )).fetchall()

            headers = [
                "Employee ID",
                "Employee Name",
                "Date",
                "Check-in",
                "Check-out",
                "Total Working Hours",
                "Status"
            ]

        return headers, rows

    finally:
        conn.close()


# ============================================================
# 14. REPORTS PAGE
# ============================================================

@app.route("/reports")
@login_required
def attendance_reports():

    report_type = request.args.get("type", "daily")

    if report_type not in ("daily", "monthly"):
        report_type = "daily"

    selected_date = valid_iso_date(
        request.args.get("date")
    )

    if selected_date is None:
        return "Invalid report date.", 400

    selected_month = request.args.get(
        "month",
        date.today().strftime("%Y-%m")
    )

    if not valid_month(selected_month):
        return "Invalid report month.", 400

    headers, records = get_report_data(
        report_type,
        selected_date,
        selected_month
    )

    return render_template(
        "reports.html",
        report_type=report_type,
        selected_date=selected_date,
        selected_month=selected_month,
        headers=headers,
        records=records
    )


# ============================================================
# 15. CSV EXPORT
# ============================================================

@app.route("/reports/export")
@login_required
def export_attendance_report():

    report_type = request.args.get("type", "daily")

    if report_type not in ("daily", "monthly"):
        report_type = "daily"

    selected_date = valid_iso_date(
        request.args.get("date")
    )

    if selected_date is None:
        return "Invalid report date.", 400

    selected_month = request.args.get(
        "month",
        date.today().strftime("%Y-%m")
    )

    if not valid_month(selected_month):
        return "Invalid report month.", 400

    headers, records = get_report_data(
        report_type,
        selected_date,
        selected_month
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(headers)
    writer.writerows(records)

    response = make_response(
        "\ufeff" + output.getvalue()
    )

    response.headers["Content-Disposition"] = (
        f"attachment; filename={report_type}_attendance_report.csv"
    )

    response.headers["Content-Type"] = (
        "text/csv; charset=utf-8"
    )

    return response


# ============================================================
# 16. XML EXPORT WITH BREAK DETAILS
# ============================================================

@app.route("/reports/export/xml")
@login_required
def export_attendance_xml():

    selected_date = valid_iso_date(
        request.args.get("date")
    )

    if selected_date is None:
        return "Invalid report date.", 400

    conn = get_db()

    try:
        employees = conn.execute("""
            SELECT
                e.employee_id,
                e.name,
                COALESCE(e.department, ''),
                a.date,
                a.check_in,
                a.check_out,
                a.total_hours,
                COALESCE(a.status, 'Absent')
            FROM employees e
            LEFT JOIN attendance a
                ON e.employee_id = a.employee_id
                AND a.date = ?
            ORDER BY e.name
        """, (selected_date,)).fetchall()

        root = ET.Element(
            "CCTVAttendanceReport",
            {
                "date": selected_date,
                "office_opening_time": "09:00",
                "office_closing_time": "18:00",
                "generated_at": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            }
        )

        for row in employees:

            (
                employee_id, name, department,
                row_date, check_in, check_out,
                hours, status
            ) = row

            employee_node = ET.SubElement(root, "Employee")

            fields = [
                ("EmployeeID", employee_id),
                ("EmployeeName", name),
                ("Department", department),
                ("Date", row_date or selected_date),
                ("CheckIn", check_in),
                ("CheckOut", check_out),
                ("RecordedWorkingHours", hours),
                ("AttendanceStatus", status)
            ]

            for tag, value in fields:
                ET.SubElement(employee_node, tag).text = (
                    "" if value is None else str(value)
                )

            breaks = conn.execute("""
                SELECT
                    break_start,
                    break_end,
                    duration_minutes,
                    status
                FROM break_records
                WHERE employee_id = ?
                  AND date = ?
                ORDER BY break_start
            """, (
                employee_id,
                selected_date
            )).fetchall()

            breaks_node = ET.SubElement(
                employee_node,
                "Breaks"
            )

            total_break_minutes = 0.0

            for break_start, break_end, duration, break_status in breaks:

                break_node = ET.SubElement(breaks_node, "Break")

                break_fields = [
                    ("BreakOut", break_start),
                    ("BreakIn", break_end),
                    ("DurationMinutes", duration),
                    ("Status", break_status)
                ]

                for tag, value in break_fields:
                    ET.SubElement(break_node, tag).text = (
                        "" if value is None else str(value)
                    )

                if duration is not None:
                    total_break_minutes += float(duration)

            ET.SubElement(
                employee_node,
                "TotalBreakMinutes"
            ).text = str(round(total_break_minutes, 2))

    finally:
        conn.close()

    xml_data = ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True
    )

    response = make_response(xml_data)

    response.headers["Content-Type"] = (
        "application/xml; charset=utf-8"
    )

    response.headers["Content-Disposition"] = (
        f"attachment; filename=cctv_attendance_{selected_date}.xml"
    )

    return response


# ============================================================
# 17. ATTENDANCE APIs
# ============================================================

@app.route("/api/attendance/daily")
@login_required
def api_daily_attendance():

    selected_date = valid_iso_date(
        request.args.get("date")
    )

    if selected_date is None:
        return json_error("Date must be YYYY-MM-DD.")

    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT
                employee_id, employee_name, date,
                check_in, check_out, total_hours, status
            FROM attendance
            WHERE date = ?
            ORDER BY employee_name
        """, (selected_date,)).fetchall()
    finally:
        conn.close()

    keys = [
        "employee_id", "employee_name", "date",
        "check_in", "check_out", "total_hours", "status"
    ]

    return jsonify([
        dict(zip(keys, row))
        for row in rows
    ])


@app.route("/api/attendance/monthly")
@login_required
def api_monthly_attendance():

    month = request.args.get(
        "month",
        date.today().strftime("%Y-%m")
    )

    if not valid_month(month):
        return json_error("Month must be YYYY-MM.")

    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT
                employee_id,
                employee_name,
                COUNT(DISTINCT date),
                ROUND(COALESCE(SUM(total_hours), 0), 2)
            FROM attendance
            WHERE strftime('%Y-%m', date) = ?
              AND status = 'Present'
            GROUP BY employee_id, employee_name
            ORDER BY employee_name
        """, (month,)).fetchall()
    finally:
        conn.close()

    keys = [
        "employee_id",
        "employee_name",
        "present_days",
        "total_hours"
    ]

    return jsonify([
        dict(zip(keys, row))
        for row in rows
    ])


@app.route("/api/employees/<employee_id>/attendance")
@login_required
def api_employee_history(employee_id):

    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT
                employee_id, employee_name, date,
                check_in, check_out, total_hours, status
            FROM attendance
            WHERE employee_id = ?
            ORDER BY date DESC
        """, (employee_id,)).fetchall()
    finally:
        conn.close()

    keys = [
        "employee_id", "employee_name", "date",
        "check_in", "check_out", "total_hours", "status"
    ]

    return jsonify([
        dict(zip(keys, row))
        for row in rows
    ])


# ============================================================
# 18. MANUAL ATTENDANCE UPDATE
# ============================================================

@app.route("/api/attendance/update", methods=["PUT", "POST"])
@role_required("Admin", "Manager")
def api_update_attendance():

    payload = request.get_json(silent=True) or request.form

    employee_id = str(
        payload.get("employee_id", "")
    ).strip()

    selected_date = valid_iso_date(
        payload.get("date")
    )

    if not employee_id or selected_date is None:
        return json_error(
            "Employee ID and valid date are required."
        )

    check_in = payload.get("check_in") or None
    check_out = payload.get("check_out") or None

    status = payload.get("status", "Present")

    if status not in ("Present", "Absent"):
        return json_error("Invalid attendance status.")

    total_hours = 0.0

    if check_in and check_out:
        try:
            start = datetime.strptime(check_in, "%H:%M:%S")
            end = datetime.strptime(check_out, "%H:%M:%S")

            total_hours = max(
                0,
                (end - start).total_seconds() / 3600
            )
        except ValueError:
            return json_error("Times must use HH:MM:SS format.")

    conn = get_db()

    try:
        employee = conn.execute("""
            SELECT name
            FROM employees
            WHERE employee_id = ?
        """, (employee_id,)).fetchone()

        if not employee:
            return json_error("Employee not found.", 404)

        existing = conn.execute("""
            SELECT id
            FROM attendance
            WHERE employee_id = ?
              AND date = ?
            ORDER BY id DESC
            LIMIT 1
        """, (employee_id, selected_date)).fetchone()

        if existing:
            conn.execute("""
                UPDATE attendance
                SET employee_name = ?,
                    check_in = ?,
                    check_out = ?,
                    total_hours = ?,
                    status = ?
                WHERE id = ?
            """, (
                employee[0], check_in, check_out,
                total_hours, status, existing[0]
            ))
        else:
            conn.execute("""
                INSERT INTO attendance (
                    employee_id, employee_name, date,
                    check_in, check_out, total_hours, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                employee_id, employee[0], selected_date,
                check_in, check_out, total_hours, status
            ))

        conn.commit()

    finally:
        conn.close()

    user = get_logged_in_user()

    log_activity(
        user["user_id"],
        "UPDATE_ATTENDANCE",
        f"Updated attendance for {employee_id} on {selected_date}."
    )

    return jsonify({
        "success": True,
        "message": "Attendance updated."
    })


# ============================================================
# 19. LEAVE MANAGEMENT
# ============================================================

@app.route("/api/leaves", methods=["GET", "POST"])
@login_required
def api_leaves():

    user = get_logged_in_user()

    if request.method == "POST":

        payload = request.get_json(silent=True) or {}

        employee_id = (
            payload.get("employee_id")
            or user.get("employee_id")
        )

        leave_type_id = payload.get("leave_type_id")
        start_date = valid_iso_date(payload.get("start_date"))
        end_date = valid_iso_date(payload.get("end_date"))
        reason = str(payload.get("reason", "")).strip()

        if not all([
            employee_id, leave_type_id,
            start_date, end_date, reason
        ]):
            return json_error("All leave details are required.")

        if end_date < start_date:
            return json_error("End date cannot be before start date.")

        if user["role"] == "Employee" and employee_id != user["employee_id"]:
            return json_error("You can only apply for your own leave.", 403)

        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
            total_days = (end - start).days + 1

            conn = get_db()

            try:
                conn.execute("""
                    INSERT INTO leave_requests (
                        employee_id, leave_type_id,
                        start_date, end_date,
                        total_days, reason, status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'Pending', CURRENT_TIMESTAMP)
                """, (
                    employee_id,
                    leave_type_id,
                    start_date,
                    end_date,
                    total_days,
                    reason
                ))

                conn.commit()

            finally:
                conn.close()

        except sqlite3.Error as error:
            return json_error(str(error))

        log_activity(
            user["user_id"],
            "LEAVE_APPLIED",
            f"Leave requested by {employee_id}."
        )

        return jsonify({
            "success": True,
            "message": "Leave request submitted."
        }), 201

    conn = get_db()

    try:
        if user["role"] == "Employee":
            rows = conn.execute("""
                SELECT *
                FROM leave_requests
                WHERE employee_id = ?
                ORDER BY created_at DESC
            """, (user["employee_id"],)).fetchall()
        else:
            rows = conn.execute("""
                SELECT *
                FROM leave_requests
                ORDER BY created_at DESC
            """).fetchall()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(leave_requests)"
            ).fetchall()
        ]

    finally:
        conn.close()

    return jsonify([
        dict(zip(columns, row))
        for row in rows
    ])


@app.route("/api/leaves/<int:leave_id>/decision", methods=["PUT"])
@role_required("Admin", "Manager")
def api_leave_decision(leave_id):

    payload = request.get_json(silent=True) or {}
    decision = payload.get("status")

    if decision not in ("Approved", "Rejected"):
        return json_error("Decision must be Approved or Rejected.")

    user = get_logged_in_user()
    conn = get_db()

    try:
        cursor = conn.execute("""
            UPDATE leave_requests
            SET status = ?
            WHERE id = ?
              AND status = 'Pending'
        """, (decision, leave_id))

        conn.commit()

        if cursor.rowcount == 0:
            return json_error(
                "Leave request not found or already processed.",
                404
            )

    finally:
        conn.close()

    log_activity(
        user["user_id"],
        "LEAVE_DECISION",
        f"Leave request {leave_id}: {decision}."
    )

    return jsonify({
        "success": True,
        "message": f"Leave {decision.lower()} successfully."
    })


# ============================================================
# 20. SHIFT MANAGEMENT
# ============================================================

@app.route("/api/shifts", methods=["GET", "POST"])
@login_required
def api_shifts():

    user = get_logged_in_user()

    if request.method == "POST":

        if user["role"] not in ("Admin", "Manager"):
            return json_error("Permission denied.", 403)

        payload = request.get_json(silent=True) or {}

        shift_name = str(payload.get("shift_name", "")).strip()
        start_time = payload.get("start_time")
        end_time = payload.get("end_time")

        if not shift_name or not start_time or not end_time:
            return json_error("Shift name and timings are required.")

        try:
            datetime.strptime(start_time, "%H:%M")
            datetime.strptime(end_time, "%H:%M")
        except ValueError:
            return json_error("Shift timings must use HH:MM format.")

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO shifts (
                    shift_name, start_time, end_time
                )
                VALUES (?, ?, ?)
            """, (shift_name, start_time, end_time))

            conn.commit()

        except sqlite3.Error as error:
            return json_error(str(error))

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Shift created."
        }), 201

    conn = get_db()

    try:
        rows = conn.execute(
            "SELECT * FROM shifts ORDER BY shift_name"
        ).fetchall()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(shifts)"
            ).fetchall()
        ]

    finally:
        conn.close()

    return jsonify([
        dict(zip(columns, row))
        for row in rows
    ])


@app.route("/api/employees/<employee_id>/shift", methods=["POST"])
@role_required("Admin", "Manager")
def assign_employee_shift(employee_id):

    payload = request.get_json(silent=True) or {}
    shift_id = payload.get("shift_id")
    effective_date = valid_iso_date(
        payload.get("effective_date")
    )

    if not shift_id or not effective_date:
        return json_error("Shift ID and effective date are required.")

    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO employee_shifts (
                employee_id, shift_id, effective_date
            )
            VALUES (?, ?, ?)
        """, (
            employee_id,
            shift_id,
            effective_date
        ))

        conn.commit()

    except sqlite3.Error as error:
        return json_error(str(error))

    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": "Shift assigned successfully."
    })


# ============================================================
# 21. PAYROLL MANAGEMENT
# ============================================================

@app.route("/api/payroll", methods=["GET", "POST"])
@role_required("Admin", "Manager")
def api_payroll():

    if request.method == "POST":

        payload = request.get_json(silent=True) or {}

        employee_id = payload.get("employee_id")
        month = payload.get("month")
        year = payload.get("year")

        if not employee_id or not month or not year:
            return json_error(
                "Employee ID, month and year are required."
            )

        try:
            month = int(month)
            year = int(year)

            if not 1 <= month <= 12 or not 2000 <= year <= 2100:
                return json_error("Invalid payroll month or year.")

        except (TypeError, ValueError):
            return json_error("Month and year must be numbers.")

        conn = get_db()

        try:
            structure = conn.execute("""
                SELECT *
                FROM salary_structures
                WHERE employee_id = ?
            """, (employee_id,)).fetchone()

            if not structure:
                return json_error(
                    "Salary structure not found for employee.",
                    404
                )

            columns = [
                item[1]
                for item in conn.execute(
                    "PRAGMA table_info(salary_structures)"
                ).fetchall()
            ]

            salary_data = dict(zip(columns, structure))

            basic_salary = float(salary_data.get("basic_salary") or 0)
            allowances = float(salary_data.get("allowances") or 0)
            deductions = float(salary_data.get("deductions") or 0)
            overtime_amount = float(payload.get("overtime_amount") or 0)

            gross_salary = basic_salary + allowances + overtime_amount
            net_salary = gross_salary - deductions

            attendance_days = conn.execute("""
                SELECT COUNT(DISTINCT date)
                FROM attendance
                WHERE employee_id = ?
                  AND strftime('%m', date) = ?
                  AND strftime('%Y', date) = ?
                  AND status = 'Present'
            """, (
                employee_id,
                f"{month:02d}",
                str(year)
            )).fetchone()[0]

            conn.execute("""
                INSERT INTO payroll_records (
                    employee_id, month, year,
                    attendance_days, basic_salary,
                    allowances, overtime_amount,
                    gross_salary, deductions,
                    net_salary, payment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
            """, (
                employee_id,
                month,
                year,
                attendance_days,
                basic_salary,
                allowances,
                overtime_amount,
                gross_salary,
                deductions,
                net_salary
            ))

            conn.commit()

        except sqlite3.Error as error:
            return json_error(str(error))

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Payroll generated.",
            "gross_salary": round(gross_salary, 2),
            "net_salary": round(net_salary, 2),
            "attendance_days": attendance_days
        }), 201

    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT *
            FROM payroll_records
            ORDER BY year DESC, month DESC
        """).fetchall()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(payroll_records)"
            ).fetchall()
        ]

    finally:
        conn.close()

    return jsonify([
        dict(zip(columns, row))
        for row in rows
    ])


@app.route("/api/payroll/<int:payroll_id>/payment", methods=["PUT"])
@role_required("Admin", "Manager")
def update_payroll_payment(payroll_id):

    payload = request.get_json(silent=True) or {}
    payment_status = payload.get("payment_status")

    if payment_status not in ("Pending", "Paid"):
        return json_error(
            "Payment status must be Pending or Paid."
        )

    conn = get_db()

    try:
        cursor = conn.execute("""
            UPDATE payroll_records
            SET payment_status = ?
            WHERE id = ?
        """, (payment_status, payroll_id))

        conn.commit()

        if cursor.rowcount == 0:
            return json_error("Payroll record not found.", 404)

    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": "Payment status updated."
    })


# ============================================================
# 22. SALARY STRUCTURE
# ============================================================

@app.route("/api/salary-structure", methods=["GET", "POST"])
@role_required("Admin", "Manager")
def api_salary_structure():

    if request.method == "POST":

        payload = request.get_json(silent=True) or {}

        employee_id = payload.get("employee_id")

        if not employee_id:
            return json_error("Employee ID is required.")

        try:
            basic_salary = float(payload.get("basic_salary", 0))
            allowances = float(payload.get("allowances", 0))
            deductions = float(payload.get("deductions", 0))

            if min(basic_salary, allowances, deductions) < 0:
                return json_error("Salary amounts cannot be negative.")

        except (ValueError, TypeError):
            return json_error("Salary amounts must be numeric.")

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO salary_structures (
                    employee_id, basic_salary,
                    allowances, deductions
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(employee_id)
                DO UPDATE SET
                    basic_salary = excluded.basic_salary,
                    allowances = excluded.allowances,
                    deductions = excluded.deductions
            """, (
                employee_id,
                basic_salary,
                allowances,
                deductions
            ))

            conn.commit()

        except sqlite3.Error as error:
            return json_error(str(error))

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Salary structure saved."
        }), 201

    conn = get_db()

    try:
        rows = conn.execute(
            "SELECT * FROM salary_structures"
        ).fetchall()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(salary_structures)"
            ).fetchall()
        ]

    finally:
        conn.close()

    return jsonify([
        dict(zip(columns, row))
        for row in rows
    ])


# ============================================================
# 23. EMPLOYEE DOCUMENTS
# ============================================================

@app.route("/api/employees/<employee_id>/documents", methods=["GET", "POST"])
@login_required
def employee_documents(employee_id):

    user = get_logged_in_user()

    if (
        user["role"] == "Employee"
        and user.get("employee_id") != employee_id
    ):
        return json_error("Permission denied.", 403)

    if request.method == "POST":

        if user["role"] not in ("Admin", "Manager"):
            return json_error("Permission denied.", 403)

        uploaded_file = request.files.get("document")
        document_type = request.form.get(
            "document_type", ""
        ).strip()

        if not uploaded_file or not uploaded_file.filename:
            return json_error("Please select a document.")

        if not document_type:
            return json_error("Document type is required.")

        filename = secure_filename(uploaded_file.filename)

        if not filename:
            return json_error("Invalid filename.")

        unique_filename = (
            f"{employee_id}_{uuid.uuid4().hex}_{filename}"
        )

        uploaded_file.save(
            os.path.join(DOCUMENT_FOLDER, unique_filename)
        )

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO employee_documents (
                    employee_id, document_type,
                    file_name, file_path,
                    uploaded_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                employee_id,
                document_type,
                filename,
                unique_filename
            ))

            conn.commit()

        except sqlite3.Error as error:
            return json_error(str(error))

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Document uploaded."
        }), 201

    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT *
            FROM employee_documents
            WHERE employee_id = ?
            ORDER BY uploaded_at DESC
        """, (employee_id,)).fetchall()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(employee_documents)"
            ).fetchall()
        ]

    finally:
        conn.close()

    return jsonify([
        dict(zip(columns, row))
        for row in rows
    ])


@app.route("/employee_documents/<path:filename>")
@login_required
def download_employee_document(filename):
    safe_filename = os.path.basename(filename)
    user = get_logged_in_user()

    conn = get_db()
    try:
        document = conn.execute(
            "SELECT employee_id FROM employee_documents WHERE file_path = ?",
            (safe_filename,)
        ).fetchone()
    finally:
        conn.close()

    if not document:
        return "Document not found.", 404

    if (
        user["role"] == "Employee"
        and user.get("employee_id") != document[0]
    ):
        return json_error("Permission denied.", 403)

    if user["role"] not in ("Admin", "Manager", "Employee"):
        return json_error("Permission denied.", 403)

    return send_from_directory(
        DOCUMENT_FOLDER,
        safe_filename,
        as_attachment=True
    )


# ============================================================
# 24. EMPLOYEE ONBOARDING
# ============================================================

@app.route("/api/onboarding", methods=["GET", "POST"])
@role_required("Admin", "Manager")
def api_onboarding():

    if request.method == "POST":

        payload = request.get_json(silent=True) or {}

        employee_id = payload.get("employee_id")
        task_name = str(payload.get("task_name", "")).strip()
        description = str(payload.get("description", "")).strip()

        if not employee_id or not task_name:
            return json_error(
                "Employee ID and task name are required."
            )

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO onboarding_tasks (
                    employee_id, task_name,
                    description, status
                )
                VALUES (?, ?, ?, 'Pending')
            """, (
                employee_id,
                task_name,
                description
            ))

            conn.commit()

        except sqlite3.Error as error:
            return json_error(str(error))

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Onboarding task created."
        }), 201

    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT *
            FROM onboarding_tasks
            ORDER BY id DESC
        """).fetchall()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(onboarding_tasks)"
            ).fetchall()
        ]

    finally:
        conn.close()

    return jsonify([
        dict(zip(columns, row))
        for row in rows
    ])


@app.route("/api/onboarding/<int:task_id>", methods=["PUT"])
@role_required("Admin", "Manager")
def update_onboarding_task(task_id):

    payload = request.get_json(silent=True) or {}
    status = payload.get("status")

    if status not in ("Pending", "In Progress", "Completed"):
        return json_error("Invalid onboarding task status.")

    conn = get_db()

    try:
        cursor = conn.execute("""
            UPDATE onboarding_tasks
            SET status = ?
            WHERE id = ?
        """, (status, task_id))

        conn.commit()

        if cursor.rowcount == 0:
            return json_error("Task not found.", 404)

    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": "Onboarding task updated."
    })


# ============================================================
# 25. ACTIVITY LOG
# ============================================================

@app.route("/api/activity-logs")
@role_required("Admin", "Manager")
def api_activity_logs():

    conn = get_db()

    try:
        rows = conn.execute("""
            SELECT *
            FROM activity_logs
            ORDER BY id DESC
            LIMIT 200
        """).fetchall()

        columns = [
            item[1]
            for item in conn.execute(
                "PRAGMA table_info(activity_logs)"
            ).fetchall()
        ]

    finally:
        conn.close()

    return jsonify([
        dict(zip(columns, row))
        for row in rows
    ])


# ============================================================
# 26. APPLICATION STARTUP
# ============================================================

if __name__ == "__main__":

    create_table()

    print("=" * 55)
    print("       CCTV EMPLOYEE ATTENDANCE MANAGEMENT")
    print("=" * 55)

    print("Database:", DATABASE)
    print("Registration: http://127.0.0.1:5000/")
    print("Employees:    http://127.0.0.1:5000/employees")
    print("Attendance:   http://127.0.0.1:5000/attendance")
    print("Reports:      http://127.0.0.1:5000/reports")
    print("Camera:       http://127.0.0.1:5000/video_feed")

    print("=" * 55)

    app.run(
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
        debug=False,
        use_reloader=False,
        threaded=True
    )
