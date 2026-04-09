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
        return window.config?.apiBase || (window.location.origin + '/api');
    }

    /* ================= CORE CHAT ================= */

    async sendMessage(message, subject = this.currentSubject, chatId = null, documentId = null, classId = null) {
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
            // Add document_id if provided (for scoped chats)
            if (documentId) {
                payload.document_id = documentId;
            }
            // Add class_id to link interaction to an LMS course
            if (classId) {
                payload.class_id = classId;
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
                sessionId: data.session_id || data.chat_id,  // Backward compatibility
                validation: data.validation || null,
                source_mode: data.source_mode || null  // NEW: Track answer source
            };

        } catch (error) {
            console.error("❌ AI Error:", error);
            throw error;
        } finally {
            this.isProcessing = false;
        }
    }

    /**
     * Send a message and receive the AI response as an SSE stream.
     * Callbacks:
     *   onMeta(meta)          — called once with {chat_id, citations, chunks, source_mode}
     *   onToken(text)         — called for each streamed token chunk
     *   onValidation(data)    — called with validation/evaluation metrics once available
     *   onDone(full, meta)    — called when stream finishes, with accumulated full text
     *   onError(err)          — called on failure
     */
    async sendMessageStream(message, subject, chatId, documentId, classId, { onMeta, onToken, onValidation, onDone, onError } = {}) {
        if (this.isProcessing) {
            onError?.(new Error("Please wait, AI is processing..."));
            return;
        }
        if (!window.auth?.token) {
            onError?.(new Error("User not authenticated"));
            return;
        }

        this.isProcessing = true;

        const payload = { message: message.trim(), subject: subject || "general" };
        if (chatId) payload.chat_id = chatId;
        if (documentId) payload.document_id = documentId;
        if (classId) payload.class_id = classId;

        try {
            const response = await fetch(`${this.apiBase}/chat/stream`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${window.auth.token}`
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || `Server error ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let fullText = "";
            let metaData = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // Process complete SSE lines
                const lines = buffer.split("\n");
                buffer = lines.pop(); // Keep incomplete last line

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed.startsWith("data:")) continue;

                    const jsonStr = trimmed.slice(5).trim();
                    if (!jsonStr) continue;

                    try {
                        const event = JSON.parse(jsonStr);

                        if (event.type === "meta") {
                            metaData = event;
                            onMeta?.(event);
                        } else if (event.type === "token") {
                            fullText += event.text;
                            onToken?.(event.text);
                        } else if (event.type === "validation") {
                            onValidation?.(event.data);
                        } else if (event.type === "done") {
                            this.addToHistory("user", message);
                            this.addToHistory("ai", fullText);
                            onDone?.(fullText, metaData);
                        } else if (event.type === "error") {
                            throw new Error(event.message || "Stream error from server");
                        }
                    } catch (parseErr) {
                        console.warn("SSE parse error:", parseErr);
                    }
                }
            }
        } catch (err) {
            console.error("❌ Stream Error:", err);
            onError?.(err);
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
                    const chunkId = chunk.id || chunk.metadata.id; // Ensure we get an ID

                    return `<span class="citation" onclick="event.stopPropagation(); window.ai.viewCitation('${chunkId}')" title="Click to view context">
                        CHUNK ${chunkNum}
                        <span class="citation-tooltip">
                            <strong>Source:</strong> ${this.escapeHtml(source)}<br/>
                            <strong>Page:</strong> ${chunk.metadata.page || 'N/A'}<br/>
                            <strong>Type:</strong> ${this.escapeHtml(chunk.metadata.type || 'N/A')}<br/>
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
            const token = window.auth?.token || localStorage.getItem("token");
            if (!token) {
                throw new Error("Authentication required");
            }

            const response = await fetch(`${this.apiBase}/feedback/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
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

    /**
     * View Citation Detail Modal
     */
    async viewCitation(chunkId) {
        const modal = document.getElementById('chunkModal');
        if (!modal) {
            console.error("Chunk modal not found");
            return;
        }

        const content = document.getElementById('chunkModalContent');
        const title = document.getElementById('chunkModalTitle');

        modal.style.display = 'flex';
        content.innerHTML = '<div class="loading">Loading citation details...</div>';

        try {
            // Need auth token
            const token = window.auth?.token || localStorage.getItem("token");
            if (!token) throw new Error("Authentication required");

            const res = await fetch(`${this.apiBase}/chunks/${chunkId}`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!res.ok) throw new Error("Failed to load chunk details");

            const data = await res.json();

            title.innerText = data.metadata.source || 'Document';

            content.innerHTML = `
                <div class="subjects-chunk-detail-card">
                    <div class="subjects-chunk-detail-row">
                        <span class="subjects-chunk-detail-label">Source:</span>
                        <span>${this.escapeHtml(data.metadata.source || 'Unknown')}</span>
                    </div>
                    <div class="subjects-chunk-detail-row">
                        <span class="subjects-chunk-detail-label">Page:</span>
                        <span>${data.metadata.page !== undefined ? data.metadata.page : 'N/A'}</span>
                    </div>
                    <div class="subjects-chunk-detail-row">
                        <span class="subjects-chunk-detail-label">Type:</span>
                        <span>${this.escapeHtml(data.metadata.type || 'N/A')}</span>
                    </div>
                </div>
                <h4 class="subjects-chunk-heading">Full Content</h4>
                <div class="subjects-chunk-text">${this.escapeHtml(data.text)}</div>
            `;

        } catch (err) {
            content.innerHTML = `<div class="subjects-modal-error">
                <h3>Error Loading Citation</h3>
                <p>${err.message}</p>
            </div>`;
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
