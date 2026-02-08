flowchart TB

%% =========================
%% Personas
%% =========================
subgraph Personas
  L[Learner Student]
  A[Admin]
end

%% =========================
%% Frontend UX
%% =========================
subgraph Frontend_UX
  LOGIN[Login Page]
  SIGNUP[Signup Page]
  SUBJECTS[Subjects Dashboard]
  CHAT[Chat Interface]
  UPLOAD[Document Upload]
  QUIZ[Quiz Modal]
  FEEDBACKUI[Feedback UI]
  SIDEBAR[Sidebar Navigation]
end

%% =========================
%% Backend Services
%% =========================
subgraph Backend_Services
  AUTH[Auth Service\nJWT Issuer]
  AUTHMW[JWT Middleware\nToken Validation]
  FILEPROC[File Processing\nPDF DOCX PPTX TXT]
  PREPROC[Preprocessing\nChunking + Metadata]
  VECTORDB[Vector Store\nEmbeddings]
  RAG[RAG Pipeline]
  RERANK[Reranker\nCross Encoder]
  PROMPTENG[Prompt Engine\nSubject Aware]
  LLM[LLM Interface\nGemini API]
  CHATAPI[Chat API]
  UPLOADAPI[Upload API]
  QUIZAPI[Quiz API]
  FEEDBACKAPI[Feedback API]
end

%% =========================
%% AI Engines
%% =========================
subgraph AI_Engines
  SEARCH[Hybrid Search\nBM25 + Semantic]
  EMBED[Embedding Service\nMiniLM]
  TUTOR[Socratic Tutor]
  QUIZGEN[Quiz Generator]
  MARKDOWN[Markdown Renderer]
end

%% =========================
%% Data Layer
%% =========================
subgraph Data_Storage
  MONGODB[MongoDB]
  VECTORSTORE[Vector Store JSON]
  UPLOADS[Uploaded Files]
end

%% =========================
%% Authentication Flow
%% =========================
L --> LOGIN
L --> SIGNUP
LOGIN --> AUTH
SIGNUP --> AUTH
AUTH --> MONGODB
AUTH --> SUBJECTS

%% =========================
%% Subject Selection Flow
%% =========================
SUBJECTS --> PROMPTENG
PROMPTENG --> CHAT
PROMPTENG --> QUIZ

%% =========================
%% Document Upload Flow
%% =========================
SUBJECTS --> SIDEBAR
SIDEBAR --> UPLOAD
UPLOAD --> AUTHMW
AUTHMW --> UPLOADAPI
UPLOADAPI --> FILEPROC
FILEPROC --> PREPROC
PREPROC --> EMBED
EMBED --> VECTORDB
VECTORDB --> VECTORSTORE
UPLOADAPI --> MONGODB
UPLOADAPI --> CHAT

%% =========================
%% Chat with RAG Flow
%% =========================
L --> CHAT
CHAT --> AUTHMW
AUTHMW --> CHATAPI
CHATAPI --> MONGODB
CHATAPI --> RAG
RAG --> SEARCH
SEARCH --> VECTORDB
VECTORDB --> RERANK
RERANK --> RAG
RAG --> PROMPTENG
PROMPTENG --> TUTOR
TUTOR --> LLM
LLM --> TUTOR
TUTOR --> CHATAPI
CHATAPI --> MARKDOWN
MARKDOWN --> CHAT

%% =========================
%% Quiz Generation Flow
%% =========================
SIDEBAR --> QUIZ
QUIZ --> AUTHMW
AUTHMW --> QUIZAPI
QUIZAPI --> VECTORDB
QUIZAPI --> PROMPTENG
PROMPTENG --> QUIZGEN
QUIZGEN --> LLM
LLM --> QUIZAPI
QUIZAPI --> QUIZ

%% =========================
%% Feedback Flow (CORE ADDITION)
%% =========================
CHAT --> FEEDBACKUI
QUIZ --> FEEDBACKUI
FEEDBACKUI --> AUTHMW
AUTHMW --> FEEDBACKAPI
FEEDBACKAPI --> MONGODB

%% =========================
%% Admin Bulk Indexing
%% =========================
A --> FILEPROC
FILEPROC --> PREPROC
PREPROC --> EMBED
EMBED --> VECTORDB
VECTORDB --> SEARCH
