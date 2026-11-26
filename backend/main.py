"""
CCTV Attendance System — FastAPI Backend
========================================
Stack:
  - FastAPI  (async web framework)
  - Neon     (PostgreSQL via psycopg3)
  - Redis    (pub/sub for live WebSocket push)
  - Firebase (authentication / session cookies)
  - Cloudinary (CCTV capture image storage)
  - OpenCV LBPH (face recognition)
  - WebSockets (real-time attendance updates)
"""

import os
import io
import csv
import hmac
import json
import time
import base64
import hashlib
import asyncio
import threading
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Load .env from project root (parent of backend/)
# ---------------------------------------------------------------------------
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import cloudinary
import cloudinary.uploader
from cloudinary.utils import private_download_url
import cv2
import firebase_admin
from firebase_admin import auth as firebase_auth
import numpy as np
import psycopg
from psycopg.rows import dict_row
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

# ---------------------------------------------------------------------------
# Parse CLOUDINARY_URL if individual vars are not set
# Format: cloudinary://api_key:api_secret@cloud_name
# The Cloudinary SDK reads CLOUDINARY_URL automatically — this is a fallback
# for the individual env vars used in health checks.
# ---------------------------------------------------------------------------
def _parse_cloudinary_url():
    url = os.getenv("CLOUDINARY_URL", "")
    if url and url.startswith("cloudinary://"):
        try:
            rest = url[len("cloudinary://"):]
            credentials, cloud_name = rest.rsplit("@", 1)
            api_key, api_secret = credentials.split(":", 1)
            if not os.getenv("CLOUDINARY_CLOUD_NAME"):
                os.environ["CLOUDINARY_CLOUD_NAME"] = cloud_name
            if not os.getenv("CLOUDINARY_API_KEY"):
                os.environ["CLOUDINARY_API_KEY"] = api_key
            if not os.getenv("CLOUDINARY_API_SECRET"):
                os.environ["CLOUDINARY_API_SECRET"] = api_secret
        except Exception:
            pass

_parse_cloudinary_url()
# Cloudinary SDK auto-reads CLOUDINARY_URL — no manual config() needed

from fastapi import (
    FastAPI, Request, Response, HTTPException,
    Depends, WebSocket, UploadFile, File, Form,
    Query, Path as PathParam,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool



# ===========================================================================
# 1. CONFIGURATION
# ===========================================================================

APP_ORIGIN      = os.getenv("APP_ORIGIN", "http://localhost:5173")
COOKIE_SECURE   = os.getenv("COOKIE_SECURE", "false").lower() == "true"
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "28800"))   # 8 hours
TZ              = os.getenv("ATTENDANCE_TIMEZONE", "Asia/Kolkata")
CHANNEL         = "cctv:attendance"
FACE_THRESHOLD  = float(os.getenv("FACE_THRESHOLD", "65"))
CASCADE_PATH    = str(Path(__file__).resolve().parents[1] / "haarcascade_frontalface_default.xml")

# Cloudinary: SDK auto-reads CLOUDINARY_URL env var (no manual config needed)
# If using individual vars, they were already set by _parse_cloudinary_url() above.



# ---------------------------------------------------------------------------
# Camera worker globals
# ---------------------------------------------------------------------------
_camera_stop   = threading.Event()
_camera_lock   = threading.Lock()
_camera_worker: Optional[threading.Thread] = None
_camera_status = "Stopped"


# ===========================================================================
# 2. DATABASE HELPERS  (Neon / PostgreSQL via psycopg3)
# ===========================================================================

