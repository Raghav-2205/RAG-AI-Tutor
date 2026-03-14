/**
 * Chat Utility functions
 * Handles message rendering and scrolling
 */

window.chatUtils = {
    addMessage: function (text, sender) {
        const messagesContainer = document.getElementById("chatMessages");
        if (!messagesContainer) return;

        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${sender}`;

        // For AI, we might want to check if it's markdown or has citations?
        // For now, let's just treat as text. formatting can be added later.
        // To support newlines, we can use simple replacement or CSS white-space.
        // CSS .message should have white-space: pre-wrap;

        // Check for citations (Simple [1], [2] parsing if needed, but textContent is safer)
        msgDiv.textContent = text;

        messagesContainer.appendChild(msgDiv);
        this.scrollToBottom();
    },

    scrollToBottom: function () {
        const messagesContainer = document.getElementById("chatMessages");
        if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    },

    clearMessages: function () {
        const messagesContainer = document.getElementById("chatMessages");
        if (messagesContainer) {
            messagesContainer.innerHTML = '';
        }
    }
};
