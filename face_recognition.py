
"""
CCTV Attendance System
Face Recognition + Tapo C500 + Flask Camera Worker

Features:
- LBPH face recognition
- Employee training
- Tapo C500 RTSP streaming
- Automatic check-in after stable recognition
- Entry / Exit detection
- SQLite attendance
- Daily XML reports
- Flask video feed and camera status
"""

import os
import cv2
import json
import time
import threading
import sqlite3
import numpy as np
import xml.etree.ElementTree as ET

from datetime import datetime, date

from db import get_connection, initialize_database


# =========================================================
# 1. PROJECT PATHS AND SETTINGS
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EMPLOYEE_FOLDER = os.path.join(BASE_DIR, "employees")
TRAINING_FOLDER = os.path.join(EMPLOYEE_FOLDER, "training_photos")

MODEL_FOLDER = os.path.join(BASE_DIR, "models")
REPORT_FOLDER = os.path.join(BASE_DIR, "reports")

CASCADE_PATH = os.path.join(
    BASE_DIR, "haarcascade_frontalface_default.xml"
)

MODEL_PATH = os.path.join(
    MODEL_FOLDER, "face_model.yml"
)

LABELS_PATH = os.path.join(
    MODEL_FOLDER, "labels.json"
)

os.makedirs(TRAINING_FOLDER, exist_ok=True)
os.makedirs(MODEL_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)


# =========================================================
# 2. FACE RECOGNITION SETTINGS
# =========================================================

CONFIDENCE_THRESHOLD = 85
STABLE_FRAMES_REQUIRED = 5

FRAME_WIDTH = 640
FRAME_HEIGHT = 480

LINE_POSITION = 0.50
LINE_MARGIN = 35

ACTION_COOLDOWN = 3
TRACK_TIMEOUT = 2

SHOW_CAMERA_WINDOW = False


# =========================================================
# 3. CAMERA GLOBAL VARIABLES
# =========================================================

CAMERA_STATUS = "STOPPED"
CAMERA_ERROR = ""

camera_lock = threading.Lock()
frame_lock = threading.Lock()
camera_status_lock = threading.Lock()

camera_stop_event = threading.Event()

camera_thread = None
latest_frame = None


# =========================================================
# 4. DATABASE INITIALIZATION
# =========================================================

def ensure_tables():
    """Initialize the existing project database."""
    initialize_database()


# =========================================================
# 5. LOAD FACE DETECTOR
# =========================================================

def load_face_detector():

    if not os.path.exists(CASCADE_PATH):
        raise FileNotFoundError(
            f"Haar cascade file not found: {CASCADE_PATH}"
        )

    detector = cv2.CascadeClassifier(CASCADE_PATH)

    if detector.empty():
        raise RuntimeError("Unable to load Haar cascade.")

    return detector


# =========================================================
# 6. LOAD LBPH MODEL
# =========================================================

def load_face_model():

    if not hasattr(cv2, "face"):
        raise RuntimeError(
            "OpenCV face module is missing. "
            "Install opencv-contrib-python."
        )

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            "Face model not found. Train the model first."
        )

    if not os.path.exists(LABELS_PATH):
        raise FileNotFoundError(
            "labels.json not found. Train the model first."
        )

    model = cv2.face.LBPHFaceRecognizer_create()
    model.read(MODEL_PATH)

    with open(LABELS_PATH, "r", encoding="utf-8") as file:
        labels = json.load(file)

    return model, labels


# =========================================================
# 7. TRAIN FACE RECOGNITION MODEL
# =========================================================

