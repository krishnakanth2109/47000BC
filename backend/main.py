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
import re
import io
import csv
import hmac
import json
import time
import base64
import hashlib
import asyncio
import threading
import calendar
from datetime import datetime, timedelta, date, time as dt_time
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

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
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
import numpy as np
import psycopg
from psycopg.rows import dict_row
import requests
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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool



# ===========================================================================
# 1. CONFIGURATION
# ===========================================================================

DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://47000bc.hexacoresoftwaresolutions.in",
]
APP_ORIGIN      = os.getenv("APP_ORIGIN", "")
APP_ORIGINS     = list(dict.fromkeys(
    [o.strip().rstrip("/") for o in APP_ORIGIN.split(",") if o.strip()] + DEFAULT_ORIGINS
))
_VERCEL_ORIGIN_RE = re.compile(r"^https://[a-zA-Z0-9-]+\.vercel\.app$")
COOKIE_SECURE   = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "").strip().lower()
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "28800"))   # 8 hours


def _is_allowed_origin(origin: str) -> bool:
    clean = origin.strip().rstrip("/")
    return bool(clean and (clean in APP_ORIGINS or _VERCEL_ORIGIN_RE.match(clean)))


def _cookie_attrs(request: Request) -> dict:
    is_https = COOKIE_SECURE or request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    samesite = COOKIE_SAMESITE or ("none" if is_https else "lax")
    secure = True if samesite == "none" else is_https
    return {"httponly": True, "secure": secure, "samesite": samesite}
TZ              = os.getenv("ATTENDANCE_TIMEZONE", "Asia/Kolkata")
OFFICE_START    = os.getenv("OFFICE_START_TIME", "09:30")
CHANNEL         = "cctv:attendance"
FACE_THRESHOLD  = float(os.getenv("FACE_THRESHOLD", "65"))
CASCADE_PATH    = str(Path(__file__).resolve().parents[1] / "haarcascade_frontalface_default.xml")
UPLOAD_DIR      = Path(__file__).resolve().parents[1] / "uploads"

def _safe_filename_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("._") or "file"


