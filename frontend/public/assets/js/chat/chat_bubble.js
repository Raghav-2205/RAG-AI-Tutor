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
    }
  }

  async send() {
    const input = document.getElementById("chatInput");
    const text = input.value.trim();
    if (!text) return;

    if (!window.ai || !window.chatUtils) {
      alert("Chat system not ready");
      return;
    }

    // User message
    chatUtils.addMessage(text, "user");
    input.value = "";

    try {
      const res = await ai.sendMessage(text);
      chatUtils.addMessage(res.response || "No response", "ai");
    } catch (err) {
      chatUtils.addMessage("❌ Error contacting AI backend", "ai");
    }
  }
}

window.chatBubble = new ChatBubble();
