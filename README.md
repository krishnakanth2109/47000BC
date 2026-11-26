# CCTV Attendance System v2.0

A complete CCTV-based employee attendance system rebuilt with a modern production stack.

## 🏗️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | **FastAPI** (Python) |
| Database | **Neon** (PostgreSQL, serverless) |
| Cache & Pub/Sub | **Redis** (Upstash or local) |
| Auth | **Firebase Authentication** (session cookies) |
| Image Storage | **Cloudinary** (authenticated, signed URLs) |
| Face Recognition | **OpenCV LBPH** (stored in Neon as bytea) |
| Frontend | **React 19 + Vite** |
| Real-time | **WebSockets** (Redis pub/sub push) |

---

## 📁 Project Structure

```
CCTV-Attendance-System/
├── backend/
│   ├── main.py           ← FastAPI application (all routes)
│   └── requirements.txt  ← Python dependencies
├── frontend/
│   ├── src/
│   │   ├── main.jsx              ← React entry point
│   │   ├── App.jsx               ← Router + auth guards
│   │   ├── firebase.js           ← Firebase web config
│   │   ├── api.js                ← Fetch helper (cookies)
│   │   ├── contexts/
│   │   │   └── AuthContext.jsx   ← Auth state + login/logout
│   │   ├── hooks/
│   │   │   └── useWebSocket.js   ← WS with auto-reconnect
│   │   ├── pages/
│   │   │   ├── LoginPage.jsx
│   │   │   ├── DashboardPage.jsx
│   │   │   ├── EmployeesPage.jsx
│   │   │   └── AttendancePage.jsx
│   │   └── components/
│   │       └── Layout.jsx        ← Sidebar + nav
│   ├── index.html
│   ├── package.json
│   └── vite.config.js           ← Dev proxy to :8000
├── haarcascade_frontalface_default.xml
├── .env                         ← Your actual secrets (gitignored)
├── .env.example                 ← Template to copy from
└── start.js                     ← Launch both servers at once
```

---

## ⚡ Quick Start

### 1. Set up environment variables

```bash
cp .env.example .env
# Then edit .env with your credentials
```

### 2. Install backend dependencies

```bash
# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

pip install -r backend/requirements.txt
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 4. Start the development servers

**Option A — Two terminals:**

```bash
# Terminal 1 — FastAPI backend
cd backend
uvicorn main:app --reload --port 8000

# Terminal 2 — Vite frontend
cd frontend
npm run dev
```

**Option B — Single command:**

```bash
node start.js
```

Open **http://localhost:5173** in your browser.

---

## 🔧 Configuration (.env)

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `REDIS_URL` | Redis URL (Upstash or local) |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Path to Firebase service account JSON |
| `FIREBASE_PROJECT_ID` | Firebase project ID |
| `VITE_FIREBASE_API_KEY` | Firebase web API key (used by React) |
| `VITE_FIREBASE_AUTH_DOMAIN` | Firebase auth domain |
| `VITE_FIREBASE_PROJECT_ID` | Firebase project ID (for React) |
| `ADMIN_UIDS` | Comma-separated Firebase UIDs with admin access |
| `TAPO_RTSP_URL` | RTSP URL of your Tapo C500 camera |
| `CAMERA_DIRECTION` | `in` (checkin) or `out` (checkout) |
| `FACE_THRESHOLD` | LBPH confidence threshold (default: `65`) |
| `APP_ORIGIN` | Frontend URL for CORS (`http://localhost:5173`) |
| `COOKIE_SECURE` | `true` in production (requires HTTPS) |

---

## 📡 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config` | Firebase web config |
| `POST` | `/api/session` | Login (Firebase token → session cookie) |
| `DELETE` | `/api/session` | Logout |
| `GET` | `/api/me` | Current user info |
| `GET` | `/api/dashboard` | Stats + recent events |
| `GET` | `/api/employees` | List employees |
| `POST` | `/api/employees` | Enroll new employee (with face photos) |
| `PUT` | `/api/employees/{id}/status` | Activate/deactivate |
| `DELETE` | `/api/employees/{id}` | Delete employee |
| `GET` | `/api/attendance` | Attendance records with filters |
| `GET` | `/api/reports/export` | Download CSV |
| `GET` | `/api/camera/status` | Camera status |
| `POST` | `/api/camera/start` | Start CCTV recognition |
| `POST` | `/api/camera/stop` | Stop camera |
| `GET` | `/api/events/{id}/snapshot` | Signed Cloudinary URL for capture |
| `POST` | `/api/admin/train` | Re-train face model |
| `WS` | `/api/live` | WebSocket (real-time push) |

---

## 🔐 Authentication Flow

1. User enters **email + password** in React frontend
2. Firebase Auth verifies credentials client-side
3. Firebase issues an **ID token** (short-lived)
4. Frontend sends the ID token to `POST /api/session`
5. FastAPI verifies the token with Firebase Admin SDK
6. FastAPI creates a **session cookie** (HttpOnly, 8 hours)
7. All subsequent API requests use the session cookie
8. Firebase client state is immediately discarded (security)

---

## 🎥 How Face Recognition Works

1. Admin registers an employee with 3–10 face photos
2. Face crops are extracted with Haar Cascade and stored as `bytea` in Neon
3. When the camera starts, an LBPH model is trained in-memory from stored crops
4. The CCTV stream is read via OpenCV RTSP
5. Each frame is scanned for faces; matched faces accumulate a "streak" counter
6. After **5 consecutive** recognized frames, attendance is recorded
7. The capture frame is uploaded to Cloudinary (authenticated)
8. Redis publishes a `refresh` message
9. All connected WebSocket clients receive the update instantly

---

## 🚀 Production Build

```bash
cd frontend
npm run build
# dist/ folder is served by FastAPI StaticFiles
```

Then run only the backend:
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```
