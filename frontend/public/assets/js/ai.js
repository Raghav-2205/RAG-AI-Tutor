/**
 * Unified & Corrected AI Manager
 * Handles chat interactions with the RAG FastAPI backend
 */

class AIManager {
    constructor() {
        this.currentSubject = "general";
        this.chatHistory = [];
        this.isProcessing = false;
    }

    get apiBase() {
        return window.config?.apiBase || "http://127.0.0.1:8000/api";
    }

    /* ================= CORE CHAT ================= */

    async sendMessage(message, subject = this.currentSubject, chatId = null) {
        if (this.isProcessing) {
            throw new Error("Please wait, AI is processing...");
        }

        if (!message || !message.trim()) {
            throw new Error("Message cannot be empty");
        }

        if (!window.auth || !window.auth.token) {
            throw new Error("User not authenticated");
        }

        this.isProcessing = true;

        try {
            const payload = {
                message: message.trim(),
                subject: subject
            };

            // Add chat_id if provided (for existing chats)
            if (chatId) {
                payload.chat_id = chatId;
            }

            console.log("📤 Sending to backend:", payload);

            const response = await fetch(`${this.apiBase}/chat/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${window.auth.token}`
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Server error");
            }

            const data = await response.json();
            console.log("📥 Received:", data);

            this.addToHistory("user", message);
            this.addToHistory("ai", data.answer);

            return {
                answer: data.answer,
                citations: data.citations || [],
                chunks: data.chunks || [],
                chat_id: data.chat_id,  // Return chat_id from backend
                sessionId: data.session_id || data.chat_id  // Backward compatibility
            };

        } catch (error) {
            console.error("❌ AI Error:", error);
            throw error;
        } finally {
            this.isProcessing = false;
        }
    }

    /* ================= SESSION ================= */

    getCurrentSessionId() {
        let id = localStorage.getItem("currentSessionId");
        if (!id) {
            id = this.generateSessionId();
        }
        return id;
    }

