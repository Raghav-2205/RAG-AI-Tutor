/**
 * Chat Bubble Component
 * Self-contained with inline message handling and scrolling
 */
class ChatBubble {
  constructor() {
    this.isOpen = false;
    this.init();
  }

  init() {
    // Inject HTML once
    document.body.insertAdjacentHTML(
      "beforeend",
      `
      <div class="chat-bubble">
        <button class="chat-toggle" id="chatToggle">💬</button>
      </div>

      <div class="chat-window" id="chatWindow">
        <div class="chat-header">
          <span>RAG AI Tutor</span>
          <button id="chatClose">✕</button>
        </div>

        <div class="chat-messages" id="chatMessages"></div>

        <div class="chat-input-container">
          <input
            class="chat-input"
            id="chatInput"
            placeholder="Ask about your uploaded documents..."
          />
          <button class="chat-send" id="chatSend">➤</button>
        </div>
      </div>
      `
    );

    this.bindEvents();
  }

  bindEvents() {
    document
      .getElementById("chatToggle")
      .addEventListener("click", () => this.toggle());

    document
      .getElementById("chatClose")
      .addEventListener("click", () => this.toggle());

    document
      .getElementById("chatSend")
      .addEventListener("click", () => this.send());

    document
      .getElementById("chatInput")
      .addEventListener("keydown", (e) => {
        if (e.key === "Enter") this.send();
      });
  }

  toggle() {
    const windowEl = document.getElementById("chatWindow");
    this.isOpen = !this.isOpen;

    windowEl.style.display = this.isOpen ? "flex" : "none";

    if (this.isOpen) {
      document.getElementById("chatInput").focus();
      this.scrollToBottom();
    }
  }

  // INLINE addMessage - no dependency on chatUtils
  addMessage(text, sender) {
    const messagesContainer = document.getElementById("chatMessages");
    if (!messagesContainer) {
      console.error("chatMessages container not found!");
      return;
    }

    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${sender}`;
    msgDiv.textContent = text;

    messagesContainer.appendChild(msgDiv);
    this.scrollToBottom();
  }

  // INLINE scrollToBottom
  scrollToBottom() {
    const messagesContainer = document.getElementById("chatMessages");
    if (messagesContainer) {
      // Use setTimeout to ensure DOM has updated
      setTimeout(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      }, 50);
    }
  }

  async send() {
    const input = document.getElementById("chatInput");
    const text = input.value.trim();
    if (!text) return;

    if (!window.ai) {
      alert("AI system not ready. Please wait or refresh the page.");
      return;
    }

    // User message
    this.addMessage(text, "user");
    input.value = "";

    // Show loading
    this.addMessage("Thinking...", "ai");

    try {
      const res = await window.ai.sendMessage(text);

      // Remove "Thinking..." message
      const messages = document.getElementById("chatMessages");
      const lastMsg = messages.lastElementChild;
      if (lastMsg && lastMsg.textContent === "Thinking...") {
        messages.removeChild(lastMsg);
      }

      // Add actual response - use 'answer' key from ai.js
      this.addMessage(res.answer || "No response received", "ai");
    } catch (err) {
      // Remove "Thinking..." message
      const messages = document.getElementById("chatMessages");
      const lastMsg = messages.lastElementChild;
      if (lastMsg && lastMsg.textContent === "Thinking...") {
        messages.removeChild(lastMsg);
      }

      this.addMessage("❌ Error: " + (err.message || "Failed to contact AI"), "ai");
    }
  }
}

// Initialize
window.chatBubble = new ChatBubble();

// Also expose chatUtils for compatibility
window.chatUtils = {
  addMessage: function (text, sender) {
    if (window.chatBubble) {
      window.chatBubble.addMessage(text, sender);
    }
  },
  scrollToBottom: function () {
    if (window.chatBubble) {
      window.chatBubble.scrollToBottom();
    }
  }
};
