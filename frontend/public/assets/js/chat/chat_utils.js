class ChatUtils {
  addMessage(text, sender) {
    const box = document.querySelector(".chat-messages");
    const msg = document.createElement("div");
    msg.className = `message ${sender}`;
    msg.textContent = text;
    box.appendChild(msg);
    box.scrollTop = box.scrollHeight;
  }
}

window.chatUtils = new ChatUtils();
