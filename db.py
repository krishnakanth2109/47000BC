
import sqlite3
import os
import hashlib
import secrets

from datetime import datetime, date


# =========================================================
# 1. DATABASE SETTINGS
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_FOLDER = os.path.join(BASE_DIR, "database")
DATABASE = os.path.join(DATABASE_FOLDER, "attendance.db")

os.makedirs(DATABASE_FOLDER, exist_ok=True)


# =========================================================
# 2. DATABASE CONNECTION
# =========================================================

def get_connection():

    os.makedirs(DATABASE_FOLDER, exist_ok=True)

    conn = sqlite3.connect(
        DATABASE,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


# =========================================================
# 3. EMPLOYEE TABLE
# =========================================================

def create_employee_table():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employees (

                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                photo TEXT,

                department TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                designation TEXT DEFAULT '',

                joining_date TEXT,
                employment_status TEXT DEFAULT 'Active',

                email TEXT DEFAULT '',
                address TEXT DEFAULT '',
                employment_type TEXT DEFAULT 'Full-time',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("PRAGMA table_info(employees)")

        columns = {
            row["name"] for row in cursor.fetchall()
        }

        migrations = {

            "department":
                "ALTER TABLE employees ADD COLUMN department TEXT DEFAULT ''",

            "phone":
                "ALTER TABLE employees ADD COLUMN phone TEXT DEFAULT ''",

            "photo":
                "ALTER TABLE employees ADD COLUMN photo TEXT",

            "designation":
                "ALTER TABLE employees ADD COLUMN designation TEXT DEFAULT ''",

            "joining_date":
                "ALTER TABLE employees ADD COLUMN joining_date TEXT",

            "employment_status":
                "ALTER TABLE employees ADD COLUMN employment_status TEXT DEFAULT 'Active'",

            "email":
                "ALTER TABLE employees ADD COLUMN email TEXT DEFAULT ''",

            "address":
                "ALTER TABLE employees ADD COLUMN address TEXT DEFAULT ''",

            "employment_type":
                "ALTER TABLE employees ADD COLUMN employment_type TEXT DEFAULT 'Full-time'",

            "created_at":
                "ALTER TABLE employees ADD COLUMN created_at TEXT"
        }

        for column, sql in migrations.items():

            if column not in columns:
                cursor.execute(sql)

        conn.commit()

        print("Employee table ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 4. USER LOGIN AND ROLE MANAGEMENT
# =========================================================

def create_users_table():

    conn = get_connection()

    try:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,

                employee_id TEXT UNIQUE,

                role TEXT NOT NULL
                    CHECK(role IN ('Admin', 'Manager', 'Employee')),

                is_active INTEGER DEFAULT 1,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id)
                    ON DELETE SET NULL
            )
        """)

        conn.commit()

        print("User and role table ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


def hash_password(password):

    if not password:
        raise ValueError("Password cannot be empty.")

    salt = secrets.token_hex(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200000
    ).hex()

    return f"{salt}${password_hash}"


def verify_password(password, stored_hash):

    try:

        salt, original_hash = stored_hash.split("$", 1)

        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            200000
        ).hex()

        return secrets.compare_digest(
            password_hash,
            original_hash
        )

    except (ValueError, AttributeError):
        return False


def create_user(
    username,
    password,
    role,
    employee_id=None,
    connection=None
):

    allowed_roles = [
        "Admin",
        "Manager",
        "Employee"
    ]

    if role not in allowed_roles:
        raise ValueError("Invalid user role.")

    password_hash = hash_password(password)

    owns_connection = connection is None
    conn = connection or get_connection()

    try:

        conn.execute("""
            INSERT INTO users (
                username,
                password_hash,
                employee_id,
                role
            )
            VALUES (?, ?, ?, ?)
        """, (
            username.strip(),
            password_hash,
            str(employee_id) if employee_id else None,
            role
        ))

        conn.commit()

        return True

    except sqlite3.IntegrityError:

        if owns_connection:
            conn.rollback()
        return False

    finally:
        if owns_connection:
            conn.close()


def authenticate_user(username, password):

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                username,
                password_hash,
                employee_id,
                role,
                is_active
            FROM users
            WHERE username = ?
        """, (username.strip(),))

        user = cursor.fetchone()

        if not user:
            return None

        if user["is_active"] != 1:
            return None

        if not verify_password(
            password,
            user["password_hash"]
        ):
            return None

        return {
            "id": user["id"],
            "username": user["username"],
            "employee_id": user["employee_id"],
            "role": user["role"]
        }

    finally:
        conn.close()


