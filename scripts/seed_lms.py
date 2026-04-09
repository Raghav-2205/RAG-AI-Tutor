import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from bson import ObjectId

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.auth import get_password_hash
from backend.utils.db import db_manager


TEACHER_ID = "65f100000000000000000001"
STUDENT_IDS = [f"65f10000000000000000010{i}" for i in range(1, 9)]
CLASS_IDS = ["lms-class-physics-101", "lms-class-math-201"]
ASSIGNMENT_IDS = [
    "lms-assignment-physics-1",
    "lms-assignment-physics-2",
    "lms-assignment-math-1",
    "lms-assignment-math-2",
]
QUIZ_IDS = ["lms-quiz-physics-1", "lms-quiz-math-1"]


def utcnow():
    return datetime.now(timezone.utc)


def user_doc(_id: str, name: str, email: str, role: str):
    return {
        "_id": ObjectId(_id),
        "name": name,
        "email": email,
        "hashed_password": get_password_hash("Password@123"),
        "role": role,
        "level": "undergraduate" if role.lower() == "student" else "faculty",
        "created_at": utcnow(),
    }


async def clear_seed_data(db):
    await db.users.delete_many(
        {
            "$or": [
                {"_id": {"$in": [ObjectId(TEACHER_ID)] + [ObjectId(sid) for sid in STUDENT_IDS]}},
                {"email": {"$regex": r"^lms\.(teacher|student)"}},
            ]
        }
    )
    await db.classes.delete_many({"id": {"$in": CLASS_IDS}})
    await db.assignments.delete_many({"id": {"$in": ASSIGNMENT_IDS}})
    await db.submissions.delete_many({"assignment_id": {"$in": ASSIGNMENT_IDS}})
    await db.lms_quizzes.delete_many({"id": {"$in": QUIZ_IDS}})
    await db.quiz_questions.delete_many({"quiz_id": {"$in": QUIZ_IDS}})
    await db.quiz_attempts.delete_many({"quiz_id": {"$in": QUIZ_IDS}})
    await db.attendance.delete_many({"class_id": {"$in": CLASS_IDS}})
    await db.attendance_records.delete_many({"class_id": {"$in": CLASS_IDS}})
    await db.announcements.delete_many({"class_id": {"$in": CLASS_IDS}})
    await db.activity_logs.delete_many({"class_id": {"$in": CLASS_IDS}})


async def seed_users(db):
    teacher = user_doc(TEACHER_ID, "LMS Teacher", "lms.teacher@example.com", "Teacher")
    students = [
        user_doc(sid, f"LMS Student {i+1}", f"lms.student{i+1}@example.com", "Student")
        for i, sid in enumerate(STUDENT_IDS)
    ]
    for doc in [teacher] + students:
        await db.users.replace_one({"_id": doc["_id"]}, doc, upsert=True)


async def seed_classes(db):
    docs = [
        {
            "id": CLASS_IDS[0],
            "name": "Physics Fundamentals",
            "section": "A",
            "description": "Core mechanics and problem solving.",
            "subject": "Physics",
            "teacher_id": TEACHER_ID,
            "join_code": "PHY101AA",
            "is_active": True,
            "students": STUDENT_IDS[:6],
            "created_at": utcnow(),
        },
        {
            "id": CLASS_IDS[1],
            "name": "Applied Mathematics",
            "section": "B",
            "description": "Algebra and calculus for engineering.",
            "subject": "Mathematics",
            "teacher_id": TEACHER_ID,
            "join_code": "MTH201BB",
            "is_active": True,
            "students": STUDENT_IDS[2:],
            "created_at": utcnow(),
        },
    ]
    for doc in docs:
        await db.classes.replace_one({"id": doc["id"]}, doc, upsert=True)