def train_model():

    print("\n[TRAINING] Starting face model training...")

    detector = load_face_detector()

    if not hasattr(cv2, "face"):
        raise RuntimeError(
            "Install opencv-contrib-python to use LBPH."
        )

    faces = []
    face_labels = []

    label_mapping = {}
    current_label = 0

    if not os.path.isdir(TRAINING_FOLDER):
        raise FileNotFoundError(
            "Training folder not found."
        )

    employee_folders = sorted([
        name for name in os.listdir(TRAINING_FOLDER)
        if os.path.isdir(
            os.path.join(TRAINING_FOLDER, name)
        )
    ])

    if not employee_folders:
        raise RuntimeError(
            "No employee training folders found."
        )

    for employee_id in employee_folders:

        employee_path = os.path.join(
            TRAINING_FOLDER,
            employee_id
        )

        employee_images = [
            os.path.join(employee_path, filename)
            for filename in os.listdir(employee_path)
            if filename.lower().endswith(
                (".jpg", ".jpeg", ".png", ".bmp")
            )
        ]

        employee_face_count = 0

        for image_path in employee_images:

            image = cv2.imread(image_path)

            if image is None:
                print("[TRAINING] Unable to read:", image_path)
                continue

            gray = cv2.cvtColor(
                image,
                cv2.COLOR_BGR2GRAY
            )

            detected_faces = detector.detectMultiScale(
                gray,
                scaleFactor=1.2,
                minNeighbors=5,
                minSize=(60, 60)
            )

            for (x, y, w, h) in detected_faces:

                face = gray[y:y + h, x:x + w]

                face = cv2.resize(
                    face,
                    (200, 200)
                )

                faces.append(face)
                face_labels.append(current_label)

                employee_face_count += 1

        if employee_face_count > 0:

            label_mapping[str(current_label)] = str(employee_id)

            print(
                f"[TRAINING] Employee {employee_id}: "
                f"{employee_face_count} faces"
            )

            current_label += 1

        else:
            print(
                f"[TRAINING] No valid faces for employee "
                f"{employee_id}"
            )

    if not faces:
        raise RuntimeError(
            "No valid face images found. "
            "Check employees/training_photos."
        )

    model = cv2.face.LBPHFaceRecognizer_create()

    model.train(
        faces,
        np.array(face_labels, dtype=np.int32)
    )

    labels_tmp = LABELS_PATH + ".tmp"
    model_tmp = MODEL_PATH + ".tmp.yml"
    try:
        with open(labels_tmp, "w", encoding="utf-8") as file:
            json.dump(label_mapping, file, indent=4)
        model.write(model_tmp)
        os.replace(model_tmp, MODEL_PATH)
        os.replace(labels_tmp, LABELS_PATH)
    finally:
        for temporary_path in (model_tmp, labels_tmp):
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

    print("\n[TRAINING] Model trained successfully.")
    print("[TRAINING] Employees:", len(label_mapping))
    print("[TRAINING] Total face samples:", len(faces))

    return True


# =========================================================
# 8. RECOGNIZE A FACE
# =========================================================

def recognize_face(face, model, labels):

    try:

        label, confidence = model.predict(face)

        if confidence > CONFIDENCE_THRESHOLD:
            return None, confidence

        employee_id = labels.get(str(label))

        if employee_id is None:
            return None, confidence

        return str(employee_id), confidence

    except Exception as error:

        print("[RECOGNITION ERROR]", error)

        return None, 999


# =========================================================
# 9. GET EMPLOYEE NAME
# =========================================================

