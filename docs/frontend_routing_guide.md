# RAG AI Tutor - Frontend Routing & Navigation Guide

## 📍 Page Structure

The application has 4 main HTML pages:

```
frontend/public/views/
├── home.html          # Landing page (not currently used)
├── login.html         # Authentication - Login
├── signup.html        # Authentication - Sign Up
└── subjects.html      # Main Dashboard (Student Workspace)
```

---

## 🔄 Routing Flow

### 1. **Entry Point → Authentication**

```mermaid
graph LR
    A[User Visits Site] --> B{Has JWT Token?}
    B -->|No| C[/views/login.html]
    B -->|Yes| D[/views/subjects.html]
    C --> E[User Logs In]
    E --> F[JWT Stored in localStorage]
    F --> D
```

**Key Details:**
- **No client-side routing framework** (no React Router, Vue Router, etc.)
- **Simple HTML page navigation** via `window.location.href`
- **Authentication check** happens on page load via `auth.js`

---

## 🔐 Authentication Pages

### `/views/login.html`

**Purpose:** User login
**Navigation:**
- **From:** Direct URL access or logout
- **To:** `/views/subjects.html` (on success)

**Navbar Links:**
- Home → `/`
- Sign Up → `/views/signup.html`

**Form Submission:**
```javascript
handleLogin(event) {
    // Calls POST /api/auth/login
    // Stores JWT in localStorage
    // Redirects to /views/subjects.html
}
```

---

### `/views/signup.html`

**Purpose:** New user registration
**Navigation:**
- **From:** Login page or direct URL
- **To:** `/views/subjects.html` (on success)

**Navbar Links:**
- Home → `/`
- Login → `/views/login.html`

**Form Submission:**
```javascript
handleSignup(event) {
    // Calls POST /api/auth/register
    // Stores JWT in localStorage
    // Redirects to /views/subjects.html
}
```

---

## 🎓 Main Dashboard - `/views/subjects.html`

### Layout Structure

```
┌─────────────────────────────────────────────────────┐
│  Navbar: "RAG AI Tutor" | [Logout Button]          │
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│ Sidebar  │        Main Workspace                   │
│          │                                          │
│  ➕ New  │     ┌───────────────────────────┐      │
│   Chat   │     │   Chat Feed               │      │
│          │     │   • User messages         │      │
│  📄 Tools │     │   • AI responses         │      │
│  Upload  │     │   • Citations             │      │
│  📝 Quiz │     └───────────────────────────┘      │
│  🗑️ Clear│                                         │
│          │     ┌───────────────────────────┐      │
│          │     │   Input Box               │      │
│          │     │   [Message...] [➤ Send]   │      │
│          │     └───────────────────────────┘      │
└──────────┴──────────────────────────────────────────┘
```

---

## 🧭 Sidebar Navigation

### **Section 1: Chat Management**

#### ➕ **New Chat**
```javascript
onclick="resetChat()"
```
**Action:**
- Clears chat feed
- Displays "New Conversation" message
- Resets conversation context

**Function:**
```javascript
function resetChat() {
    document.getElementById('chatFeed').innerHTML = 
        '<h1>New Conversation</h1>';
}
```

---

### **Section 2: Tools**

#### 📄 **Upload Document**
```javascript
onclick="document.getElementById('hiddenFileInput').click()"
```
**Action:**
- Triggers hidden file input
- Accepts: `.pdf`, `.docx`, `.txt`, `.pptx`, `.jpg`, `.png`

**Flow:**
1. User clicks "Upload Document"
2. File selector opens
3. `handleFileSelect(event)` triggered on file selection
4. File uploaded via `POST /api/upload/`
5. Text extracted → Chunked → Embedded → Stored in vector DB
6. Success message shown in chat

**Code:**
```javascript
async function handleFileSelect(e) {
    const file = e.target.files[0];
    const token = localStorage.getItem('token');
    
    // Upload to API
    const formData = new FormData();
    formData.append('file', file);
    formData.append('subject', 'general');
    
    const response = await fetch(`${apiBase}/upload/`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
    });
    
    // Show result in chat
}
```

---

#### 📝 **Generate Quiz**
```javascript
onclick="openQuizModal()"
```
**Action:**
- Opens modal overlay
- Requests quiz generation from API
- Displays multiple-choice questions

**Flow:**
1. User clicks "Generate Quiz"
2. Modal opens with loading state
3. `POST /api/quiz/` called
4. LLM generates MCQs from document chunks
5. Quiz rendered in modal

**Function:**
```javascript
function openQuizModal() {
    document.getElementById('quizModal').style.display = 'flex';
    // Fetch and render quiz...
}
```

---

#### 🗑️ **Clear Documents**
```javascript
onclick="clearAllDocuments()" 
style="color: #ff6b6b;"
```
**Action:**
- Deletes ALL user documents
- Clears vector store
- Confirmation dialog required

