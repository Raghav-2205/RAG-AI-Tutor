import asyncio
import sys
import os
import random
from datetime import datetime, timedelta

# Append root to path so we can import backend
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.db import get_db, db_manager
from backend.auth import get_password_hash
from backend.services import lms_service

async def seed_database():
    await db_manager.connect()
    db = db_manager.db

    print("🧹 Clearing old dummy data...")
    # Clean previous generated stuff to avoid duplication
    await db.users.delete_many({"email": {"$in": ["professor@school.edu", "alice@school.edu", "bob@school.edu", "charlie@school.edu", "diana@school.edu"]}})
    await db.classes.delete_many({})
    await db.assignments.delete_many({})
    await db.submissions.delete_many({})
    await db.lms_quizzes.delete_many({})
    await db.quiz_questions.delete_many({})
    await db.quiz_attempts.delete_many({})
    await db.attendance.delete_many({})
    await db.attendance_records.delete_many({})
    await db.announcements.delete_many({})

    print("🌱 Seeding database with dummy LMS data strictly via lms_service...")

    # 1. Create Teacher
    teacher_email = "professor@school.edu"
    result = await db.users.insert_one({
        "name": "Dr. Alan Turing",
        "email": teacher_email,
        "hashed_password": get_password_hash("password"),
        "level": "postgraduate",
        "role": "Teacher",
        "created_at": datetime.utcnow()
    })
    teacher_id = str(result.inserted_id)
    print(f"✅ Created Teacher: {teacher_email}")

    # 2. Create Students
    students_data = [
        {"name": "Alice Smith", "email": "alice@school.edu"},
        {"name": "Bob Johnson", "email": "bob@school.edu"},
        {"name": "Charlie Davis", "email": "charlie@school.edu"},
        {"name": "Diana Prince", "email": "diana@school.edu"},
    ]
    student_ids = []
    
    for s in students_data:
        res = await db.users.insert_one({
            "name": s["name"],
            "email": s["email"],
            "hashed_password": get_password_hash("password"),
            "level": "undergraduate",
            "role": "Student",
            "created_at": datetime.utcnow()
        })
        student_ids.append(str(res.inserted_id))
        print(f"✅ Created Student: {s['email']}")

    # 3. Create Classes using LMS Service
    classes_data = [
        {"name": "Introduction to AI", "subject": "Computer Science", "section": "CS101", "description": "Learn the basics of Artificial Intelligence."},
        {"name": "Data Structures", "subject": "Computer Science", "section": "CS201", "description": "Advanced trees, graphs, and algorithms."},
        {"name": "Web Engineering", "subject": "Software", "section": "SE301", "description": "Full-stack web development principles."}
    ]
    class_ids = []

    for c in classes_data:
        cls = await lms_service.create_class(
            db, teacher_id, c["name"], c["section"], c["description"], c["subject"]
        )
        cid = cls["id"]
        class_ids.append(cid)
        print(f"✅ Created Class: {c['name']} (Code: {cls['join_code']})")
        
        # Enroll students natively
        for sid in student_ids:
            # lms_service.enroll_student pushes just the string ID natively
            await lms_service.enroll_student(db, cls["join_code"], sid)

    # 4. Create Assignments & Submissions
    for i, cid in enumerate(class_ids):
        assgn = await lms_service.create_assignment(
            db=db,
            class_id=cid,
            created_by=teacher_id,
            title=f"Week {i+1} Assignment",
            description="Please complete the attached exercises and upload your PDF.",
            due_date=datetime.utcnow() + timedelta(days=7),
            max_points=100
        )
        assgn_id = assgn["id"]
        print(f"✅ Created Assignment for class {cid}")

        # Submissions
        for sid in student_ids:
            if random.random() > 0.2: # 80% submission rate
                graded = random.random() > 0.5
                sub = await lms_service.submit_assignment(
                    db=db,
                    assignment_id=assgn_id,
                    student_id=sid,
                    content="Here is my completed assignment.",
                    file_url=None
                )
                if graded:
                    await lms_service.grade_submission(
                        db=db,
                        submission_id=sub["id"],
                        graded_by=teacher_id,
                        points_earned=random.randint(70, 100),
                        feedback="Good job!"
                    )

    # 5. Create Announcements manually (since no service method explicitly listed)
    for cid in class_ids:
        import uuid
        await db.announcements.insert_one({
            "id": str(uuid.uuid4()),
            "class_id": cid,
            "author_id": teacher_id,
            "title": "Welcome to the new semester!",
            "content": "Please review the syllabus uploaded in the materials section.",
            "priority": "high",
            "created_at": datetime.utcnow().isoformat()
        })
        print(f"✅ Created announcement for class {cid}")

    # 6. Create Quizzes
    for i, cid in enumerate(class_ids):
        questions = [
            {"type": "mcq", "question": "What does CPU stand for?", "options": [{"label": "Central Process Unit", "is_correct": False}, {"label": "Computer Personal Unit", "is_correct": False}, {"label": "Central Processing Unit", "is_correct": True}], "answer_key": "Central Processing Unit", "points": 10},
            {"type": "mcq", "question": "HTML is a programming language.", "options": [{"label": "True", "is_correct": False}, {"label": "False", "is_correct": True}], "answer_key": "False", "points": 10}
        ]
        
        quiz = await lms_service.create_quiz(
            db=db,
            class_id=cid,
            created_by=teacher_id,
            title=f"Midterm Quiz {i+1}",
            description="A quick test of your knowledge.",
            max_attempts=1,
            questions=questions
        )
        quiz_id = quiz["id"]
        print(f"✅ Created Quiz for class {cid}")

        # Quiz Attempts
        for sid in student_ids:
            if random.random() > 0.1:
                # Mock answers to match question ids
                # First fetch the created questions
                q_cursor = db.quiz_questions.find({"quiz_id": quiz_id})
                q_list = await q_cursor.to_list(None)
                answers = {}
                score = random.choice([10, 20])
                if len(q_list) >= 2:
                    answers[str(q_list[0]["id"])] = "Central Processing Unit"
                    answers[str(q_list[1]["id"])] = "False" if score == 20 else "True"
                
                # submit attempt natively
                # submit_quiz_attempt calculates percentage etc.
                await lms_service.submit_quiz_attempt(
                    db=db,
                    quiz_id=quiz_id,
                    student_id=sid,
                    answers=answers
                )

    # 7. Add Attendance for a few days
    for cid in class_ids:
        dates = [(datetime.utcnow() - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(1, 4)]
        for date in dates:
            for sid in student_ids:
                status = "present" if random.random() > 0.15 else "absent"
                # Use native mark_attendance which populates attendance_records too
                await lms_service.mark_attendance(
                    db=db,
                    class_id=cid,
                    date_str=date,
                    records=[{"student_id": sid, "status": status}]
                )

    print("🎉 Database successfully seeded with NATIVE schemas!")
    await db_manager.disconnect()

if __name__ == "__main__":
    asyncio.run(seed_database())