def get_employee_name(employee_id):

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT name
            FROM employees
            WHERE employee_id = ?
            """,
            (str(employee_id),)
        )

        result = cursor.fetchone()

        if result:
            return result["name"]

        return "Unknown Employee"

    finally:
        connection.close()


# =========================================================
# 10. MARK EMPLOYEE CHECK-IN
# =========================================================

def mark_checkin(employee_id, employee_name):

    connection = get_connection()

    try:

        cursor = connection.cursor()

        today = date.today().isoformat()

        current_time = datetime.now().strftime("%H:%M:%S")

        cursor.execute(
            """
            SELECT id
            FROM attendance
            WHERE employee_id = ?
              AND date = ?
            """,
            (str(employee_id), today)
        )

        existing = cursor.fetchone()

        if existing:

            print(
                f"[CHECK-IN] Already recorded today: "
                f"{employee_name} ({employee_id})"
            )

            return False

        cursor.execute(
            """
            INSERT INTO attendance (
                employee_id,
                employee_name,
                date,
                check_in,
                check_out,
                total_hours,
                status,
                attendance_source
            )
            VALUES (?, ?, ?, ?, NULL, 0, 'Present', 'CCTV')
            """,
            (
                str(employee_id),
                employee_name,
                today,
                current_time
            )
        )

        connection.commit()

        print(
            f"[CHECK-IN] {employee_name} "
            f"({employee_id}) at {current_time}"
        )

        generate_daily_xml()

        return True

    except sqlite3.Error as error:

        connection.rollback()

        print("[CHECK-IN DATABASE ERROR]", error)

        return False

    finally:
        connection.close()


# =========================================================
# 11. MARK EMPLOYEE CHECK-OUT
# =========================================================

def mark_checkout(employee_id, employee_name):

    connection = get_connection()

    try:

        cursor = connection.cursor()

        today = date.today().isoformat()

        current_time = datetime.now()

        cursor.execute(
            """
            SELECT id, check_in, check_out
            FROM attendance
            WHERE employee_id = ?
              AND date = ?
            """,
            (str(employee_id), today)
        )

        record = cursor.fetchone()

        if not record:

            print(
                f"[CHECK-OUT] No check-in found for "
                f"{employee_name}"
            )

            return False

        if record["check_out"]:

            print(
                f"[CHECK-OUT] Already checked out: "
                f"{employee_name}"
            )

            return False

        check_in_time = datetime.strptime(
            record["check_in"],
            "%H:%M:%S"
        )

        check_out_time = datetime.strptime(
            current_time.strftime("%H:%M:%S"),
            "%H:%M:%S"
        )

        total_seconds = (
            check_out_time - check_in_time
        ).total_seconds()

        if total_seconds < 0:
            total_seconds += 24 * 60 * 60

        total_hours = round(
            total_seconds / 3600,
            2
        )

        cursor.execute(
            """
            UPDATE attendance
            SET check_out = ?,
                total_hours = ?
            WHERE id = ?
            """,
            (
                current_time.strftime("%H:%M:%S"),
                total_hours,
                record["id"]
            )
        )

        connection.commit()

        print(
            f"[CHECK-OUT] {employee_name} "
            f"at {current_time.strftime('%H:%M:%S')} "
            f"| Hours: {total_hours}"
        )

        generate_daily_xml()

        return True

    except (sqlite3.Error, ValueError) as error:

        connection.rollback()

        print("[CHECK-OUT ERROR]", error)

        return False

    finally:
        connection.close()


# =========================================================
# 12. GENERATE DAILY XML REPORT
# =========================================================

def generate_daily_xml():

    today = date.today().isoformat()

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
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
            ORDER BY check_in
            """,
            (today,)
        )

        records = cursor.fetchall()

    finally:
        connection.close()

    root = ET.Element("AttendanceReport")
    root.set("date", today)

    fields = [
        "employee_id",
        "employee_name",
        "date",
        "check_in",
        "check_out",
        "total_hours",
        "status"
    ]

    for record in records:

        employee = ET.SubElement(root, "Employee")

        for field in fields:

            element = ET.SubElement(employee, field)

            value = record[field]

            element.text = (
                "" if value is None else str(value)
            )

    tree = ET.ElementTree(root)

    output_path = os.path.join(
        REPORT_FOLDER,
        f"attendance_{today}.xml"
    )

    tree.write(
        output_path,
        encoding="utf-8",
        xml_declaration=True
    )

    return output_path


# =========================================================
# 13. OPEN TAPO C500 CAMERA
# =========================================================

def open_tapo_camera():

    rtsp_url = os.environ.get(
        "TAPO_RTSP_URL",
        ""
    ).strip()

    print(
        "[CAMERA DEBUG] RTSP environment variable exists:",
        bool(rtsp_url)
    )

    if not rtsp_url:

        raise RuntimeError(
            "TAPO_RTSP_URL is missing from the Flask process."
        )

    print("[CAMERA] Connecting to Tapo C500...")

    cap = cv2.VideoCapture(
        rtsp_url,
        cv2.CAP_FFMPEG
    )

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

    if not cap.isOpened():

        cap.release()

        raise RuntimeError(
            "RTSP connection failed. "
            "Check camera credentials, IP and stream path."
        )

    print("[CAMERA] Tapo C500 connected successfully.")

    return cap


