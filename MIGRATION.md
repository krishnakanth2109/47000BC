# FastAPI and React attendance app

Use the repository root for backend commands. The original Flask implementation, HR routes and SQLite records remain in the repository. The new attendance app starts with separate PostgreSQL tables and requires fresh enrollment.

## Connect services

Fill in the ignored root `.env` (a shareable blank copy is in `.env.example`).

- DATABASE_URL: Neon PostgreSQL connection string with sslmode=require. The database user needs permission to create tables.
- REDIS_URL: Redis connection string (rediss:// for hosted TLS). Redis distributes attendance notifications. Neon stores the durable record.
- CLOUDINARY_URL: server-side Cloudinary credentials. Matched snapshots use authenticated image delivery.
- GOOGLE_APPLICATION_CREDENTIALS: absolute path to the Firebase service-account JSON stored outside this repository.
- FIREBASE_PROJECT_ID, FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN: values from the Firebase web app in the same project. Enable email/password sign-in, create your administrator in Firebase Authentication, list their UID in ADMIN_UIDS, and authorize localhost for development.
- TAPO_RTSP_URL: the stream URL reachable from the backend computer.
- CAMERA_DIRECTION: in for an entrance camera or out for an exit camera. Each camera run has one direction. One event per employee, direction and local date is stored.
- APP_ORIGIN must exactly match the browser origin. For local use open http://localhost:5173. Set COOKIE_SECURE=true when serving over HTTPS.

## Run locally in PowerShell

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
    .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

In another terminal:

    cd frontend
    npm install
    npm run dev

Sign in, register someone with 3–10 separate photos, then start the camera. Restart the camera after enrolling another employee to reload its training samples. The recognizer requires five consecutive matching frames. The dashboard shows the latest 200 events. Use View photo to retrieve a short-lived Cloudinary link.

Use a single backend worker for the camera. For a hosted frontend, proxy /api HTTP and WebSocket traffic to that backend on the same origin.

Alternatively, after npm run build, set APP_ORIGIN=http://127.0.0.1:8000 and restart the API. Open http://127.0.0.1:8000 to use the compiled dashboard on the same port.
