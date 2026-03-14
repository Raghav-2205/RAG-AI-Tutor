# 🖥️ Frontend Documentation

The frontend of the RAG AI Tutor is built using **Vanilla JavaScript**, **HTML5**, and CSS. It avoids heavy frameworks to keep the architecture simple and easy to understand. The application behaves like a Single-Page Application (SPA) in feel, though it uses distinct HTML files for different views.

## 📂 Structure
All frontend files are located in `frontend/public/views/`.

---

## 1. Login Page (`login.html`)
### **Purpose**
The entry point of the application. Handles user authentication and token management.

### **UI Components**
*   Email & Password input fields.
*   "Login" button.
*   Link to Signup page.
*   Error message display area.

### **JavaScript Logic**
*   **Event Listener**: Listens for the form `submit` event.
*   **API Call**: Sends a `POST` request to `/api/auth/login` with `x-www-form-urlencoded` data.
*   **Token Storage**: On success, receives an `access_token` and stores it in `localStorage.getItem('token')`.
*   **Redirection**: Redirects user to `subjects.html` upon successful login.

---

## 2. Signup Page (`signup.html`)
### **Purpose**
Allows new users to register an account.

### **UI Components**
*   Name, Email, Password, and "Role" (Student/Teacher) inputs.
*   "Register" button.

### **JavaScript Logic**
*   **Validation**: Ensures passwords match (if confirm password field exists) and email format is valid.
*   **API Call**: Sends a `POST` request to `/api/auth/register` with JSON data.
*   **Flow**: On success, alerts the user and redirects them to `login.html`.

---

## 3. Subjects / Dashboard (`subjects.html`)
### **Purpose**
The main landing page after login. It serves as a dashboard where users can select what they want to study or manage their data.

### **UI Components**
*   **Navigation Bar**: Links to Chat, Upload, Quiz, Profile.
*   **Subject Cards**: Visual representation of different study topics (e.g., Biology, History).
*   **Stats Overview**: (Optional) Displays recent progress.

### **JavaScript Logic**
*   **Auth Check**: On load, checks if `localStorage.getItem('token')` exists. If not, redirects to login.
*   **Data Fetching**: Calls `/api/auth/me` to greet the user by name.
*   **Navigation**: Clicking a subject saves the selected subject to `localStorage` or passes it as a query parameter to the Chat page.

---

## 4. Chat Page (`chat.html`)
### **Purpose**
The core interaction interface. Users ask questions and receive RAG-generated answers.

### **UI Components**
*   **Chat Window**: Scrollable area displaying message history.
*   **Input Area**: Text box for typing questions.
*   **Send Button**.
*   **History Sidebar**: A list of previous chat sessions.

### **JavaScript Logic**
*   **State Management**: Maintains `currentChatId` to know if we are starting a new conversation or continuing an old one.
*   **API Calls**:
    *   `POST /api/chat/`: Sends the user's message.
    *   `GET /api/chat/sessions`: Loads the sidebar history.
    *   `GET /api/chat/sessions/{id}`: Loads a specific conversation.
*   **Rendering**:
    *   Dynamically creates HTML elements for User (Right aligned) and AI (Left aligned) messages.
    *   **Citations**: When the API returns search results, the JS renders them as clickable footnotes or expandable "Source" blocks below the answer.

---

## 5. Upload Page (`upload.html`)
### **Purpose**
Users upload their study materials here.

### **UI Components**
*   **File Drop Zone**: Drag-and-drop area or "Choose File" button.
*   **Subject Selector**: Dropdown to categorize the document.
*   **Upload Button**.
*   **Document List**: Table showing previously uploaded files.

### **JavaScript Logic**
*   **File Handling**: Uses `FormData` to package the file input.
*   **API Call**: `POST /api/upload/`.
*   **Progress Feedback**: Shows a spinner or progress bar while the backend chunks and embeds the file.
*   **Document List**: Calls `GET /api/upload/` to refresh the table of uploaded files after a successful upload.

---

## 6. Quiz Page (`quiz.html`)
### **Purpose**
Allows users to test their knowledge.

### **UI Components**
*   **Setup**: "Generate Quiz" button and "Number of Questions" selector.
*   **Quiz Interface**: Question text, 4 options (Radio buttons).
*   **Results View**: Score display (e.g., "8/10") and personalized feedback.

### **JavaScript Logic**
*   **Generation**: Calls `POST /api/quiz/generate` to trigger the LLM to create questions.
*   **State**: Stores the current list of questions locally.
*   **Navigation**: Handles "Next" and "Previous" question buttons.
*   **Submission**:
    *   Collects all selected answers.
    *   Calls `POST /api/quiz/submit`.
    *   Displays the backend's grading and feedback.

---