# =========================================================
# 14. CAMERA STATUS
# =========================================================

def set_camera_status(status, error=""):

    global CAMERA_STATUS
    global CAMERA_ERROR

    with camera_status_lock:

        CAMERA_STATUS = status
        CAMERA_ERROR = error


def get_camera_status():

    with camera_status_lock:

        return {
            "status": CAMERA_STATUS,
            "error": CAMERA_ERROR
        }


# =========================================================
# 15. LIVE CCTV FACE RECOGNITION
# =========================================================

def live_cctv_recognition():

    global latest_frame

    print("[CAMERA] Loading face detector...")

    detector = load_face_detector()

    print("[CAMERA] Loading trained model...")

    model, labels = load_face_model()

    # Employee tracking information
    tracked_faces = {}

    # Number of consecutive recognized frames
    stable_counts = {}

    # Last successful attendance action
    last_action = {}

    cap = None

    try:

        while not camera_stop_event.is_set():

            # -------------------------------------------------
            # CONNECT / RECONNECT CAMERA
            # -------------------------------------------------

            if cap is None or not cap.isOpened():

                set_camera_status("CONNECTING")

                try:

                    if cap is not None:
                        cap.release()

                    cap = open_tapo_camera()

                    set_camera_status("LIVE")

                except Exception as error:

                    set_camera_status(
                        "RECONNECTING",
                        str(error)
                    )

                    print(
                        "[CAMERA CONNECTION ERROR]",
                        error
                    )

                    time.sleep(3)

                    continue

            # -------------------------------------------------
            # READ CAMERA FRAME
            # -------------------------------------------------

            success, frame = cap.read()

            if not success or frame is None:

                set_camera_status(
                    "RECONNECTING",
                    "Unable to read CCTV frame."
                )

                cap.release()
                cap = None

                time.sleep(1)

                continue

            frame = cv2.resize(
                frame,
                (FRAME_WIDTH, FRAME_HEIGHT)
            )

            gray = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2GRAY
            )

            faces = detector.detectMultiScale(
                gray,
                scaleFactor=1.2,
                minNeighbors=5,
                minSize=(60, 60)
            )

            height, width = frame.shape[:2]

            line_x = int(width * LINE_POSITION)

            # Draw virtual entry/exit line
            cv2.line(
                frame,
                (line_x, 0),
                (line_x, height),
                (0, 255, 255),
                2
            )

            current_time = time.time()

            # Track employees detected in this frame
            seen_employees = set()

            # -------------------------------------------------
            # PROCESS DETECTED FACES
            # -------------------------------------------------

            for (x, y, w, h) in faces:

                face = gray[
                    y:y + h,
                    x:x + w
                ]

                face = cv2.resize(
                    face,
                    (200, 200)
                )

                employee_id, confidence = recognize_face(
                    face,
                    model,
                    labels
                )

                # ---------------------------------------------
                # UNKNOWN PERSON
                # ---------------------------------------------

                if employee_id is None:

                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + w, y + h),
                        (0, 0, 255),
                        2
                    )

                    cv2.putText(
                        frame,
                        "Unknown",
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 0, 255),
                        2
                    )

                    continue

                # ---------------------------------------------
                # KNOWN EMPLOYEE
                # ---------------------------------------------

                employee_name = get_employee_name(employee_id)

                center_x = x + w // 2
                center_y = y + h // 2

                seen_employees.add(employee_id)

                previous_position = tracked_faces.get(
                    employee_id
                )

                # Update consecutive recognition count
                stable_counts[employee_id] = (
                    stable_counts.get(employee_id, 0) + 1
                )

                # Update employee tracking
                tracked_faces[employee_id] = {
                    "x": center_x,
                    "y": center_y,
                    "time": current_time
                }

                direction = None

                # ---------------------------------------------
                # DETECT VIRTUAL LINE CROSSING
                # ---------------------------------------------

                if previous_position is not None:

                    old_x = previous_position["x"]

                    # Left to right = ENTRY
                    if (
                        old_x < line_x - LINE_MARGIN
                        and center_x > line_x + LINE_MARGIN
                    ):

                        direction = "ENTRY"

                    # Right to left = EXIT
                    elif (
                        old_x > line_x + LINE_MARGIN
                        and center_x < line_x - LINE_MARGIN
                    ):

                        direction = "EXIT"

                # ---------------------------------------------
                # AUTOMATIC CHECK-IN AFTER STABLE RECOGNITION
                # ---------------------------------------------

                if (
                    stable_counts[employee_id]
                    >= STABLE_FRAMES_REQUIRED
                ):

                    previous_action_time = last_action.get(
                        employee_id,
                        0
                    )

                    cooldown_finished = (
                        current_time - previous_action_time
                        >= ACTION_COOLDOWN
                    )

                    # Check-in does not require line crossing.
                    # It happens after stable face recognition.
                    if cooldown_finished:

                        attendance_saved = mark_checkin(
                            employee_id,
                            employee_name
                        )

                        if attendance_saved:

                            last_action[employee_id] = current_time

                # ---------------------------------------------
                # CHECK-OUT AFTER RIGHT-TO-LEFT CROSSING
                # ---------------------------------------------

                if direction == "EXIT":

                    previous_action_time = last_action.get(
                        employee_id,
                        0
                    )

                    cooldown_finished = (
                        current_time - previous_action_time
                        >= ACTION_COOLDOWN
                    )

                    if cooldown_finished:

                        checkout_saved = mark_checkout(
                            employee_id,
                            employee_name
                        )

                        if checkout_saved:

                            last_action[employee_id] = current_time

                # ---------------------------------------------
                # DRAW EMPLOYEE RECOGNITION
                # ---------------------------------------------

                cv2.rectangle(
                    frame,
                    (x, y),
                    (x + w, y + h),
                    (0, 255, 0),
                    2
                )

                display_text = (
                    f"{employee_name} ({employee_id})"
                )

                cv2.putText(
                    frame,
                    display_text,
                    (x, max(y - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2
                )

                cv2.circle(
                    frame,
                    (center_x, center_y),
                    4,
                    (255, 0, 0),
                    -1
                )

                # Show recognition stability
                cv2.putText(
                    frame,
                    f"Stable: {stable_counts[employee_id]}",
                    (x, y + h + 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (255, 255, 0),
                    1
                )

            # -------------------------------------------------
            # RESET STABILITY WHEN EMPLOYEE DISAPPEARS
            # -------------------------------------------------

            for employee_id in list(stable_counts.keys()):

                if employee_id not in seen_employees:

                    stable_counts[employee_id] = 0

            # -------------------------------------------------
            # REMOVE OLD TRACKING DATA
            # -------------------------------------------------

            for employee_id in list(tracked_faces.keys()):

                last_seen = tracked_faces[employee_id]["time"]

                if current_time - last_seen > TRACK_TIMEOUT:

                    del tracked_faces[employee_id]

                    stable_counts.pop(
                        employee_id,
                        None
                    )

            # -------------------------------------------------
            # CAMERA STATUS OVERLAY
            # -------------------------------------------------

            cv2.putText(
                frame,
                "TAPO C500 - LIVE",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                "Face Recognition: ACTIVE",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2
            )

            # -------------------------------------------------
            # PUBLISH FRAME FOR FLASK
            # -------------------------------------------------

            encoded, buffer = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), 80]
            )

            if encoded:

                with frame_lock:

                    latest_frame = buffer.tobytes()

            # -------------------------------------------------
            # OPTIONAL OPENCV WINDOW
            # -------------------------------------------------

            if SHOW_CAMERA_WINDOW:

                cv2.imshow(
                    "Tapo C500 CCTV Attendance",
                    frame
                )

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    finally:

        if cap is not None:
            cap.release()

        if SHOW_CAMERA_WINDOW:
            cv2.destroyAllWindows()

        if camera_stop_event.is_set():
            set_camera_status("STOPPED")


