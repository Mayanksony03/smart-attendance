from pymongo import MongoClient
import os

# Read MongoDB connection string from environment variable
MONGO_URI = os.environ.get("MONGO_URI", "")

if not MONGO_URI:
    raise Exception("MONGO_URI environment variable not set!")

client = MongoClient(MONGO_URI)
db = client["attendance_system"]

# Collections (equivalent to SQLite tables)
students_col    = db["students"]
sessions_col    = db["sessions"]
attendance_col  = db["attendance"]


# Indexes to avoid duplicates
students_col.create_index("name", unique=True)
attendance_col.create_index([("student_name", 1), ("session_id", 1)], unique=True)
teachers_col.create_index("username", unique=True)
branches_col.create_index("name", unique=True)