def _upload_image(raw: bytes, cloud_folder: str, local_subdir: str, filename_stem: str) -> tuple[str, str]:
    """Upload image to Cloudinary when active, falling back to local uploads/ storage."""
    if (
        os.getenv("CLOUDINARY_CLOUD_NAME")
        and os.getenv("CLOUDINARY_API_KEY")
        and os.getenv("CLOUDINARY_API_SECRET")
    ):
        try:
            res = cloudinary.uploader.upload(
                raw,
                folder=cloud_folder,
                type="authenticated",
                resource_type="image",
            )
            return res.get("secure_url", ""), res.get("public_id", "")
        except Exception as exc:
            print(f"[UPLOAD] Cloudinary unavailable ({exc}); saving locally.")

    target_dir = UPLOAD_DIR / local_subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{_safe_filename_stem(filename_stem)}.jpg"
    (target_dir / safe_name).write_bytes(raw)
    return "", f"local:{local_subdir}/{safe_name}"

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
    return AsyncRedis.from_url(url, socket_connect_timeout=2, decode_responses=True)


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
        for alter_sql in (
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS department TEXT DEFAULT ''",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS designation TEXT DEFAULT ''",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT ''",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS email TEXT DEFAULT ''",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS joining_date DATE",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Active'",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS photo_url TEXT DEFAULT ''",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS samples BYTEA[] NOT NULL DEFAULT ARRAY[]::BYTEA[]",
            "ALTER TABLE cctv_employee ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        ):
            conn.execute(alter_sql)
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cctv_salary_structure (
                employee_id   TEXT PRIMARY KEY REFERENCES cctv_employee(id) ON DELETE CASCADE,
                basic_salary  NUMERIC(12,2) NOT NULL DEFAULT 0,
                hra           NUMERIC(12,2) NOT NULL DEFAULT 0,
                allowances    NUMERIC(12,2) NOT NULL DEFAULT 0,
                deductions    NUMERIC(12,2) NOT NULL DEFAULT 0,
                overtime_rate NUMERIC(10,2) NOT NULL DEFAULT 0,
                updated_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cctv_payroll (
                id              BIGSERIAL PRIMARY KEY,
                employee_id     TEXT NOT NULL REFERENCES cctv_employee(id) ON DELETE CASCADE,
                pay_month       INT NOT NULL CHECK (pay_month BETWEEN 1 AND 12),
                pay_year        INT NOT NULL CHECK (pay_year BETWEEN 2000 AND 2100),
                working_days    INT NOT NULL DEFAULT 22,
                present_days    INT NOT NULL DEFAULT 0,
                absent_days     INT NOT NULL DEFAULT 0,
                late_days       INT NOT NULL DEFAULT 0,
                worked_hours    NUMERIC(10,2) NOT NULL DEFAULT 0,
                overtime_hours  NUMERIC(10,2) NOT NULL DEFAULT 0,
                overtime_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
                basic_salary    NUMERIC(12,2) NOT NULL DEFAULT 0,
                hra             NUMERIC(12,2) NOT NULL DEFAULT 0,
                allowances      NUMERIC(12,2) NOT NULL DEFAULT 0,
                gross_salary    NUMERIC(12,2) NOT NULL DEFAULT 0,
                deductions      NUMERIC(12,2) NOT NULL DEFAULT 0,
                net_salary      NUMERIC(12,2) NOT NULL DEFAULT 0,
                payment_status  TEXT NOT NULL DEFAULT 'Pending' CHECK (payment_status IN ('Pending', 'Processed', 'Paid')),
                payment_date    DATE,
                generated_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(employee_id, pay_month, pay_year)
            )
        """)


# ===========================================================================
# 3. FIREBASE AUTH HELPERS
# ===========================================================================

_fb_lock = threading.Lock()
_google_request = google_requests.Request()


def _firebase_env(name: str) -> str:
    return (
        os.getenv(f"FIREBASE_{name}", "").strip()
        or os.getenv(f"VITE_FIREBASE_{name}", "").strip()
    )


def _verify_firebase_id_token(token: str) -> tuple[dict, bool]:
    """Verify a Firebase ID token using Admin SDK creds or projectId-only public certs."""
    has_creds = _has_firebase_credentials()
    if has_creds:
        claims = firebase_auth.verify_id_token(
            token, app=get_firebase_app(), check_revoked=True
        )
        return claims, True

    project_id = _firebase_env("PROJECT_ID")
    if not project_id:
        raise RuntimeError("FIREBASE_PROJECT_ID not configured")

    claims = google_id_token.verify_firebase_token(
        token, _google_request, audience=project_id
    )
    claims["uid"] = claims["sub"]
    return claims, False


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
            project_id = _firebase_env("PROJECT_ID")
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

            # Upload capture to Cloudinary (or fall back to local uploads/captures/)
            _, buf = cv2.imencode(".jpg", crop)
            image_url, public_id = _upload_image(
                buf.tobytes(),
                "cctv-attendance",
                "captures",
                f"event_{row['id']}",
            )
            if not image_url:
                image_url = f"/api/events/{row['id']}/snapshot"
            conn.execute(
                "UPDATE cctv_event SET image_url=%s, public_id=%s WHERE id=%s",
                (image_url, public_id, row["id"]),
            )

        # Notify all WebSocket clients (non-blocking)
        _publish_attendance_refresh()

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

# CORS — allow the React frontend origin(s) and Vercel preview deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_ORIGINS,
    allow_origin_regex=r"^https://[a-zA-Z0-9-]+\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# 7. AUTHENTICATION ENDPOINTS
# ===========================================================================

class LoginPayload(BaseModel):
    token: str


class EmailAuthPayload(BaseModel):
    email: str
    password: str


_FIREBASE_ERROR_MESSAGES = {
    "EMAIL_NOT_FOUND": "Invalid email or password",
    "INVALID_PASSWORD": "Invalid email or password",
    "INVALID_LOGIN_CREDENTIALS": "Invalid email or password",
    "USER_DISABLED": "This account has been disabled",
    "EMAIL_EXISTS": "An account with this email already exists",
    "INVALID_EMAIL": "Please enter a valid email address",
    "WEAK_PASSWORD": "Password must be at least 6 characters",
    "OPERATION_NOT_ALLOWED": "Email/password sign-in is disabled in Firebase",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts — please try again later",
}


def _firebase_identity_auth(operation: str, email: str, password: str) -> str:
    """Authenticate or register via Firebase Identity Toolkit using backend FIREBASE_API_KEY."""
    api_key = _firebase_env("API_KEY")
    if not api_key:
        raise HTTPException(503, "FIREBASE_API_KEY is not configured on backend")

    try:
        resp = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:{operation}?key={api_key}",
            json={"email": email.strip(), "password": password, "returnSecureToken": True},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(502, f"Unable to reach Firebase Auth: {exc}")

    data = resp.json()
    if resp.status_code != 200:
        code = (data.get("error", {}).get("message") or "").split(":")[0].strip()
        friendly = _FIREBASE_ERROR_MESSAGES.get(code, code or "Firebase authentication failed")
        status = 429 if code == "TOO_MANY_ATTEMPTS_TRY_LATER" else 401 if operation == "signInWithPassword" else 400
        raise HTTPException(status, friendly)

    id_token = data.get("idToken")
    if not id_token:
        raise HTTPException(502, "Firebase Auth did not return an ID token")
    return id_token


def _issue_session_from_token(token: str, request: Request, response: Response) -> dict:
    """Verify Firebase ID token, check admin access, and set the session cookie."""
    try:
        claims, has_creds = _verify_firebase_id_token(token)
    except Exception as exc:
        print(f"[AUTH] verify_id_token failed: {type(exc).__name__}: {exc}")
        raise HTTPException(401, "Firebase sign-in failed — invalid token")

    _check_admin_uid(claims["uid"], claims.get("email", ""))

    # Reject tokens from sign-ins that are more than 5 minutes old
    if time.time() - claims["auth_time"] > 300:
        raise HTTPException(401, "Sign in again to continue")

    if has_creds:
        session_cookie = firebase_auth.create_session_cookie(
            token,
            expires_in=timedelta(seconds=SESSION_MAX_AGE),
            app=get_firebase_app(),
        )
    else:
        # Fallback when FIREBASE_SERVICE_ACCOUNT_PATH is not configured
        session_cookie = _sign_local_session(claims["uid"], claims.get("email", ""))

    response.set_cookie(
        "session",
        session_cookie,
        max_age=SESSION_MAX_AGE,
        **_cookie_attrs(request),
    )

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
                (claims["uid"], "LOGIN", f"User {claims.get('email', claims['uid'])} signed in"),
            )
    except Exception:
        pass

    return {"ok": True, "uid": claims["uid"], "email": claims.get("email", "")}


@app.get("/api/health")
def health():
    """Health check endpoint for Render / load balancers."""
    return {"status": "ok"}


@app.get("/api/config")
def get_firebase_config():
    """Return public Firebase web config (safe to expose)."""
    return {
        "apiKey":            _firebase_env("API_KEY"),
        "authDomain":        _firebase_env("AUTH_DOMAIN"),
        "projectId":         _firebase_env("PROJECT_ID"),
        "storageBucket":     _firebase_env("STORAGE_BUCKET"),
        "messagingSenderId": _firebase_env("MESSAGING_SENDER_ID"),
        "appId":             _firebase_env("APP_ID"),
    }


@app.post("/api/auth/login")
def auth_login(body: EmailAuthPayload, request: Request, response: Response):
    """Sign in with email & password using backend FIREBASE_API_KEY."""
    id_token = _firebase_identity_auth("signInWithPassword", body.email, body.password)
    return _issue_session_from_token(id_token, request, response)


@app.post("/api/auth/register")
def auth_register(body: EmailAuthPayload, request: Request, response: Response):
    """Register with email & password using backend FIREBASE_API_KEY."""
    id_token = _firebase_identity_auth("signUp", body.email, body.password)
    return _issue_session_from_token(id_token, request, response)


@app.post("/api/session")
def login(body: LoginPayload, request: Request, response: Response):
    """Exchange a Firebase ID token for a server-side session cookie."""
    return _issue_session_from_token(body.token, request, response)


@app.delete("/api/session")
def logout(request: Request, response: Response, user: dict = Depends(admin_user)):
    """Revoke the Firebase session cookie."""
    try:
        firebase_auth.revoke_refresh_tokens(user["uid"], app=get_firebase_app())
    except Exception:
        pass
    attrs = _cookie_attrs(request)
    response.delete_cookie("session", path="/", secure=attrs["secure"], samesite=attrs["samesite"])
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


@app.get("/api/employees/{employee_id}/photo")
def get_employee_photo(
    employee_id: str = PathParam(...),
    _: dict = Depends(admin_user),
):
    """Serve locally stored employee profile photo (or first face sample fallback)."""
    emp_dir = (UPLOAD_DIR / "employees").resolve()
    local_file = (emp_dir / f"{_safe_filename_stem(employee_id)}.jpg").resolve()
    if local_file.parent == emp_dir and local_file.is_file():
        return FileResponse(local_file, media_type="image/jpeg")

    with get_db() as conn:
        row = conn.execute(
            "SELECT samples FROM cctv_employee WHERE id = %s",
            (employee_id,),
        ).fetchone()
    if row and row["samples"]:
        return Response(content=bytes(row["samples"][0]), media_type="image/png")
    raise HTTPException(404, "Employee photo not found")


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
    first_raw: Optional[bytes] = None

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

        if i == 0:
            first_raw = raw

        # Encode face crop as PNG bytes for storage in Neon
        _, buf = cv2.imencode(".png", crops[0])
        samples.append(buf.tobytes())

    # Upload first photo to Cloudinary or fall back to local storage
    photo_url, _ = _upload_image(first_raw or b"", "cctv-employees", "employees", id)
    if not photo_url:
        photo_url = f"/api/employees/{id}/photo"

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

    required_env = ["DATABASE_URL", "TAPO_RTSP_URL"]

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

def _parse_day_param(day_str: str) -> date:
    if not day_str:
        return datetime.now(ZoneInfo(TZ)).date()
    try:
        return date.fromisoformat(day_str)
    except ValueError:
        raise HTTPException(422, "Invalid date format; expected YYYY-MM-DD")


def _parse_office_start_time() -> dt_time:
    try:
        parts = OFFICE_START.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return dt_time(9, 30)


def _publish_attendance_refresh():
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return
    def _send():
        try:
            r = Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
            r.publish(CHANNEL, "refresh")
            r.close()
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


class ManualAttendancePayload(BaseModel):
    employee_id: str
    day: str
    direction: Literal["in", "out"]
    time: Optional[str] = None


@app.get("/api/attendance/daily")
def daily_attendance(
    day: str = Query("", description="YYYY-MM-DD (defaults to today)"),
    q: str = Query("", description="Search name, ID, or department"),
    status: str = Query("all", description="all|present|absent|inside|checked_out|late"),
    _: dict = Depends(admin_user),
):
    """Return daily attendance overview KPIs and per-employee status for a given date."""
    target_day = _parse_day_param(day)
    tz = ZoneInfo(TZ)
    cutoff = _parse_office_start_time()

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                e.id, e.name, e.department, e.designation, e.status AS employee_status, e.photo_url,
                ev_in.id AS check_in_event_id,
                ev_in.occurred_at AS check_in_at,
                ev_in.image_url AS check_in_image_url,
                ev_out.id AS check_out_event_id,
                ev_out.occurred_at AS check_out_at,
                ev_out.image_url AS check_out_image_url
            FROM cctv_employee e
            LEFT JOIN cctv_event ev_in
              ON ev_in.employee_id = e.id AND ev_in.day = %s AND ev_in.direction = 'in'
            LEFT JOIN cctv_event ev_out
              ON ev_out.employee_id = e.id AND ev_out.day = %s AND ev_out.direction = 'out'
            WHERE e.status = 'Active' OR ev_in.id IS NOT NULL OR ev_out.id IS NOT NULL
            ORDER BY e.name, e.id
            """,
            (target_day, target_day),
        ).fetchall()

    all_records = []
    total_active = 0
    present_active = 0
    inside_count = 0
    checked_out_count = 0
    late_count = 0
    total_hours_sum = 0.0

    for row in rows:
        cin = row["check_in_at"].astimezone(tz) if row["check_in_at"] else None
        cout = row["check_out_at"].astimezone(tz) if row["check_out_at"] else None

        if cin and cout:
            att_status = "Checked Out"
            hours = round(max(0.0, (cout - cin).total_seconds() / 3600.0), 2)
        elif cin:
            att_status = "Inside"
            hours = None
        elif cout:
            att_status = "Checked Out"
            hours = None
        else:
            att_status = "Absent"
            hours = None

        is_late = bool(cin and cin.time() > cutoff)

        if row["employee_status"] == "Active":
            total_active += 1
            if att_status != "Absent":
                present_active += 1
        if att_status == "Inside":
            inside_count += 1
        elif att_status == "Checked Out":
            checked_out_count += 1
        if is_late:
            late_count += 1
        if hours is not None:
            total_hours_sum += hours

        all_records.append({
            "employee_id": row["id"],
            "name": row["name"],
            "department": row["department"] or "",
            "designation": row["designation"] or "",
            "employee_status": row["employee_status"] or "Active",
            "photo_url": row["photo_url"] or "",
            "attendance_status": att_status,
            "is_late": is_late,
            "check_in_event_id": row["check_in_event_id"],
            "check_in_at": cin.isoformat() if cin else None,
            "check_in_source": "CCTV" if row["check_in_image_url"] else ("Manual" if cin else None),
            "check_in_has_photo": bool(row["check_in_image_url"]),
            "check_out_event_id": row["check_out_event_id"],
            "check_out_at": cout.isoformat() if cout else None,
            "check_out_source": "CCTV" if row["check_out_image_url"] else ("Manual" if cout else None),
            "check_out_has_photo": bool(row["check_out_image_url"]),
            "working_hours": hours,
        })

    q_lower = q.strip().lower()
    status_norm = status.strip().lower()
    filtered = []
    for rec in all_records:
        if q_lower and not any(
            q_lower in (rec[field] or "").lower()
            for field in ("employee_id", "name", "department", "designation")
        ):
            continue
        if status_norm == "present" and rec["attendance_status"] == "Absent":
            continue
        if status_norm == "absent" and rec["attendance_status"] != "Absent":
            continue
        if status_norm == "inside" and rec["attendance_status"] != "Inside":
            continue
        if status_norm == "checked_out" and rec["attendance_status"] != "Checked Out":
            continue
        if status_norm == "late" and not rec["is_late"]:
            continue
        filtered.append(rec)

    absent_active = max(0, total_active - present_active)
    rate = round((present_active / total_active) * 100.0, 1) if total_active else 0.0

    return {
        "overview": {
            "date": target_day.isoformat(),
            "timezone": TZ,
            "office_start": cutoff.strftime("%H:%M"),
            "total_employees": total_active,
            "present": present_active,
            "absent": absent_active,
            "inside": inside_count,
            "checked_out": checked_out_count,
            "late": late_count,
            "attendance_rate": rate,
            "total_hours": round(total_hours_sum, 2),
        },
        "records": filtered,
    }


@app.post("/api/attendance/manual")
def upsert_manual_attendance(
    body: ManualAttendancePayload,
    user: dict = Depends(admin_user),
):
    """Create or update an employee's check-in or check-out event for a given date."""
    target_day = _parse_day_param(body.day)
    tz = ZoneInfo(TZ)

    if body.time:
        parsed_time = None
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                parsed_time = datetime.strptime(body.time.strip(), fmt).time()
                break
            except ValueError:
                continue
        if parsed_time is None:
            raise HTTPException(422, "time must be HH:MM or HH:MM:SS")
    else:
        parsed_time = datetime.now(tz).time().replace(microsecond=0)

    occurred_at = datetime.combine(target_day, parsed_time, tzinfo=tz)

    with get_db() as conn:
        emp = conn.execute(
            "SELECT id, name FROM cctv_employee WHERE id = %s",
            (body.employee_id,),
        ).fetchone()
        if not emp:
            raise HTTPException(404, "Employee not found")

        row = conn.execute(
            """
            INSERT INTO cctv_event (employee_id, day, direction, occurred_at, image_url, public_id)
            VALUES (%s, %s, %s, %s, '', '')
            ON CONFLICT (employee_id, day, direction)
            DO UPDATE SET occurred_at = EXCLUDED.occurred_at
            RETURNING id, occurred_at
            """,
            (body.employee_id, target_day, body.direction, occurred_at),
        ).fetchone()

        conn.execute(
            "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
            (
                user["uid"],
                "MANUAL_ATTENDANCE",
                f"Marked {body.direction} for {body.employee_id} on {target_day.isoformat()} at {parsed_time.strftime('%H:%M:%S')}",
            ),
        )

    _publish_attendance_refresh()
    return {"ok": True, "id": row["id"], "occurred_at": row["occurred_at"].astimezone(tz).isoformat()}


@app.delete("/api/attendance/manual")
def delete_manual_attendance(
    employee_id: str = Query(...),
    day: str = Query(...),
    direction: str = Query("", description="Optional: 'in' or 'out'; empty clears both"),
    user: dict = Depends(admin_user),
):
    """Clear an employee's check-in and/or check-out event for a given date."""
    target_day = _parse_day_param(day)
    if direction not in ("", "in", "out"):
        raise HTTPException(422, "direction must be 'in', 'out', or empty")

    with get_db() as conn:
        if direction:
            cur = conn.execute(
                "DELETE FROM cctv_event WHERE employee_id = %s AND day = %s AND direction = %s",
                (employee_id, target_day, direction),
            )
        else:
            cur = conn.execute(
                "DELETE FROM cctv_event WHERE employee_id = %s AND day = %s",
                (employee_id, target_day),
            )
        if cur.rowcount == 0:
            raise HTTPException(404, "No matching attendance record found")

        conn.execute(
            "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
            (
                user["uid"],
                "DELETE_ATTENDANCE",
                f"Cleared {direction or 'all'} attendance for {employee_id} on {target_day.isoformat()}",
            ),
        )

    _publish_attendance_refresh()
    return {"ok": True, "deleted": cur.rowcount}


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
    """Serve local capture file or redirect to a signed Cloudinary URL."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT public_id FROM cctv_event WHERE id = %s", (event_id,)
        ).fetchone()
    if not row or not row["public_id"]:
        raise HTTPException(404, "Snapshot not found")

    public_id = row["public_id"]
    if public_id.startswith("local:"):
        rel = public_id[len("local:"):]
        upload_root = UPLOAD_DIR.resolve()
        local_file = (upload_root / rel).resolve()
        try:
            local_file.relative_to(upload_root)
        except ValueError:
            raise HTTPException(403, "Invalid snapshot path")
        if not local_file.is_file():
            raise HTTPException(404, "Snapshot file not found")
        return FileResponse(
            local_file,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    url = private_download_url(
        public_id,
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
# 11B. SALARY STRUCTURE & ATTENDANCE-BASED PAYROLL ENDPOINTS
# ===========================================================================

class SalaryStructurePayload(BaseModel):
    employee_id: str
    basic_salary: float = 0
    hra: float = 0
    allowances: float = 0
    deductions: float = 0
    overtime_rate: float = 0


class PayrollGeneratePayload(BaseModel):
    month: int
    year: int
    working_days: Optional[int] = None
    standard_daily_hours: float = 8.0
    employee_id: Optional[str] = None


class PayrollPaymentPayload(BaseModel):
    payment_status: Literal["Pending", "Processed", "Paid"]


def _default_working_days(year: int, month: int) -> int:
    """Count weekdays (Mon-Fri) in the given month."""
    _, days_in_month = calendar.monthrange(year, month)
    return sum(
        1 for d in range(1, days_in_month + 1)
        if date(year, month, d).weekday() < 5
    )


def _validate_month_year(month: int, year: int):
    if not 1 <= month <= 12:
        raise HTTPException(422, "month must be between 1 and 12")
    if not 2000 <= year <= 2100:
        raise HTTPException(422, "year must be between 2000 and 2100")


@app.get("/api/salary-structures")
def list_salary_structures(_: dict = Depends(admin_user)):
    """List all active employees along with their configured salary structure."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                e.id AS employee_id, e.name, e.department, e.designation, e.status,
                COALESCE(s.basic_salary, 0)::FLOAT AS basic_salary,
                COALESCE(s.hra, 0)::FLOAT AS hra,
                COALESCE(s.allowances, 0)::FLOAT AS allowances,
                COALESCE(s.deductions, 0)::FLOAT AS deductions,
                COALESCE(s.overtime_rate, 0)::FLOAT AS overtime_rate,
                (s.employee_id IS NOT NULL) AS configured,
                s.updated_at
            FROM cctv_employee e
            LEFT JOIN cctv_salary_structure s ON s.employee_id = e.id
            WHERE e.status = 'Active'
            ORDER BY e.name, e.id
            """
        ).fetchall()
    return rows


@app.post("/api/salary-structures")
def upsert_salary_structure(
    body: SalaryStructurePayload,
    user: dict = Depends(admin_user),
):
    """Create or update an employee's monthly salary structure."""
    amounts = [body.basic_salary, body.hra, body.allowances, body.deductions, body.overtime_rate]
    if any(v < 0 for v in amounts):
        raise HTTPException(422, "Salary amounts cannot be negative")

    with get_db() as conn:
        emp = conn.execute(
            "SELECT id, name FROM cctv_employee WHERE id = %s",
            (body.employee_id,),
        ).fetchone()
        if not emp:
            raise HTTPException(404, "Employee not found")

        row = conn.execute(
            """
            INSERT INTO cctv_salary_structure
                (employee_id, basic_salary, hra, allowances, deductions, overtime_rate, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (employee_id) DO UPDATE SET
                basic_salary = EXCLUDED.basic_salary,
                hra = EXCLUDED.hra,
                allowances = EXCLUDED.allowances,
                deductions = EXCLUDED.deductions,
                overtime_rate = EXCLUDED.overtime_rate,
                updated_at = NOW()
            RETURNING employee_id, basic_salary::FLOAT, hra::FLOAT, allowances::FLOAT,
                      deductions::FLOAT, overtime_rate::FLOAT, updated_at
            """,
            (
                body.employee_id,
                round(body.basic_salary, 2),
                round(body.hra, 2),
                round(body.allowances, 2),
                round(body.deductions, 2),
                round(body.overtime_rate, 2),
            ),
        ).fetchone()

        conn.execute(
            "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
            (user["uid"], "SALARY_STRUCTURE", f"Updated salary structure for {body.employee_id}"),
        )

    return {"ok": True, "structure": row}


@app.get("/api/payroll")
def list_payroll(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    q: str = Query(""),
    status: str = Query("all"),
    _: dict = Depends(admin_user),
):
    """List generated monthly payroll records and summary totals."""
    now_local = datetime.now(ZoneInfo(TZ)).date()
    m = month or now_local.month
    y = year or now_local.year
    _validate_month_year(m, y)

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id, p.employee_id, e.name, e.department, e.designation,
                p.pay_month, p.pay_year, p.working_days, p.present_days, p.absent_days,
                p.late_days, p.worked_hours::FLOAT, p.overtime_hours::FLOAT,
                p.overtime_amount::FLOAT, p.basic_salary::FLOAT, p.hra::FLOAT,
                p.allowances::FLOAT, p.gross_salary::FLOAT, p.deductions::FLOAT,
                p.net_salary::FLOAT, p.payment_status, p.payment_date, p.generated_at
            FROM cctv_payroll p
            JOIN cctv_employee e ON e.id = p.employee_id
            WHERE p.pay_month = %s AND p.pay_year = %s
            ORDER BY e.name, p.employee_id
            """,
            (m, y),
        ).fetchall()

        unconfigured_cnt = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM cctv_employee e
            LEFT JOIN cctv_salary_structure s ON s.employee_id = e.id
            WHERE e.status = 'Active' AND s.employee_id IS NULL
            """
        ).fetchone()["cnt"]

        active_cnt = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cctv_employee WHERE status = 'Active'"
        ).fetchone()["cnt"]

    total_gross = round(sum(r["gross_salary"] for r in rows), 2)
    total_deductions = round(sum(r["deductions"] for r in rows), 2)
    total_net = round(sum(r["net_salary"] for r in rows), 2)
    total_present = sum(r["present_days"] for r in rows)
    total_hours = round(sum(r["worked_hours"] for r in rows), 2)
    pending_cnt = sum(1 for r in rows if r["payment_status"] == "Pending")
    processed_cnt = sum(1 for r in rows if r["payment_status"] == "Processed")
    paid_cnt = sum(1 for r in rows if r["payment_status"] == "Paid")

    q_lower = q.strip().lower()
    status_norm = status.strip().lower()
    filtered = []
    for r in rows:
        if q_lower and not any(
            q_lower in (r[f] or "").lower()
            for f in ("employee_id", "name", "department", "designation")
        ):
            continue
        if status_norm != "all" and r["payment_status"].lower() != status_norm:
            continue
        filtered.append(r)

    return {
        "summary": {
            "month": m,
            "year": y,
            "default_working_days": _default_working_days(y, m),
            "active_employees": active_cnt,
            "unconfigured_structures": unconfigured_cnt,
            "total_records": len(rows),
            "total_gross": total_gross,
            "total_deductions": total_deductions,
            "total_net": total_net,
            "total_present_days": total_present,
            "total_worked_hours": total_hours,
            "pending_count": pending_cnt,
            "processed_count": processed_cnt,
            "paid_count": paid_cnt,
        },
        "records": filtered,
    }