# =========================================================
# 16. CAMERA WORKER
# =========================================================

def camera_worker():

    try:

        set_camera_status("STARTING")

        camera_stop_event.clear()

        live_cctv_recognition()

    except Exception as error:

        print("[CAMERA WORKER ERROR]", error)

        set_camera_status(
            "ERROR",
            str(error)
        )

    finally:

        if camera_stop_event.is_set():
            set_camera_status("STOPPED")


# =========================================================
# 17. START CAMERA WORKER
# =========================================================

def start_camera_worker():

    global camera_thread

    with camera_lock:

        if (
            camera_thread is not None
            and camera_thread.is_alive()
        ):

            print("[CAMERA] Camera is already running.")

            return False

        camera_stop_event.clear()

        set_camera_status("STARTING")

        camera_thread = threading.Thread(
            target=camera_worker,
            daemon=True,
            name="TapoC500CameraWorker"
        )

        camera_thread.start()

        print("[CAMERA] Worker started.")

        return True


# =========================================================
# 18. STOP CAMERA WORKER
# =========================================================

def stop_camera_worker():

    global camera_thread
    global latest_frame

    camera_stop_event.set()

    if (
        camera_thread is not None
        and camera_thread.is_alive()
    ):

        camera_thread.join(timeout=5)

    set_camera_status("STOPPED")

    print("[CAMERA] Worker stopped.")

    return True