def get_all_users():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                username,
                employee_id,
                role,
                is_active,
                created_at
            FROM users
            ORDER BY id DESC
        """)

        return [dict(row) for row in cursor.fetchall()]

    finally:
        conn.close()


# =========================================================
# 5. ATTENDANCE TABLE
# =========================================================

def create_attendance_table():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,
                employee_name TEXT NOT NULL,

                date TEXT NOT NULL,

                check_in TEXT,
                check_out TEXT,

                total_hours REAL DEFAULT 0,
                status TEXT DEFAULT 'Present',

                location_name TEXT,
                latitude REAL,
                longitude REAL,

                camera_id TEXT,
                attendance_source TEXT DEFAULT 'CCTV',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("PRAGMA table_info(attendance)")

        columns = {
            row["name"] for row in cursor.fetchall()
        }

        migrations = {

            "total_hours":
                "ALTER TABLE attendance ADD COLUMN total_hours REAL DEFAULT 0",

            "status":
                "ALTER TABLE attendance ADD COLUMN status TEXT DEFAULT 'Present'",

            "location_name":
                "ALTER TABLE attendance ADD COLUMN location_name TEXT",

            "latitude":
                "ALTER TABLE attendance ADD COLUMN latitude REAL",

            "longitude":
                "ALTER TABLE attendance ADD COLUMN longitude REAL",

            "camera_id":
                "ALTER TABLE attendance ADD COLUMN camera_id TEXT",

            "attendance_source":
                "ALTER TABLE attendance ADD COLUMN attendance_source TEXT DEFAULT 'CCTV'",

            "created_at":
                "ALTER TABLE attendance ADD COLUMN created_at TEXT"
        }

        for column, sql in migrations.items():

            if column not in columns:
                cursor.execute(sql)

        conn.commit()

        print("Attendance table ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 6. BREAK RECORDS TABLE
# =========================================================

def create_break_table():

    conn = get_connection()

    try:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS break_records (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                date TEXT NOT NULL,

                break_start TEXT,
                break_end TEXT,

                duration_minutes REAL DEFAULT 0,

                status TEXT DEFAULT 'Completed'
            )
        """)

        conn.commit()

        print("Break records table ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 7. LEAVE MANAGEMENT
# =========================================================

def create_leave_tables():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leave_types (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                leave_name TEXT NOT NULL UNIQUE,

                description TEXT,

                default_days REAL DEFAULT 0,

                is_paid INTEGER DEFAULT 1
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leave_requests (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                leave_type_id INTEGER,

                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,

                total_days REAL NOT NULL,

                reason TEXT,

                status TEXT DEFAULT 'Pending'
                    CHECK(status IN (
                        'Pending',
                        'Approved',
                        'Rejected',
                        'Cancelled'
                    )),

                manager_comment TEXT,

                reviewed_by INTEGER,

                requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id),

                FOREIGN KEY(leave_type_id)
                    REFERENCES leave_types(id),

                FOREIGN KEY(reviewed_by)
                    REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_leave_balance (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                leave_type_id INTEGER NOT NULL,

                year INTEGER NOT NULL,

                allocated_days REAL DEFAULT 0,
                used_days REAL DEFAULT 0,

                UNIQUE(employee_id, leave_type_id, year),

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id),

                FOREIGN KEY(leave_type_id)
                    REFERENCES leave_types(id)
            )
        """)

        conn.commit()

        print("Leave management tables ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 8. SHIFT MANAGEMENT
# =========================================================

def create_shift_tables():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shifts (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                shift_name TEXT NOT NULL UNIQUE,

                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,

                break_duration_minutes INTEGER DEFAULT 0,

                description TEXT,

                is_active INTEGER DEFAULT 1,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_shifts (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                shift_id INTEGER NOT NULL,

                effective_from TEXT NOT NULL,
                effective_to TEXT,

                assigned_by INTEGER,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id),

                FOREIGN KEY(shift_id)
                    REFERENCES shifts(id),

                FOREIGN KEY(assigned_by)
                    REFERENCES users(id)
            )
        """)

        conn.commit()

        print("Shift management tables ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 9. PAYROLL MANAGEMENT
# =========================================================

def create_payroll_tables():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS salary_structures (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL UNIQUE,

                basic_salary REAL DEFAULT 0,

                hra REAL DEFAULT 0,

                allowances REAL DEFAULT 0,

                other_earnings REAL DEFAULT 0,

                deductions REAL DEFAULT 0,

                effective_from TEXT NOT NULL,

                effective_to TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payroll_records (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                pay_month INTEGER NOT NULL,
                pay_year INTEGER NOT NULL,

                working_days REAL DEFAULT 0,
                present_days REAL DEFAULT 0,
                leave_days REAL DEFAULT 0,

                basic_salary REAL DEFAULT 0,
                hra REAL DEFAULT 0,
                allowances REAL DEFAULT 0,
                other_earnings REAL DEFAULT 0,

                overtime_hours REAL DEFAULT 0,
                overtime_amount REAL DEFAULT 0,

                gross_salary REAL DEFAULT 0,

                deductions REAL DEFAULT 0,

                net_salary REAL DEFAULT 0,

                payment_status TEXT DEFAULT 'Pending'
                    CHECK(payment_status IN (
                        'Pending',
                        'Processed',
                        'Paid'
                    )),

                payment_date TEXT,

                generated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(employee_id, pay_month, pay_year),

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id)
            )
        """)

        conn.commit()

        print("Payroll management tables ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 10. EMPLOYEE DOCUMENT MANAGEMENT
# =========================================================

def create_document_tables():

    conn = get_connection()

    try:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS employee_documents (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                document_name TEXT NOT NULL,

                document_type TEXT,

                file_path TEXT NOT NULL,

                uploaded_by INTEGER,

                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,

                verification_status TEXT DEFAULT 'Pending'
                    CHECK(verification_status IN (
                        'Pending',
                        'Verified',
                        'Rejected'
                    )),

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id),

                FOREIGN KEY(uploaded_by)
                    REFERENCES users(id)
            )
        """)

        conn.commit()

        print("Employee document table ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 11. EMPLOYEE ONBOARDING
# =========================================================

def create_onboarding_tables():

    conn = get_connection()

    try:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS onboarding_tasks (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                task_name TEXT NOT NULL,

                description TEXT,

                assigned_to INTEGER,

                status TEXT DEFAULT 'Pending'
                    CHECK(status IN (
                        'Pending',
                        'In Progress',
                        'Completed'
                    )),

                due_date TEXT,

                completed_at TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(employee_id)
                    REFERENCES employees(employee_id),

                FOREIGN KEY(assigned_to)
                    REFERENCES users(id)
            )
        """)

        conn.commit()

        print("Employee onboarding table ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 12. ACTIVITY AUDIT LOG
# =========================================================

def create_audit_table():

    conn = get_connection()

    try:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER,

                action TEXT NOT NULL,

                description TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE SET NULL
            )
        """)

        conn.commit()

        print("Activity log table ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


def add_activity_log(user_id, action, description=""):

    conn = get_connection()

    try:

        conn.execute("""
            INSERT INTO activity_logs (
                user_id,
                action,
                description
            )
            VALUES (?, ?, ?)
        """, (
            user_id,
            action,
            description
        ))

        conn.commit()

        return True

    except sqlite3.Error:

        conn.rollback()
        return False

    finally:
        conn.close()


# =========================================================
# 13. DATABASE INDEXES
# =========================================================

def create_indexes():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        indexes = [

            """
            CREATE INDEX IF NOT EXISTS idx_attendance_date
            ON attendance(date)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_attendance_employee
            ON attendance(employee_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_attendance_employee_date
            ON attendance(employee_id, date)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_break_employee_date
            ON break_records(employee_id, date)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_leave_employee
            ON leave_requests(employee_id, status)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_shift_employee
            ON employee_shifts(employee_id, effective_from)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_payroll_employee
            ON payroll_records(employee_id, pay_year, pay_month)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_documents_employee
            ON employee_documents(employee_id)
            """
        ]

        for sql in indexes:
            cursor.execute(sql)

        conn.commit()

        print("Database indexes ready.")

    except sqlite3.Error:

        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# 14. REGISTER EMPLOYEE
# Original function signature preserved.
# =========================================================

def register_employee(
    employee_id,
    name,
    photo=None,
    department="",
    phone="",
    designation="",
    joining_date=None,
    employment_status="Active"
):

    conn = get_connection()

    try:

        conn.execute("""
            INSERT INTO employees (
                employee_id,
                name,
                photo,
                department,
                phone,
                designation,
                joining_date,
                employment_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(employee_id),
            name,
            photo,
            department,
            phone,
            designation,
            joining_date,
            employment_status
        ))

        conn.commit()

        print("Employee registered successfully!")

        return True

    except sqlite3.IntegrityError:

        print("Employee ID already exists.")

        return False

    except sqlite3.Error as error:

        conn.rollback()

        print(
            "Employee registration error:",
            error
        )

        return False

    finally:
        conn.close()


# =========================================================
# 15. GET ALL EMPLOYEES
# Original 3-column return format preserved.
# =========================================================

def get_all_employees():

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT employee_id, name, photo
            FROM employees
            ORDER BY employee_id
        """)

        return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# 16. GET EMPLOYEE BY ID
# Original 3-column return format preserved.
# =========================================================

def get_employee(employee_id):

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT employee_id, name, photo
            FROM employees
            WHERE employee_id = ?
        """, (str(employee_id),))

        return cursor.fetchone()

    finally:
        conn.close()


# =========================================================
# 17. GET COMPLETE EMPLOYEE PROFILE
# =========================================================

def get_employee_profile(employee_id):

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                employee_id,
                name,
                department,
                phone,
                designation,
                joining_date,
                employment_status,
                photo,
                email,
                address,
                employment_type
            FROM employees
            WHERE employee_id = ?
        """, (str(employee_id),))

        return cursor.fetchone()

    finally:
        conn.close()


