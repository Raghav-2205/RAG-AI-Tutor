// backend/database/mongodb/collections.js
// MongoDB shell script - Run: mongosh < collections.js

// Optimal collection creation with validators
db.createCollection("users", {
   validator: {
      $jsonSchema: {
         bsonType: "object",
         required: ["email", "name", "level", "password"],
         properties: {
            email: { bsonType: "string", pattern: "^.+@.+$" },
            name: { bsonType: "string", maxLength: 100 },
            level: { 
               enum: ["school", "college", "professional", "research"] 
            }
         }
      }
   }
});

db.createCollection("documents");
db.createCollection("chats");
db.createCollection("feedback"); 
db.createCollection("quizzes");

// Default TTL for old chat sessions (30 days)
db.createCollection("chat_sessions", {
   expireAfterSeconds: 2592000
});

print("✅ Collections created with validators");
