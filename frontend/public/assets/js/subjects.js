class SubjectsManager {
  constructor() {
    this.subjects = ["math", "physics", "chemistry", "cs"];
  }

  render() {
    const grid = document.getElementById("subjectsGrid");
    if (!grid) return;

    grid.innerHTML = this.subjects
      .map(
        (s) => `
      <div class="subject-card">
        <div class="subject-icon">📚</div>
        <h3>${s.toUpperCase()}</h3>
        <button class="subject-btn" onclick="subjectsManager.open('${s}')">Start Chat</button>
      </div>`
      )
      .join("");
  }

  open(subject) {
    if (!window.ai) {
      alert("AI system not initialized. Please refresh the page.");
      return;
    }
    
    ai.setSubject(subject);
    
    if (!window.chatBubble || !document.getElementById("chatWindow")) {
      alert("Chat not loaded. Please refresh the page.");
      return;
    }
    
    chatBubble.toggle();
  }
}

// Initialize after DOM loads
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.subjectsManager = new SubjectsManager();
  });
} else {
  window.subjectsManager = new SubjectsManager();
}