def get_db():
    """Return a synchronous psycopg connection to Neon."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise HTTPException(503, "DATABASE_URL not configured")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=8)


def get_redis() -> Redis:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        raise HTTPException(503, "REDIS_URL not configured")
    return Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5, decode_responses=True)


async def get_async_redis() -> AsyncRedis:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        raise HTTPException(503, "REDIS_URL not configured")
    return AsyncRedis.from_url(url, decode_responses=True)


def run_migrations():
    """Create all tables if they do not exist yet."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cctv_employee (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                department  TEXT DEFAULT '',
                designation TEXT DEFAULT '',
                phone       TEXT DEFAULT '',
                email       TEXT DEFAULT '',
                joining_date DATE,
                status      TEXT DEFAULT 'Active',
                photo_url   TEXT DEFAULT '',
                samples     BYTEA[] NOT NULL DEFAULT ARRAY[]::BYTEA[],
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cctv_event (
                id          BIGSERIAL PRIMARY KEY,
                employee_id TEXT REFERENCES cctv_employee(id) ON DELETE SET NULL,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                day         DATE NOT NULL,
                direction   TEXT CHECK(direction IN ('in','out')),
                image_url   TEXT NOT NULL DEFAULT '',
                public_id   TEXT DEFAULT '',
                UNIQUE(employee_id, day, direction)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id          BIGSERIAL PRIMARY KEY,
                uid         TEXT NOT NULL,
                action      TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cctv_admin (
                uid         TEXT PRIMARY KEY,
                email       TEXT DEFAULT '',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)


# ===========================================================================
# 3. FIREBASE AUTH HELPERS
# ===========================================================================

_fb_lock = threading.Lock()


def _has_firebase_credentials() -> bool:
    sa_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "")
    gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    return bool((sa_path and Path(sa_path).exists()) or (gac and Path(gac).exists()))


def get_firebase_app():
    with _fb_lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            sa_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "")
            project_id = os.getenv("FIREBASE_PROJECT_ID", "")
            if sa_path and Path(sa_path).exists():
                from firebase_admin import credentials
                cred = credentials.Certificate(sa_path)
                return firebase_admin.initialize_app(cred, {"projectId": project_id})
            # Fall back to ADC / env-based credentials
            return firebase_admin.initialize_app(options={"projectId": project_id})