async def seed_assignments(db):
    due = utcnow() + timedelta(days=7)
    docs = [
        {"id": ASSIGNMENT_IDS[0], "class_id": CLASS_IDS[0], "title": "Newton Laws Worksheet", "max_points": 100},
        {"id": ASSIGNMENT_IDS[1], "class_id": CLASS_IDS[0], "title": "Kinematics Lab Report", "max_points": 100},
        {"id": ASSIGNMENT_IDS[2], "class_id": CLASS_IDS[1], "title": "Linear Algebra Set", "max_points": 100},
        {"id": ASSIGNMENT_IDS[3], "class_id": CLASS_IDS[1], "title": "Calculus Practice", "max_points": 100},
    ]
    full_docs = []
    for d in docs:
        full_docs.append(
            {
                **d,
                "description": f"Submit {d['title']} before deadline.",
                "type": "homework",
                "due_date": due,
                "allow_late": False,
                "created_by": TEACHER_ID,
                "created_at": utcnow(),
            }
        )
    for doc in full_docs:
        await db.assignments.replace_one({"id": doc["id"]}, doc, upsert=True)

    submissions = []
    for a in full_docs:
        class_students = STUDENT_IDS[:6] if a["class_id"] == CLASS_IDS[0] else STUDENT_IDS[2:]
        for i, sid in enumerate(class_students):
            submissions.append(
                {
                    "id": f"sub-{a['id']}-{i+1}",
                    "assignment_id": a["id"],
                    "student_id": sid,
                    "content": "Completed assignment solution.",
                    "file_url": None,
                    "status": "graded" if i % 2 == 0 else "submitted",
                    "submitted_at": utcnow() - timedelta(days=1),
                    "points_earned": 80 + (i % 5) if i % 2 == 0 else None,
                    "feedback": "Good work, improve explanations." if i % 2 == 0 else None,
                }
            )
    for doc in submissions:
        await db.submissions.replace_one({"id": doc["id"]}, doc, upsert=True)


async def seed_quizzes(db):
    quizzes = [
        {
            "id": QUIZ_IDS[0],
            "class_id": CLASS_IDS[0],
            "title": "Physics Quiz 1",
            "description": "Mechanics basics",
            "time_limit": 20,
        },
        {
            "id": QUIZ_IDS[1],
            "class_id": CLASS_IDS[1],
            "title": "Math Quiz 1",
            "description": "Algebra basics",
            "time_limit": 25,
        },
    ]
    for q in quizzes:
        doc = {
            **q,
            "created_by": TEACHER_ID,
            "type": "quiz",
            "max_attempts": 1,
            "is_published": True,
            "created_at": utcnow(),
        }
        await db.lms_quizzes.replace_one({"id": doc["id"]}, doc, upsert=True)

    question_docs = []
    attempt_docs = []
    for q in quizzes:
        q1 = f"{q['id']}-q1"
        q2 = f"{q['id']}-q2"
        question_docs.extend(
            [
                {
                    "id": q1,
                    "quiz_id": q["id"],
                    "question": "Choose the correct statement.",
                    "type": "mcq",
                    "options": [
                        {"label": "A", "text": "Option A", "is_correct": False},
                        {"label": "B", "text": "Option B", "is_correct": True},
                    ],
                    "answer_key": "B",
                    "points": 5,
                    "order_index": 0,
                },
                {
                    "id": q2,
                    "quiz_id": q["id"],
                    "question": "Second concept check.",
                    "type": "mcq",
                    "options": [
                        {"label": "A", "text": "Option A", "is_correct": True},
                        {"label": "B", "text": "Option B", "is_correct": False},
                    ],
                    "answer_key": "A",
                    "points": 5,
                    "order_index": 1,
                },
            ]
        )

        class_students = STUDENT_IDS[:6] if q["class_id"] == CLASS_IDS[0] else STUDENT_IDS[2:]
        for i, sid in enumerate(class_students):
            score = 10 if i % 2 == 0 else 5
            attempt_docs.append(
                {
                    "id": f"attempt-{q['id']}-{i+1}",
                    "quiz_id": q["id"],
                    "student_id": sid,
                    "answers": {q1: "B", q2: "A" if i % 2 == 0 else "B"},
                    "score": score,
                    "max_score": 10,
                    "percentage": (score / 10) * 100,
                    "correct_count": 2 if i % 2 == 0 else 1,
                    "question_results": [
                        {"question_id": q1, "is_correct": True},
                        {"question_id": q2, "is_correct": i % 2 == 0},
                    ],
                    "submitted_at": utcnow() - timedelta(hours=4),
                    "is_complete": True,
                }
            )

    for doc in question_docs:
        await db.quiz_questions.replace_one({"id": doc["id"]}, doc, upsert=True)
    for doc in attempt_docs:
        await db.quiz_attempts.replace_one({"id": doc["id"]}, doc, upsert=True)