@app.post("/api/payroll/generate")
def generate_payroll(
    body: PayrollGeneratePayload,
    user: dict = Depends(admin_user),
):
    """Generate or recalculate payroll for a month from attendance events and salary structures."""
    _validate_month_year(body.month, body.year)
    working_days = body.working_days if body.working_days is not None else _default_working_days(body.year, body.month)
    if working_days <= 0 or working_days > 31:
        raise HTTPException(422, "working_days must be between 1 and 31")
    if body.standard_daily_hours <= 0 or body.standard_daily_hours > 24:
        raise HTTPException(422, "standard_daily_hours must be between 1 and 24")

    _, last_dom = calendar.monthrange(body.year, body.month)
    month_start = date(body.year, body.month, 1)
    month_end = date(body.year, body.month, last_dom)
    tz = ZoneInfo(TZ)
    cutoff = _parse_office_start_time()

    with get_db() as conn:
        if body.employee_id:
            employees = conn.execute(
                """
                SELECT e.id, e.name, s.basic_salary::FLOAT, s.hra::FLOAT,
                       s.allowances::FLOAT, s.deductions::FLOAT, s.overtime_rate::FLOAT,
                       (s.employee_id IS NOT NULL) AS configured
                FROM cctv_employee e
                LEFT JOIN cctv_salary_structure s ON s.employee_id = e.id
                WHERE e.id = %s
                """,
                (body.employee_id,),
            ).fetchall()
            if not employees:
                raise HTTPException(404, "Employee not found")
        else:
            employees = conn.execute(
                """
                SELECT e.id, e.name, s.basic_salary::FLOAT, s.hra::FLOAT,
                       s.allowances::FLOAT, s.deductions::FLOAT, s.overtime_rate::FLOAT,
                       (s.employee_id IS NOT NULL) AS configured
                FROM cctv_employee e
                LEFT JOIN cctv_salary_structure s ON s.employee_id = e.id
                WHERE e.status = 'Active'
                ORDER BY e.name, e.id
                """
            ).fetchall()

        target_ids = [e["id"] for e in employees if e["configured"]]
        skipped = [e["id"] for e in employees if not e["configured"]]

        if not target_ids:
            raise HTTPException(
                422,
                "No salary structures configured for the selected employee(s). Configure salary structures first.",
            )

        events = conn.execute(
            """
            SELECT employee_id, day, direction, occurred_at
            FROM cctv_event
            WHERE employee_id = ANY(%s)
              AND day BETWEEN %s AND %s
            ORDER BY day, occurred_at
            """,
            (target_ids, month_start, month_end),
        ).fetchall()

        # Group events by (employee_id, day)
        by_emp_day: dict[str, dict[date, dict[str, datetime]]] = {}
        for ev in events:
            emp_days = by_emp_day.setdefault(ev["employee_id"], {})
            day_pair = emp_days.setdefault(ev["day"], {})
            day_pair[ev["direction"]] = ev["occurred_at"].astimezone(tz)

        generated = 0
        for emp in employees:
            if not emp["configured"]:
                continue

            emp_days = by_emp_day.get(emp["id"], {})
            present_days = 0
            late_days = 0
            worked_hours = 0.0
            overtime_hours = 0.0

            for day_pair in emp_days.values():
                cin = day_pair.get("in")
                cout = day_pair.get("out")
                if cin:
                    present_days += 1
                    if cin.time() > cutoff:
                        late_days += 1
                if cin and cout and cout >= cin:
                    day_hrs = (cout - cin).total_seconds() / 3600.0
                    worked_hours += day_hrs
                    if day_hrs > body.standard_daily_hours:
                        overtime_hours += day_hrs - body.standard_daily_hours

            absent_days = max(0, working_days - present_days)
            ratio = min(1.0, present_days / working_days)

            earned_basic = round(emp["basic_salary"] * ratio, 2)
            earned_hra = round(emp["hra"] * ratio, 2)
            earned_allowances = round(emp["allowances"] * ratio, 2)
            ot_hrs_rounded = round(overtime_hours, 2)
            ot_amount = round(ot_hrs_rounded * emp["overtime_rate"], 2)
            gross = round(earned_basic + earned_hra + earned_allowances + ot_amount, 2)
            deductions = round(emp["deductions"], 2)
            net = round(max(0.0, gross - deductions), 2)

            conn.execute(
                """
                INSERT INTO cctv_payroll (
                    employee_id, pay_month, pay_year, working_days,
                    present_days, absent_days, late_days, worked_hours,
                    overtime_hours, overtime_amount, basic_salary, hra,
                    allowances, gross_salary, deductions, net_salary,
                    payment_status, payment_date, generated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', NULL, NOW())
                ON CONFLICT (employee_id, pay_month, pay_year) DO UPDATE SET
                    working_days = EXCLUDED.working_days,
                    present_days = EXCLUDED.present_days,
                    absent_days = EXCLUDED.absent_days,
                    late_days = EXCLUDED.late_days,
                    worked_hours = EXCLUDED.worked_hours,
                    overtime_hours = EXCLUDED.overtime_hours,
                    overtime_amount = EXCLUDED.overtime_amount,
                    basic_salary = EXCLUDED.basic_salary,
                    hra = EXCLUDED.hra,
                    allowances = EXCLUDED.allowances,
                    gross_salary = EXCLUDED.gross_salary,
                    deductions = EXCLUDED.deductions,
                    net_salary = EXCLUDED.net_salary,
                    payment_status = CASE
                        WHEN cctv_payroll.payment_status = 'Paid' THEN 'Paid'
                        ELSE 'Pending'
                    END,
                    generated_at = NOW()
                """,
                (
                    emp["id"], body.month, body.year, working_days,
                    present_days, absent_days, late_days, round(worked_hours, 2),
                    ot_hrs_rounded, ot_amount, earned_basic, earned_hra,
                    earned_allowances, gross, deductions, net,
                ),
            )
            generated += 1

        conn.execute(
            "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
            (
                user["uid"],
                "GENERATE_PAYROLL",
                f"Generated payroll for {generated} employee(s) for {body.year}-{body.month:02d}",
            ),
        )

    return {"ok": True, "generated": generated, "skipped_no_structure": skipped}


