// backend/database/mongodb/init.js
// Complete MongoDB setup - Run once: mongosh localhost:27017/rag_tutor < init.js

load("collections.js");
load("indexes.js");

// Insert test admin user (optional)
db.users.insertOne({
   email: "admin@ragtutor.com",
   name: "Admin User",
   level: "professional",
   password: "$2b$12$KIXp",  // bcrypt hash of "admin123"
   created_at: new ISODate()
});

// Create analytics views
db.createView("user_activity", "chats", [
   { $group: { 
      _id: "$user_id", 
      total_chats: { $sum: 1 },
      subjects: { $addToSet: "$subject" }
   }}
]);

db.createView("document_stats", "documents", [
   { $group: { 
      _id: { user_id: "$user_id", subject: "$subject" },
      total_docs: { $sum: 1 },
      total_chunks: { $sum: "$chunks_count" }
   }}
]);

print("🎉 MongoDB RAG Tutor - Production ready!");
print("Collections: users, documents, chats, feedback, quizzes");
print("Views: user_activity, document_stats");