def _session_secret() -> bytes:
    raw = (
        os.getenv("SESSION_SECRET")
        or os.getenv("CLOUDINARY_API_SECRET")
        or os.getenv("DATABASE_URL")
        or "cctv-attendance-fallback-secret"
    )
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _sign_local_session(uid: str, email: str) -> str:
    payload = json.dumps({
        "uid": uid,
        "email": email,
        "exp": int(time.time()) + SESSION_MAX_AGE,
    }, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(payload).decode("ascii")
    sig = hmac.new(_session_secret(), b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"local.{b64}.{sig}"


def _verify_local_session(cookie: str) -> Optional[dict]:
    if not cookie.startswith("local."):
        return None
    parts = cookie.split(".", 2)
    if len(parts) != 3:
        raise HTTPException(401, "Invalid session")
    _, b64, sig = parts
    expected = hmac.new(_session_secret(), b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401, "Invalid session signature")
    try:
        claims = json.loads(base64.urlsafe_b64decode(b64.encode("ascii")).decode("utf-8"))
    except Exception:
        raise HTTPException(401, "Invalid session payload")
    if time.time() > claims.get("exp", 0):
        raise HTTPException(401, "Session expired — please sign in again")
    return claims


def _check_admin_uid(uid: str, email: str = ""):
    admin_uids = [u.strip() for u in os.getenv("ADMIN_UIDS", "").split(",") if u.strip()]
    if admin_uids:
        if uid not in admin_uids:
            raise HTTPException(403, "Administrator access required")
        return

    # If ADMIN_UIDS is not set in .env, use cctv_admin table in Neon
    # and auto-enroll the very first user who registers/logs in.
    with get_db() as conn:
        rows = conn.execute("SELECT uid FROM cctv_admin").fetchall()
        if not rows:
            conn.execute(
                "INSERT INTO cctv_admin (uid, email) VALUES (%s, %s) ON CONFLICT (uid) DO NOTHING",
                (uid, email),
            )
            return
        if not any(r["uid"] == uid for r in rows):
            raise HTTPException(403, "Administrator access required")


def verify_session_cookie(cookie: Optional[str]) -> dict:
    if not cookie:
        raise HTTPException(401, "Please sign in")
    claims = _verify_local_session(cookie)
    if claims is None:
        try:
            claims = firebase_auth.verify_session_cookie(
                cookie, check_revoked=True, app=get_firebase_app()
            )
        except Exception:
            raise HTTPException(401, "Session expired — please sign in again")
    _check_admin_uid(claims["uid"], claims.get("email", ""))
    return claims


def admin_user(request: Request) -> dict:
    """FastAPI dependency — verifies the Firebase session cookie."""
    return verify_session_cookie(request.cookies.get("session"))


# ===========================================================================
# 4. FACE RECOGNITION HELPERS
# ===========================================================================

def load_cascade():
    if not Path(CASCADE_PATH).exists():
        raise HTTPException(503, "Haar cascade file not found on server")
    cascade = cv2.CascadeClassifier(CASCADE_PATH)
    if cascade.empty():
        raise HTTPException(503, "Failed to load Haar cascade")
    return cascade


def extract_faces(frame: np.ndarray, cascade) -> list[np.ndarray]:
    """Return 200×200 gray crops of every face found in frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    rects = cascade.detectMultiScale(gray, 1.2, 5, minSize=(60, 60))
    crops = []
    if len(rects):
        for (x, y, w, h) in rects:
            crops.append(cv2.resize(gray[y:y + h, x:x + w], (200, 200)))
    return crops


def decode_image(raw: bytes) -> Optional[np.ndarray]:
    buf = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


# ===========================================================================
# 5. CAMERA WORKER  (runs in background thread)
# ===========================================================================

def _record_attendance(employee_id: str, crop: np.ndarray, direction: str):
    """Upload crop to Cloudinary, insert attendance event, publish to Redis."""
    global _camera_status
    try:
        with get_db() as conn:
            row = conn.execute(
                """
                INSERT INTO cctv_event (employee_id, day, direction, image_url)
                VALUES (%s, (NOW() AT TIME ZONE %s)::DATE, %s, '')
                ON CONFLICT DO NOTHING RETURNING id
                """,
                (employee_id, TZ, direction),
            ).fetchone()
            if not row:
                return  # already recorded today

            # Upload capture to Cloudinary
            _, buf = cv2.imencode(".jpg", crop)
            upload_result = cloudinary.uploader.upload(
                buf.tobytes(),
                folder="cctv-attendance",
                type="authenticated",
                resource_type="image",
            )
            conn.execute(
                "UPDATE cctv_event SET image_url=%s, public_id=%s WHERE id=%s",
                (upload_result["secure_url"], upload_result["public_id"], row["id"]),
            )

        # Notify all WebSocket clients
        r = get_redis()
        r.publish(CHANNEL, "refresh")
        r.close()

    except Exception as exc:
        print(f"[RECORD ERROR] {exc}")


def _camera_capture_loop():
    global _camera_status
    cap = None
    try:
        run_migrations()

        # Load all employees + build LBPH model
        with get_db() as conn:
            employees = conn.execute(
                "SELECT id, samples FROM cctv_employee WHERE status='Active' ORDER BY id"
            ).fetchall()

        if not employees:
            _camera_status = "No active employees enrolled"
            return

        images, int_labels = [], []
        for i, emp in enumerate(employees):
            for sample in emp["samples"]:
                images.append(cv2.imdecode(np.frombuffer(bytes(sample), np.uint8), 0))
                int_labels.append(i)

        model = cv2.face.LBPHFaceRecognizer_create()
        model.train(images, np.array(int_labels, np.int32))

        cascade = load_cascade()

        rtsp_url = os.getenv("TAPO_RTSP_URL", "")
        if not rtsp_url:
            _camera_status = "TAPO_RTSP_URL not configured"
            return

        cap = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000],
        )
        if not cap.isOpened():
            _camera_status = "Cannot connect to RTSP stream"
            return

        streak: dict[int, int] = {}
        recorded: set[int] = set()
        current_day: Optional[date] = None
        direction = os.getenv("CAMERA_DIRECTION", "in")

        while not _camera_stop.is_set():
            ok, frame = cap.read()
            if not ok:
                _camera_status = "Camera disconnected — retrying…"
                cap.release()
                time.sleep(3)
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                continue

            _camera_status = "Live"
            today = datetime.now(ZoneInfo(TZ)).date()
            if today != current_day:
                recorded.clear()
                current_day = today

            seen: dict[int, np.ndarray] = {}
            for crop in extract_faces(frame, cascade):
                label, distance = model.predict(crop)
                if distance <= FACE_THRESHOLD:
                    seen[label] = crop

            streak = {lb: streak.get(lb, 0) + 1 for lb in seen}
            for lb, count in streak.items():
                if count >= 5 and lb not in recorded:
                    emp_id = employees[lb]["id"]
                    _record_attendance(emp_id, seen[lb], direction)
                    recorded.add(lb)

    except Exception as exc:
        _camera_status = f"Camera error: {type(exc).__name__}: {exc}"
    finally:
        if cap is not None:
            cap.release()
        if _camera_stop.is_set():
            _camera_status = "Stopped"


# ===========================================================================
# 6. FASTAPI APP SETUP
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: run DB migrations
    try:
        await run_in_threadpool(run_migrations)
    except Exception as exc:
        print(f"[STARTUP] DB migration warning: {exc}")
    yield
    # Shutdown: stop camera worker
    _camera_stop.set()
    if _camera_worker and _camera_worker.is_alive():
        await run_in_threadpool(_camera_worker.join, 10)


app = FastAPI(title="CCTV Attendance System", version="2.0.0", lifespan=lifespan)

# CORS — allow the React Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[APP_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# 7. AUTHENTICATION ENDPOINTS
# ===========================================================================

class LoginPayload(BaseModel):
    token: str


@app.get("/api/config")
def get_firebase_config():
    """Return public Firebase web config (safe to expose)."""
    return {
        "apiKey":           os.getenv("VITE_FIREBASE_API_KEY", ""),
        "authDomain":       os.getenv("VITE_FIREBASE_AUTH_DOMAIN", ""),
        "projectId":        os.getenv("VITE_FIREBASE_PROJECT_ID", os.getenv("FIREBASE_PROJECT_ID", "")),
        "storageBucket":    os.getenv("VITE_FIREBASE_STORAGE_BUCKET", ""),
        "messagingSenderId":os.getenv("VITE_FIREBASE_MESSAGING_SENDER_ID", ""),
        "appId":            os.getenv("VITE_FIREBASE_APP_ID", ""),
    }


@app.post("/api/session")
def login(body: LoginPayload, response: Response):
    """Exchange a Firebase ID token for a server-side session cookie."""
    has_creds = _has_firebase_credentials()
    try:
        claims = firebase_auth.verify_id_token(
            body.token, app=get_firebase_app(), check_revoked=has_creds
        )
    except Exception as exc:
        print(f"[AUTH] verify_id_token failed: {type(exc).__name__}: {exc}")
        raise HTTPException(401, "Firebase sign-in failed — invalid token")

    _check_admin_uid(claims["uid"], claims.get("email", ""))

    # Reject tokens from sign-ins that are more than 5 minutes old
    if time.time() - claims["auth_time"] > 300:
        raise HTTPException(401, "Sign in again to continue")

    if has_creds:
        session_cookie = firebase_auth.create_session_cookie(
            body.token,
            expires_in=timedelta(seconds=SESSION_MAX_AGE),
            app=get_firebase_app(),
        )
    else:
        # Fallback when FIREBASE_SERVICE_ACCOUNT_PATH is not configured
        session_cookie = _sign_local_session(claims["uid"], claims.get("email", ""))

    response.set_cookie(
        "session",
        session_cookie,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=SESSION_MAX_AGE,
    )

    # Log the activity
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
                (claims["uid"], "LOGIN", f"User {claims.get('email', claims['uid'])} signed in"),
            )
    except Exception:
        pass

    return {"ok": True}


@app.delete("/api/session")
def logout(response: Response, user: dict = Depends(admin_user)):
    """Revoke the Firebase session cookie."""
    try:
        firebase_auth.revoke_refresh_tokens(user["uid"], app=get_firebase_app())
    except Exception:
        pass
    response.delete_cookie("session", samesite="strict")
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(admin_user)):
    """Return the current authenticated user's uid and email."""
    return {"uid": user["uid"], "email": user.get("email", "")}


# ===========================================================================
# 8. EMPLOYEE ENDPOINTS
# ===========================================================================

@app.get("/api/employees")
def list_employees(
    q: str = Query("", description="Search by name or ID"),
    status: str = Query("Active", description="Filter by status"),
    _: dict = Depends(admin_user),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, department, designation, phone, email,
                   joining_date, status, photo_url, created_at
            FROM cctv_employee
            WHERE (%s = '' OR name ILIKE %s OR id ILIKE %s)
              AND (%s = 'all' OR status = %s)
            ORDER BY name
            """,
            (q, f"%{q}%", f"%{q}%", status.lower(), status),
        ).fetchall()
    return rows


@app.get("/api/employees/{employee_id}")
def get_employee(
    employee_id: str = PathParam(...),
    _: dict = Depends(admin_user),
):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM cctv_employee WHERE id = %s", (employee_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Employee not found")
    return row


@app.post("/api/employees", status_code=201)
def enroll_employee(
    id: str = Form(..., min_length=1, max_length=80),
    name: str = Form(..., min_length=1, max_length=160),
    department: str = Form(""),
    designation: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    joining_date: str = Form(""),
    photos: list[UploadFile] = File(...),
    user: dict = Depends(admin_user),
):
    """Register a new employee with 3–10 face training photos."""
    if not 3 <= len(photos) <= 10:
        raise HTTPException(422, "Choose between 3 and 10 face photos")

    cascade = load_cascade()
    samples: list[bytes] = []
    photo_url = ""

    for i, photo in enumerate(photos):
        raw = photo.file.read(5_000_001)
        if not raw or len(raw) > 5_000_000:
            raise HTTPException(422, "Each photo must be under 5 MB")
        frame = decode_image(raw)
        if frame is None:
            raise HTTPException(422, f"Photo {i + 1} could not be decoded")

        crops = extract_faces(frame, cascade)
        if len(crops) != 1:
            raise HTTPException(422, f"Photo {i + 1} must show exactly one clear face")

        # Encode face crop as PNG bytes for storage in Neon
        _, buf = cv2.imencode(".png", crops[0])
        samples.append(buf.tobytes())

        # Upload the first photo to Cloudinary as the profile picture
        if i == 0:
            upload = cloudinary.uploader.upload(
                raw,
                folder="cctv-employees",
                type="authenticated",
                resource_type="image",
            )
            photo_url = upload.get("secure_url", "")

    # Parse joining_date
    jd = None
    if joining_date:
        try:
            jd = datetime.strptime(joining_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(422, "joining_date must be YYYY-MM-DD")

    with get_db() as conn:
        result = conn.execute(
            """
            INSERT INTO cctv_employee
                (id, name, department, designation, phone, email, joining_date, photo_url, samples)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING RETURNING id
            """,
            (id, name, department, designation, phone, email, jd, photo_url, samples),
        ).fetchone()

    if not result:
        raise HTTPException(409, "Employee ID already exists")

    # Log
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
                (user["uid"], "ENROLL_EMPLOYEE", f"Enrolled employee {id} ({name})"),
            )
    except Exception:
        pass

    return {"ok": True, "id": id}


@app.put("/api/employees/{employee_id}/status")
def update_employee_status(
    employee_id: str = PathParam(...),
    status: str = Form(...),
    user: dict = Depends(admin_user),
):
    if status not in ("Active", "Inactive"):
        raise HTTPException(422, "status must be 'Active' or 'Inactive'")
    with get_db() as conn:
        result = conn.execute(
            "UPDATE cctv_employee SET status=%s WHERE id=%s RETURNING id",
            (status, employee_id),
        ).fetchone()
    if not result:
        raise HTTPException(404, "Employee not found")
    return {"ok": True}


@app.delete("/api/employees/{employee_id}")
def delete_employee(
    employee_id: str = PathParam(...),
    user: dict = Depends(admin_user),
):
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM cctv_employee WHERE id=%s RETURNING id", (employee_id,)
        ).fetchone()
    if not result:
        raise HTTPException(404, "Employee not found")
    return {"ok": True}


# ===========================================================================
# 9. CAMERA CONTROL ENDPOINTS
# ===========================================================================

@app.get("/api/camera/status")
def camera_status(_: dict = Depends(admin_user)):
    return {"status": _camera_status}


@app.post("/api/camera/{action}")
def camera_control(
    action: str = PathParam(...),
    _: dict = Depends(admin_user),
):
    global _camera_worker, _camera_status

    required_env = ["DATABASE_URL", "REDIS_URL", "CLOUDINARY_CLOUD_NAME",
                    "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "TAPO_RTSP_URL"]

    with _camera_lock:
        if action == "stop":
            _camera_stop.set()
            _camera_status = "Stopping…"

        elif action == "start":
            missing = [k for k in required_env if not os.getenv(k)]
            if missing:
                raise HTTPException(503, f"Missing environment variables: {', '.join(missing)}")

            if os.getenv("CAMERA_DIRECTION") not in ("in", "out"):
                raise HTTPException(422, "Set CAMERA_DIRECTION to 'in' or 'out' in .env")

            if _camera_worker and _camera_worker.is_alive():
                return {"status": _camera_status, "message": "Camera already running"}

            _camera_stop.clear()
            _camera_status = "Connecting…"
            _camera_worker = threading.Thread(target=_camera_capture_loop, daemon=True)
            _camera_worker.start()

        else:
            raise HTTPException(404, f"Unknown action '{action}'. Use 'start' or 'stop'")

    return {"status": _camera_status}


# ===========================================================================
# 10. ATTENDANCE / EVENTS ENDPOINTS
# ===========================================================================

@app.get("/api/attendance")
def list_attendance(
    start_date: str = Query(str(date.today()), description="YYYY-MM-DD"),
    end_date: str = Query(str(date.today()), description="YYYY-MM-DD"),
    employee_id: str = Query("", description="Filter by employee ID"),
    direction: str = Query("", description="'in' or 'out'"),
    _: dict = Depends(admin_user),
):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT e.id, p.name, e.employee_id, e.occurred_at, e.day,
                   e.direction, e.image_url
            FROM cctv_event e
            JOIN cctv_employee p ON p.id = e.employee_id
            WHERE e.day BETWEEN %s AND %s
              AND (%s = '' OR e.employee_id = %s)
              AND (%s = '' OR e.direction = %s)
            ORDER BY e.occurred_at DESC
            LIMIT 500
            """,
            (start_date, end_date, employee_id, employee_id, direction, direction),
        ).fetchall()
    return rows


@app.get("/api/dashboard")
def dashboard(_: dict = Depends(admin_user)):
    """Combined dashboard data: recent events, employee list, camera status."""
    with get_db() as conn:
        events = conn.execute(
            """
            SELECT e.id, p.name, e.employee_id, e.occurred_at,
                   e.direction, e.image_url
            FROM cctv_event e
            JOIN cctv_employee p ON p.id = e.employee_id
            ORDER BY e.id DESC LIMIT 200
            """
        ).fetchall()
        employees = conn.execute(
            "SELECT id, name, status FROM cctv_employee ORDER BY name"
        ).fetchall()
        today = datetime.now(ZoneInfo(TZ)).date().isoformat()
        present_today = conn.execute(
            "SELECT COUNT(DISTINCT employee_id) AS cnt FROM cctv_event WHERE day = %s AND direction = 'in'",
            (today,),
        ).fetchone()
        total_active = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cctv_employee WHERE status = 'Active'"
        ).fetchone()

    return {
        "employees": employees,
        "events": events,
        "camera": _camera_status,
        "stats": {
            "present_today": present_today["cnt"] if present_today else 0,
            "total_active": total_active["cnt"] if total_active else 0,
            "today": today,
        },
    }


@app.get("/api/events/{event_id}/snapshot")
def snapshot(
    event_id: int = PathParam(...),
    _: dict = Depends(admin_user),
):
    """Redirect to a short-lived signed Cloudinary URL for the capture image."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT public_id FROM cctv_event WHERE id = %s", (event_id,)
        ).fetchone()
    if not row or not row["public_id"]:
        raise HTTPException(404, "Snapshot not found")

    url = private_download_url(
        row["public_id"],
        "jpg",
        type="authenticated",
        expires_at=int(time.time()) + 60,
    )
    return RedirectResponse(url, headers={"Cache-Control": "no-store"})


# ===========================================================================
# 11. REPORTS ENDPOINT (CSV export)
# ===========================================================================

@app.get("/api/reports/export")
def export_csv(
    start_date: str = Query(str(date.today())),
    end_date: str = Query(str(date.today())),
    _: dict = Depends(admin_user),
):
    """Download attendance as a CSV file."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT p.name, e.employee_id, e.day, e.direction,
                   e.occurred_at AT TIME ZONE %s AS local_time
            FROM cctv_event e
            JOIN cctv_employee p ON p.id = e.employee_id
            WHERE e.day BETWEEN %s AND %s
            ORDER BY e.day DESC, p.name
            """,
            (TZ, start_date, end_date),
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Employee ID", "Date", "Direction", "Time"])
    for r in rows:
        t = r["local_time"]
        writer.writerow([
            r["name"], r["employee_id"], str(r["day"]),
            r["direction"], t.strftime("%H:%M:%S") if t else "",
        ])
    output.seek(0)

    filename = f"attendance_{start_date}_{end_date}.csv"
    return StreamingResponse(
        iter([output.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===========================================================================
# 12. TRAIN FACE MODEL ENDPOINT
# ===========================================================================

@app.post("/api/admin/train")
def train_face_model(_: dict = Depends(admin_user)):
    """Re-train LBPH model from the faces stored in Neon (non-blocking)."""
    try:
        with get_db() as conn:
            employees = conn.execute(
                "SELECT id, samples FROM cctv_employee WHERE status='Active' ORDER BY id"
            ).fetchall()

        if not employees:
            raise HTTPException(422, "No active employees to train from")

        images, labels = [], []
        for i, emp in enumerate(employees):
            for sample in emp["samples"]:
                img = cv2.imdecode(np.frombuffer(bytes(sample), np.uint8), 0)
                if img is not None:
                    images.append(img)
                    labels.append(i)

        if not images:
            raise HTTPException(422, "No valid face samples found")

        model = cv2.face.LBPHFaceRecognizer_create()
        model.train(images, np.array(labels, np.int32))

        return {
            "ok": True,
            "employees_trained": len(employees),
            "total_samples": len(images),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Training failed: {exc}")


# ===========================================================================
# 13. WEBSOCKET — REAL-TIME ATTENDANCE PUSH
# ===========================================================================

@app.websocket("/api/live")
async def live_ws(ws: WebSocket):
    """
    WebSocket endpoint — sends 'refresh' whenever a new attendance event
    is recorded (via Redis pub/sub) and 'ping' as a keepalive.
    """
    # Verify origin
    if ws.headers.get("origin") != APP_ORIGIN:
        await ws.close(code=1008)
        return

    # Verify session cookie
    try:
        claims = await run_in_threadpool(
            verify_session_cookie, ws.cookies.get("session")
        )
    except HTTPException:
        await ws.close(code=1008)
        return

    await ws.accept()

    redis = await get_async_redis()
    try:
        async with redis.pubsub() as sub:
            await sub.subscribe(CHANNEL)
            while time.time() < claims["exp"]:
                try:
                    msg = await asyncio.wait_for(
                        sub.get_message(ignore_subscribe_messages=True), timeout=15
                    )
                    await ws.send_text("refresh" if msg else "ping")
                except asyncio.TimeoutError:
                    await ws.send_text("ping")
                except Exception:
                    break
    except Exception:
        pass
    finally:
        await redis.aclose()


# ===========================================================================
# 14. SERVE REACT VITE FRONTEND (production)
# ===========================================================================

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