# =========================================================
# 19. FLASK VIDEO STREAM
# =========================================================

def generate_video_frames():

    while True:

        with frame_lock:
            frame = latest_frame

        if frame is None:

            time.sleep(0.1)

            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )

        time.sleep(0.03)


# =========================================================
# 20. RECOGNIZE AN IMAGE
# =========================================================

def recognize_image(image_path):

    if not os.path.exists(image_path):

        raise FileNotFoundError(
            "Image file not found."
        )

    detector = load_face_detector()

    model, labels = load_face_model()

    image = cv2.imread(image_path)

    if image is None:

        raise ValueError(
            "Unable to read the image."
        )

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=5,
        minSize=(60, 60)
    )

    results = []

    for (x, y, w, h) in faces:

        face = gray[
            y:y + h,
            x:x + w
        ]

        face = cv2.resize(
            face,
            (200, 200)
        )

        employee_id, confidence = recognize_face(
            face,
            model,
            labels
        )

        if employee_id is None:
            continue

        employee_name = get_employee_name(employee_id)

        results.append({
            "employee_id": employee_id,
            "employee_name": employee_name,
            "confidence": float(confidence)
        })

    return results


# =========================================================
# 21. MAIN MENU
# =========================================================

def main():

    ensure_tables()

    while True:

        print("\n====================================")
        print(" CCTV ATTENDANCE MANAGEMENT SYSTEM")
        print("====================================")
        print("1. Train Face Recognition Model")
        print("2. Recognize Image")
        print("3. Start Live Tapo CCTV")
        print("4. Stop Live CCTV")
        print("5. Generate Daily XML Report")
        print("6. Exit")
        print("====================================")

        choice = input("Enter your choice: ").strip()

        if choice == "1":

            try:
                train_model()

            except Exception as error:
                print("[TRAINING ERROR]", error)

        elif choice == "2":

            image_path = input(
                "Enter image path: "
            ).strip().strip('"')

            try:

                results = recognize_image(image_path)

                if not results:
                    print("No known employee detected.")

                for result in results:

                    print(
                        result["employee_id"],
                        result["employee_name"],
                        result["confidence"]
                    )

            except Exception as error:
                print("[IMAGE RECOGNITION ERROR]", error)

        elif choice == "3":

            started = start_camera_worker()

            if started:
                print("Camera start requested.")
            else:
                print("Camera is already running.")

            while (
                camera_thread is not None
                and camera_thread.is_alive()
            ):

                try:
                    time.sleep(1)

                except KeyboardInterrupt:

                    stop_camera_worker()
                    break

        elif choice == "4":

            stop_camera_worker()

        elif choice == "5":

            try:

                output = generate_daily_xml()

                print(
                    "XML report generated:",
                    output
                )

            except Exception as error:
                print("[XML ERROR]", error)

        elif choice == "6":

            stop_camera_worker()

            print("Exiting system.")

            break

        else:

            print("Invalid choice. Try again.")


# =========================================================
# 22. RUN STANDALONE
# =========================================================

if __name__ == "__main__":

    ensure_tables()

    main()