    generateSessionId() {
        const id = `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;
        localStorage.setItem("currentSessionId", id);
        return id;
    }

    clearSession() {
        this.chatHistory = [];
        localStorage.removeItem("currentSessionId");
    }

    /* ================= HISTORY ================= */

    addToHistory(role, content) {
        this.chatHistory.push({
            role,
            content,
            timestamp: new Date().toISOString()
        });

        if (this.chatHistory.length > 100) {
            this.chatHistory = this.chatHistory.slice(-50);
        }
    }

    /* ================= UTILITIES ================= */

    formatMessage(text, chunks = []) {
        // Use marked.js for markdown parsing if available
        if (typeof marked !== 'undefined') {
            // Configure marked for safe HTML
            marked.setOptions({
                breaks: true,
                gfm: true,
                headerIds: false,
                mangle: false
            });

            // Parse markdown
            let html = marked.parse(text);

            // Convert citation patterns like (CHUNK 1), (CHUNK 2) to interactive elements
            // Match patterns: (CHUNK N) or [CHUNK N]
            html = html.replace(/\(CHUNK (\d+)\)|\[CHUNK (\d+)\]/gi, (match, num1, num2) => {
                const chunkNum = parseInt(num1 || num2);
                const chunk = chunks[chunkNum - 1]; // chunks array is 0-indexed

                if (chunk && chunk.metadata) {
                    const source = chunk.metadata.source || 'Unknown source';
                    const preview = chunk.text ? chunk.text.substring(0, 100) + '...' : '';

                    return `<span class="citation" data-chunk="${chunkNum}">
                        CHUNK ${chunkNum}
                        <span class="citation-tooltip">
                            <strong>Source:</strong> ${this.escapeHtml(source)}<br/>
                            <em>${this.escapeHtml(preview)}</em>
                        </span>
                    </span>`;
                } else {
                    // Fallback if chunk data not available
                    return `<span class="citation">CHUNK ${chunkNum}</span>`;
                }
            });

            return html;
        }

        // Fallback if marked.js not available
        return text
            .replace(/\n/g, "<br>")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\*(.*?)\*/g, "<em>$1</em>");
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    extractCodeBlocks(text) {
        const regex = /```(\w+)?\n([\s\S]*?)```/g;
        const blocks = [];
        let match;

        while ((match = regex.exec(text)) !== null) {
            blocks.push({
                language: match[1] || "text",
                code: match[2].trim()
            });
        }
        return blocks;
    }

    /* ================= VOICE INPUT ================= */

    async startVoiceInput() {
        const SpeechRecognition =
            window.SpeechRecognition || window.webkitSpeechRecognition;

        if (!SpeechRecognition) {
            throw new Error("Speech recognition not supported");
        }

        const recognition = new SpeechRecognition();
        recognition.lang = "en-US";
        recognition.interimResults = false;

        return new Promise((resolve, reject) => {
            recognition.onresult = e =>
                resolve(e.results[0][0].transcript);

            recognition.onerror = e =>
                reject(new Error(e.error));

            recognition.start();
        });
    }

    /* ================= FEEDBACK ================= */

    /**
     * Submit feedback for a chat response or quiz
     */
    async submitFeedback(source, referenceId, rating, subject = 'general', comment = '') {
        try {
            const response = await fetch(`${this.config.apiBase}/feedback/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.getToken()}`
                },
                body: JSON.stringify({
                    source,
                    reference_id: referenceId,
                    rating,
                    subject,
                    comment
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to submit feedback');
            }

            return await response.json();
        } catch (error) {
            console.error('❌ Feedback error:', error);
            throw error;
        }
    }

    /**
     * Create feedback UI HTML for chat messages
     */
    createChatFeedbackUI(sessionId, subject = 'general') {
        const feedbackId = `feedback-${sessionId}`;
        return `
            <div class="feedback-container" id="${feedbackId}">
                <span class="feedback-label">Was this helpful?</span>
                <div class="feedback-buttons">
                    <button class="feedback-btn" data-rating="positive" onclick="window.ai.handleChatFeedback('${sessionId}', 'positive', '${subject}')">
                        👍
                    </button>
                    <button class="feedback-btn" data-rating="negative" onclick="window.ai.handleChatFeedback('${sessionId}', 'negative', '${subject}')">
                        👎
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Handle chat feedback button click
     */
    async handleChatFeedback(sessionId, rating, subject) {
        const feedbackContainer = document.getElementById(`feedback-${sessionId}`);
        if (!feedbackContainer) return;

        const buttons = feedbackContainer.querySelectorAll('.feedback-btn');
        buttons.forEach(btn => btn.classList.remove('selected'));

        const clickedButton = feedbackContainer.querySelector(`[data-rating="${rating}"]`);
        if (clickedButton) clickedButton.classList.add('selected');

        // Check if comment area already exists
        if (feedbackContainer.querySelector('.feedback-comment')) return;

        // Add comment textarea and submit button
        const commentHTML = `
            <div style="width: 100%; display: flex; flex-direction: column;">
                <textarea class="feedback-comment" placeholder="Optional: Tell us more..." rows="2"></textarea>
                <button class="feedback-submit" onclick="window.ai.submitChatFeedback('${sessionId}', '${rating}', '${subject}')">
                    Submit Feedback
                </button>
            </div>
        `;
        feedbackContainer.insertAdjacentHTML('beforeend', commentHTML);
    }

    /**
     * Submit chat feedback with comment
     */
    async submitChatFeedback(sessionId, rating, subject) {
        const feedbackContainer = document.getElementById(`feedback-${sessionId}`);
        if (!feedbackContainer) return;

        const commentArea = feedbackContainer.querySelector('.feedback-comment');
        const comment = commentArea ? commentArea.value.trim() : '';

        try {
            await this.submitFeedback('chat', sessionId, rating, subject, comment);
            feedbackContainer.innerHTML = '<span class="feedback-thanks">✓ Thank you for your feedback!</span>';
        } catch (error) {
            alert(`Failed to submit feedback: ${error.message}`);
        }
    }
}

/* ================= GLOBAL INSTANCE ================= */

window.ai = new AIManager();

/* ================= UI HELPER ================= */

window.sendChatMessage = async (message, callback) => {
    try {
        callback?.({ type: "user", message });
        callback?.({ type: "loading", message: "Thinking..." });

        const res = await window.ai.sendMessage(message);

        callback?.({
            type: "ai",
            message: res.answer,
            citations: res.citations,
            chunks: res.chunks  // Pass chunks for citation tooltips
        });

        return res;
    } catch (err) {
        callback?.({
            type: "error",
            message: err.message
        });
        throw err;
    }
};