**Flow:**
1. User clicks "Clear Documents"
2. Confirmation: `confirm('Are you sure?')`
3. `DELETE /api/upload/all` called
4. MongoDB + Vector store cleared
5. Success message in chat

**Function:**
```javascript
async function clearAllDocuments() {
    if (!confirm('Are you sure?')) return;
    
    await fetch(`${apiBase}/upload/all`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
    });
    
    // Display confirmation
}
```

---

## 💬 Main Workspace - Chat Interface

### Components:

#### **1. Chat Feed** (`#chatFeed`)
- Scrollable message container
- Displays user and AI messages
- Markdown-formatted responses
- Interactive citations with hover tooltips

**Message Types:**
```html
<!-- User Message -->
<div class="msg user">What is Scrum?</div>

<!-- AI Response -->
<div class="msg ai">
    <strong>Scrum is a framework...</strong>
    <span class="citation">CHUNK 1
        <span class="citation-tooltip">
            Source: scrum_methodology.pptx
        </span>
    </span>
</div>
```

---

#### **2. Input Area**
```html
<textarea id="chatInput" placeholder="Message RAG AI Tutor..."></textarea>
<button id="sendBtn" onclick="sendMessage()">➤</button>
```

**Send Message Flow:**
1. User types question
2. Clicks send button (or Enter key)
3. `sendMessage()` called
4. Message sent to `POST /api/chat/`
5. RAG pipeline executes:
   - Searches vector DB
   - Retrieves relevant chunks
   - Builds context
   - LLM generates response
6. Response formatted with markdown + citations
7. Displayed in chat feed

**Function:**
```javascript
async function sendMessage() {
    const input = document.getElementById('chatInput');
    const feed = document.getElementById('chatFeed');
    const text = input.value.trim();
    
    // Add user message to feed
    feed.innerHTML += `<div class="msg user">${text}</div>`;
    feed.innerHTML += `<div class="msg ai">Thinking...</div>`;
    
    // Call AI
    const res = await window.ai.sendMessage(text);
    
    // Format and display response
    const formattedAnswer = window.ai.formatMessage(res.answer, res.chunks);
    feed.lastElementChild.innerHTML = formattedAnswer;
}
```

---

## 🔗 API Integration

### Backend Endpoints Used:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/register` | POST | User signup |
| `/api/auth/login` | POST | User login |
| `/api/chat/` | POST | Chat with AI tutor |
| `/api/upload/` | POST | Upload document |
| `/api/upload/all` | DELETE | Clear all documents |
| `/api/quiz/` | POST | Generate quiz |

---

## 🎨 State Management

### LocalStorage Keys:

```javascript
localStorage.setItem('token', 'JWT_TOKEN');           // Auth token
localStorage.setItem('currentSessionId', 'session_123'); // Chat session
```

### Global JavaScript Objects:

```javascript
window.ai = new AIManager();          // AI interaction manager  
window.auth = { token: '...' };       // Auth state
window.config = { apiBase: 'http://...' }; // API config
```

---

## 🚪 Logout Flow

```javascript
onclick="localStorage.clear(); window.location.href='/views/login.html';"
```

**Action:**
1. Clears all localStorage (token, session)
2. Redirects to login page
3. User must re-authenticate

---

## 🔄 Page Load Authentication Check

**In every protected page (`subjects.html`):**

```javascript
// Performed by auth.js on page load
if (!localStorage.getItem('token')) {
    window.location.href = '/views/login.html';
}
```

---

## 📊 Summary Routing Map

```mermaid
graph TB
    START([User Enters Site]) --> LOGIN[/views/login.html]
    SIGNUP[/views/signup.html] --> AUTH{Auth Success?}
    LOGIN --> AUTH
    AUTH -->|Yes| DASHBOARD[/views/subjects.html]
    AUTH -->|No| ERROR[Error Message]
    
    DASHBOARD --> SIDEBAR{Sidebar Action}
    
    SIDEBAR -->|New Chat| RESET[Reset Chat Feed]
    SIDEBAR -->|Upload| UPLOAD[File Upload Flow]
    SIDEBAR -->|Quiz| QUIZ[Quiz Modal]
    SIDEBAR -->|Clear| CLEAR[Clear Documents]
    
    DASHBOARD --> CHAT[Chat with AI]
    CHAT --> API[Backend API]
    API --> RESPONSE[Formatted Response]
    
    DASHBOARD --> LOGOUT[Logout Button]
    LOGOUT --> LOGIN
```

---

## 🎯 Key Takeaways

1. **No SPA Framework** - Simple multi-page application with direct HTML navigation
2. **JWT Authentication** - Token stored in localStorage, checked on page load
3. **Sidebar as Action Hub** - All key features accessible from sidebar
4. **Single Main Dashboard** - All learning activities happen in `subjects.html`
5. **API-Driven** - Frontend is thin client, backend handles all business logic
6. **Real-Time Interaction** - Chat updates dynamically via async/await fetch calls

---

This architecture keeps the frontend simple and maintainable while leveraging powerful backend RAG capabilities! 🚀
