# 🖥️ Frontend Developer Guide

The **RAG AI Tutor** frontend is built with **Vanilla JavaScript (ES6+)** and **CSS** to ensure maximum performance and zero build-step complexity. It follows a clean, component-based structure where possible.

---

## 📂 Structure

```
frontend/
├── public/
│   ├── index.html          # Main Entry Point (Router)
│   ├── assets/
│   │   ├── css/            # Stylsheets
│   │   │   ├── main.css    # Global Styles
│   │   │   ├── chat.css    # Chat Interface Styles
│   │   │   ├── components.css # Button, Modal, Card Styles
│   │   │   └── auth.css    # Login/Signup Styles
│   │   └── js/             # Application Logic
│   │   │   ├── config.js   # Global Config (API Base URL)
│   │   │   ├── auth.js     # Authentication Manager
│   │   │   ├── ai.js       # Core AI & Chat Logic
│   │   │   ├── subjects.js # Subject/Topic Management
│   │   │   └── voice/      # Voice Dictation Module
│   └── views/              # Partial HTML Templates
│       ├── home.html       # Landing Page
│       ├── login.html      # Login Form
│       ├── signup.html     # Registration Form
│       ├── subjects.html   # Main Workspace (Chat & Sidebar)
│       └── quiz.html       # Quiz Interface
```

---

## 🧩 Core Pages & Logic

### 1. `index.html` (The Shell)
-   **Role**: Acts as the Single Page Application (SPA) shell.
-   **Logic**:
    -   Loads global CSS and JS.
    -   Implements a simple **Router** (`navigateToPage`, `loadView`) to switch content in `<div id="app">` without reloading.
    -   Manages the global `NavBar` state (Login/Logout buttons).

### 2. `auth.js` (Authentication)
-   **Role**: Manages user sessions.
-   **Key Methods**:
    -   `login(email, password)`: Calls `/api/auth/login`, stores JWT in `localStorage`.
    -   `register(email, password, name)`: Calls `/api/auth/register`.
    -   `logout()`: Clears token and redirects to Home.
    -   `isAuthenticated()`: Checks if a valid token exists.

### 3. `ai.js` (The Brain)
-   **Role**: Handles all Chat and RAG interactions.
-   **Key Features**:
    -   **`sendMessage(text)`**: Sends user query to `/api/chat/`.
    -   **`viewCitation(chunkId)`**: Fetches chunk details from `/api/chunks/{id}` and populates the **Citation Modal**.
    -   **`formatMessage(markdown)`**: Parses Markdown and converts citations (e.g., `[CHUNK 1]`) into clickable HTML elements.
    -   **Feedback**: Submits user ratings for adaptive learning.

### 4. `subjects.html` (The Workspace)
-   **Role**: The main interface for authenticated users.
-   **Features**:
    -   **Sidebar**: Lists chat history, managed by `ChatHistoryManager` (in `subjects.html` script).
    -   **Chat Feed**: Renders messages dynamically using `ai.js`.
    -   **File Upload**: Hidden input triggers `upload.js` logic.
    -   **Probe Modal**: Displays chunk details when a citation is clicked.

---

## 🎨 Styling & UI

-   **Design System**: Glassmorphism with a dark theme (`#0a0e27` background).
-   **Responsive**: Uses CSS Grid and Flexbox for mobile adaptation.
-   **Components**: Reusable classes in `components.css` for Buttons, Cards, and Inputs.

---

## 🔗 Integration Points

### **Frontend → Backend Communication**
-   All API calls use `fetch` with the `Authorization: Bearer <token>` header.
-   **Base URL**: Configured in `assets/js/config.js` (default: `http://127.0.0.1:8000`).

### **State Management**
-   **Session State**: `localStorage` stores the JWT token and current `sessionId`.
-   **View State**: The router manages the current active view.
-   **Chat State**: `ChatHistoryManager` maintains the list of active conversations.