async def seed_attendance(db):
    dates = [(utcnow() - timedelta(days=i)).date().isoformat() for i in range(3, 0, -1)]
    attendance_docs = []
    record_docs = []
    for class_id in CLASS_IDS:
        students = STUDENT_IDS[:6] if class_id == CLASS_IDS[0] else STUDENT_IDS[2:]
        for d in dates:
            records = []
            for i, sid in enumerate(students):
                status = "present" if (i + len(d)) % 4 != 0 else "absent"
                records.append({"student_id": sid, "status": status})
                record_docs.append(
                    {
                        "class_id": class_id,
                        "student_id": sid,
                        "date": d,
                        "status": status,
                        "updated_at": utcnow(),
                    }
                )
            attendance_docs.append(
                {
                    "id": f"att-{class_id}-{d}",
                    "class_id": class_id,
                    "date": d,
                    "records": records,
                    "created_at": utcnow(),
                }
            )
    for doc in attendance_docs:
        await db.attendance.replace_one(
            {"class_id": doc["class_id"], "date": doc["date"]},
            doc,
            upsert=True,
        )
    for doc in record_docs:
        await db.attendance_records.update_one(
            {"class_id": doc["class_id"], "student_id": doc["student_id"], "date": doc["date"]},
            {"$set": doc},
            upsert=True,
        )


async def seed_announcements(db):
    docs = [
        {
            "id": "ann-physics-1",
            "class_id": CLASS_IDS[0],
            "author_id": TEACHER_ID,
            "title": "Physics class update",
            "content": "Bring lab notebook for tomorrow.",
            "priority": "normal",
            "created_at": utcnow().isoformat(),
        },
        {
            "id": "ann-math-1",
            "class_id": CLASS_IDS[1],
            "author_id": TEACHER_ID,
            "title": "Math quiz reminder",
            "content": "Quiz opens at 10 AM Friday.",
            "priority": "high",
            "created_at": utcnow().isoformat(),
        },
    ]
    for doc in docs:
        await db.announcements.replace_one({"id": doc["id"]}, doc, upsert=True)


async def seed_activity_logs(db):
    docs = []
    for index, student_id in enumerate(STUDENT_IDS[:6]):
        docs.append(
            {
                "id": f"log-physics-chat-{index+1}",
                "user_id": student_id,
                "class_id": CLASS_IDS[0],
                "category": "chat",
                "data": {"messages": 1},
                "date": (utcnow() - timedelta(minutes=10 + index)).strftime("%Y-%m-%dT%H:%M:%S"),
                "logged_at": utcnow() - timedelta(minutes=10 + index),
            }
        )
    for index, student_id in enumerate(STUDENT_IDS[2:]):
        docs.append(
            {
                "id": f"log-math-quiz-{index+1}",
                "user_id": student_id,
                "class_id": CLASS_IDS[1],
                "category": "quiz_attempt",
                "data": {"quiz_id": QUIZ_IDS[1]},
                "date": (utcnow() - timedelta(minutes=20 + index)).strftime("%Y-%m-%dT%H:%M:%S"),
                "logged_at": utcnow() - timedelta(minutes=20 + index),
            }
        )
    for doc in docs:
        await db.activity_logs.replace_one({"id": doc["id"]}, doc, upsert=True)


async def run(reset: bool):
    await db_manager.connect()
    db = db_manager.db
    try:
        if reset:
            await clear_seed_data(db)
        await seed_users(db)
        await seed_classes(db)
        await seed_assignments(db)
        await seed_quizzes(db)
        await seed_attendance(db)
        await seed_announcements(db)
        await seed_activity_logs(db)
        print("LMS seed complete.")
        print("Teacher: lms.teacher@example.com / Password@123")
        print("Students: lms.student1@example.com ... lms.student8@example.com / Password@123")
        if reset:
            print("Mode: reset")
        else:
            print("Mode: append (seed namespace refreshed)")
    finally:
        await db_manager.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed deterministic LMS fixtures.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reset", action="store_true", help="Clear existing seed namespace and insert fixtures.")
    mode.add_argument("--append", action="store_true", help="Insert or refresh only seed namespace fixtures.")
    args = parser.parse_args()
    asyncio.run(run(reset=args.reset))