# =========================================================
# 18. GET DAILY ATTENDANCE
# =========================================================

def get_daily_attendance(report_date=None):

    if report_date is None:
        report_date = date.today().isoformat()

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                employee_id,
                employee_name,
                date,
                check_in,
                check_out,
                total_hours,
                status
            FROM attendance
            WHERE date = ?
            ORDER BY employee_id
        """, (report_date,))

        return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# 19. GET ATTENDANCE HISTORY
# =========================================================

def get_attendance_history(employee_id):

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                employee_id,
                employee_name,
                date,
                check_in,
                check_out,
                total_hours,
                status
            FROM attendance
            WHERE employee_id = ?
            ORDER BY date DESC, id DESC
        """, (str(employee_id),))

        return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# 20. GET BREAK HISTORY
# =========================================================

def get_break_history(employee_id, report_date=None):

    conn = get_connection()

    try:

        cursor = conn.cursor()

        if report_date:

            cursor.execute("""
                SELECT
                    employee_id,
                    date,
                    break_start,
                    break_end,
                    duration_minutes,
                    status
                FROM break_records
                WHERE employee_id = ? AND date = ?
                ORDER BY break_start
            """, (
                str(employee_id),
                report_date
            ))

        else:

            cursor.execute("""
                SELECT
                    employee_id,
                    date,
                    break_start,
                    break_end,
                    duration_minutes,
                    status
                FROM break_records
                WHERE employee_id = ?
                ORDER BY date DESC, break_start
            """, (str(employee_id),))

        return cursor.fetchall()

    finally:
        conn.close()


# =========================================================
# 21. INITIALIZE ALL DATABASE TABLES
# =========================================================

def initialize_database():

    print("\n======================================")
    print(" CCTV ATTENDANCE AND HRMS DATABASE")
    print("======================================")

    create_employee_table()

    create_attendance_table()

    create_break_table()

    create_users_table()

    create_leave_tables()

    create_shift_tables()

    create_payroll_tables()

    create_document_tables()

    create_onboarding_tables()

    create_audit_table()

    create_indexes()

    print("\n======================================")
    print("DATABASE INITIALIZED SUCCESSFULLY!")
    print("======================================")

    print("Existing records have been preserved.")

    print("Database location:", DATABASE)


# =========================================================
# 22. PROGRAM START
# =========================================================

if __name__ == "__main__":

    initialize_database()
