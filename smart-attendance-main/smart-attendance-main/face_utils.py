import cv2
import face_recognition
import pickle
import numpy as np
import base64
from datetime import datetime
from db import students_col, attendance_col
from send_email import send_email


def decode_image(image_data):
    """Decode a base64 image (with or without data-URL prefix) into a cv2 frame."""
    if "," in image_data:
        image_data = image_data.split(",")[1]
    img_bytes = base64.b64decode(image_data)
    np_arr    = np.frombuffer(img_bytes, np.uint8)
    frame     = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return frame


def preprocess_for_recognition(frame):
    """
    Improve face detection on mobile by trying multiple image orientations.
    Mobile cameras sometimes send images rotated 90/180/270 degrees.
    Returns the frame (possibly rotated) with the best face count.
    """
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    encs = face_recognition.face_encodings(rgb)
    if encs:
        return frame, rgb, encs

    # Try rotations (common on mobile)
    for angle_code in [cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE]:
        rotated     = cv2.rotate(frame, angle_code)
        rotated_rgb = cv2.cvtColor(rotated, cv2.COLOR_BGR2RGB)
        encs        = face_recognition.face_encodings(rotated_rgb)
        if encs:
            print(f"[FACE] Detected face after rotation {angle_code}")
            return rotated, rotated_rgb, encs

    # No rotations worked — return original with empty encodings
    return frame, rgb, []


def register_face(name, student_email, parent_email, image_data, roll_no, branch, semester, section):
    frame = decode_image(image_data)
    if frame is None:
        return "Image decode error — please try again"

    # Upscale small images for better detection (common on phones with compressed captures)
    h, w = frame.shape[:2]
    if w < 300 or h < 300:
        scale = max(300 / w, 300 / h)
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)

    _, _, encodings = preprocess_for_recognition(frame)

    if len(encodings) == 0:
        return "No face detected. Make sure your face is fully visible, well-lit, and centred in the camera."
    if len(encodings) > 1:
        return "Multiple faces detected. Please ensure only one person is in the camera."

    encoding_blob = base64.b64encode(pickle.dumps(encodings[0])).decode("utf-8")

    try:
        students_col.insert_one({
            "name":          name,
            "roll_no":       roll_no,
            "branch":        branch,
            "semester":      semester,
            "section":       section,
            "encoding":      encoding_blob,
            "student_email": student_email,
            "parent_email":  parent_email
        })
        return f"Student Registered: {name}"
    except Exception as e:
        if "duplicate" in str(e).lower():
            return "Student already exists with this name"
        return f"DB error: {str(e)}"


def recognize_face(session, image_data):
    session_id = str(session["_id"])
    frame = decode_image(image_data)
    if frame is None:
        return "Image decode error — please try again"

    # Upscale if too small
    h, w = frame.shape[:2]
    if w < 300 or h < 300:
        scale = max(300 / w, 300 / h)
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)

    _, _, encodings = preprocess_for_recognition(frame)

    if len(encodings) == 0:
        return "No face detected. Ensure good lighting and face the camera directly."
    if len(encodings) > 1:
        return "Multiple faces detected. Only one person should be in frame."

    current_encoding = encodings[0]
    
    # Filter students by session's branch, semester, section
    query = {}
    if session.get("branch"): query["branch"] = session["branch"]
    if session.get("semester"): query["semester"] = str(session["semester"])
    if session.get("section"): query["section"] = session["section"]

    students         = list(students_col.find(query, {"name": 1, "encoding": 1}))

    if not students:
        return "No students registered yet. Contact admin."

    best_match    = None
    best_distance = 1.0

    for student in students:
        try:
            stored_encoding = pickle.loads(base64.b64decode(student["encoding"]))
            distance        = face_recognition.face_distance([stored_encoding], current_encoding)[0]
            if distance < best_distance:
                best_distance = distance
                best_match    = student["name"]
        except Exception as e:
            print(f"[FACE] Error comparing with {student.get('name','?')}: {e}")
            continue

    print(f"[FACE] Best match: {best_match} | Distance: {best_distance:.3f}")

    # Threshold: 0.5 is strict, 0.55 is slightly more lenient (good for mobile cameras)
    THRESHOLD = 0.55
    if best_distance < THRESHOLD and best_match:
        name     = best_match
        existing = attendance_col.find_one({
            "student_name": name,
            "session_id":   session_id
        })
        if existing:
            return f"{name} already marked PRESENT"

        attendance_col.insert_one({
            "student_name": name,
            "session_id":   session_id,
            "status":       "PRESENT",
            "time":         datetime.now().strftime("%H:%M:%S")
        })
        return f"{name} PRESENT"

    return "Face Not Recognized. Try better lighting or move closer to the camera."