@app.put("/api/payroll/{payroll_id}/payment")
def update_payroll_payment(
    payroll_id: int = PathParam(...),
    body: PayrollPaymentPayload = ...,
    user: dict = Depends(admin_user),
):
    """Update payroll payment status (Pending, Processed, or Paid)."""
    pay_date = datetime.now(ZoneInfo(TZ)).date() if body.payment_status == "Paid" else None
    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE cctv_payroll
            SET payment_status = %s, payment_date = %s
            WHERE id = %s
            RETURNING id, employee_id, payment_status, payment_date
            """,
            (body.payment_status, pay_date, payroll_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Payroll record not found")

        conn.execute(
            "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
            (user["uid"], "PAYROLL_PAYMENT", f"Payroll #{payroll_id} marked {body.payment_status}"),
        )

    return {"ok": True, "record": row}


@app.delete("/api/payroll/{payroll_id}")
def delete_payroll_record(
    payroll_id: int = PathParam(...),
    user: dict = Depends(admin_user),
):
    """Delete a payroll record."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM cctv_payroll WHERE id = %s", (payroll_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Payroll record not found")
        conn.execute(
            "INSERT INTO activity_log (uid, action, description) VALUES (%s, %s, %s)",
            (user["uid"], "DELETE_PAYROLL", f"Deleted payroll #{payroll_id}"),
        )
    return {"ok": True}


@app.get("/api/payroll/export")
def export_payroll_csv(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    _: dict = Depends(admin_user),
):
    """Download monthly payroll as CSV."""
    now_local = datetime.now(ZoneInfo(TZ)).date()
    m = month or now_local.month
    y = year or now_local.year
    _validate_month_year(m, y)

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                p.employee_id, e.name, e.department, p.pay_month, p.pay_year,
                p.working_days, p.present_days, p.absent_days, p.late_days,
                p.worked_hours::FLOAT, p.overtime_hours::FLOAT, p.basic_salary::FLOAT,
                p.hra::FLOAT, p.allowances::FLOAT, p.overtime_amount::FLOAT,
                p.gross_salary::FLOAT, p.deductions::FLOAT, p.net_salary::FLOAT,
                p.payment_status, p.payment_date
            FROM cctv_payroll p
            JOIN cctv_employee e ON e.id = p.employee_id
            WHERE p.pay_month = %s AND p.pay_year = %s
            ORDER BY e.name, p.employee_id
            """,
            (m, y),
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Employee ID", "Name", "Department", "Month", "Year",
        "Working Days", "Present Days", "Absent Days", "Late Days",
        "Worked Hours", "Overtime Hours", "Basic", "HRA", "Allowances",
        "Overtime Amount", "Gross Salary", "Deductions", "Net Salary",
        "Status", "Payment Date",
    ])
    for r in rows:
        writer.writerow([
            r["employee_id"], r["name"], r["department"], r["pay_month"], r["pay_year"],
            r["working_days"], r["present_days"], r["absent_days"], r["late_days"],
            r["worked_hours"], r["overtime_hours"], r["basic_salary"], r["hra"],
            r["allowances"], r["overtime_amount"], r["gross_salary"], r["deductions"],
            r["net_salary"], r["payment_status"], r["payment_date"] or "",
        ])
    output.seek(0)
    filename = f"payroll_{y}_{m:02d}.csv"
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
    origin = (ws.headers.get("origin") or "").rstrip("/")
    if origin not in APP_ORIGINS:
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

    redis = None
    try:
        redis = await get_async_redis()
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
        # Redis offline — keep WebSocket alive with periodic keepalive pings
        while time.time() < claims["exp"]:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                try:
                    await ws.send_text("ping")
                except Exception:
                    break
            except Exception:
                break
    finally:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:
                pass


# ===========================================================================
# 14. SERVE REACT VITE FRONTEND (production)
# ===========================================================================

frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.is_dir():
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        target = (frontend_dist / full_path).resolve()
        if full_path and target.is_file() and frontend_dist.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(frontend_dist / "index.html")
