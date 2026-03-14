// backend/database/mongodb/indexes.js
// Production MongoDB indexes for sub-10ms queries

// USERS
db.users.createIndex({ email: 1 }, { unique: true, name: "users_email_unique" });
db.users.createIndex({ level: 1 }, { name: "users_level" });

// DOCUMENTS - Critical for RAG filtering
db.documents.createIndex({ user_id: 1 }, { name: "documents_user_id" });
db.documents.createIndex({ 
   user_id: 1, 
   subject: 1 
}, { 
   name: "documents_user_subject_composite",
   background: false  // Critical index - block briefly for speed
});
db.documents.createIndex({ doc_id: 1 }, { unique: true });
db.documents.createIndex({ status: 1 });

// CHATS - Timeline + search
db.chats.createIndex({ 
   user_id: 1, 
   created_at: -1 
}, { name: "chats_user_timeline" });
db.chats.createIndex({ subject: 1 });
db.chats.createIndex({ 
   user_id: 1, 
   subject: 1,
   created_at: -1 
}, { name: "chats_user_subject_timeline" });

// FEEDBACK - Analytics
db.feedback.createIndex({ user_id: 1 });
db.feedback.createIndex({ rating: 1 });
db.feedback.createIndex({ chat_session_id: 1 });

// QUIZZES
db.quizzes.createIndex({ user_id: 1 });
db.quizzes.createIndex({ user_id: 1, created_at: -1 });

print("✅ Production indexes created - RAG optimized");
