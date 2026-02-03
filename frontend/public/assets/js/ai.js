/**
 * Enhanced AI Manager
 * Handles chat interactions with the RAG AI backend
 */
class AIManager {
  constructor() {
    this.currentSubject = "general";
    this.chatHistory = [];
    this.isProcessing = false;
  }

  get apiBase() {
    return window.config ? window.config.apiBase : "http://127.0.0.1:8000/api";
  }

  async sendMessage(message, options = {}) {
    if (this.isProcessing) {
      throw new Error("Another message is being processed. Please wait.");
    }

    if (!message || message.trim().length === 0) {
      throw new Error("Message cannot be empty");
    }

    if (!window.auth || !window.auth.isAuthenticated) {
      throw new Error("Please log in to continue");
    }

    this.isProcessing = true;

    try {
      const requestBody = {
        message: message.trim(),
        subject: options.subject || this.currentSubject,
        session_id: options.session_id || this.getCurrentSessionId(),
        include_citations: options.include_citations !== false
      };

      const response = await this.makeRequest(`${this.apiBase}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${window.auth.token}`
        },
        body: JSON.stringify(requestBody)
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `Server error: ${response.status}`);
      }

      const data = await response.json();
      
      // Add to chat history
      this.addToHistory({
        type: 'user',
        message: message,
        timestamp: new Date().toISOString()
      });
      
      this.addToHistory({
        type: 'ai',
        message: data.message || data.response,
        citations: data.citations || [],
        timestamp: new Date().toISOString()
      });

      return data;
    } catch (error) {
      console.error('AI Manager error:', error);
      throw error;
    } finally {
      this.isProcessing = false;
    }
  }

  async getChatHistory(sessionId = null) {
    try {
      const url = sessionId 
        ? `${this.apiBase}/chat/history/${sessionId}`
        : `${this.apiBase}/chat/sessions`;

      const response = await this.makeRequest(url, {
        headers: {
          Authorization: `Bearer ${window.auth.token}`
        }
      });

      if (!response.ok) {
        throw new Error('Failed to fetch chat history');
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get chat history:', error);
      return [];
    }
  }

  async createNewSession(subject = null) {
    try {
      const response = await this.makeRequest(`${this.apiBase}/chat/sessions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${window.auth.token}`
        },
        body: JSON.stringify({
          subject: subject || this.currentSubject
        })
      });

      if (!response.ok) {
        throw new Error('Failed to create new session');
      }

      const session = await response.json();
      localStorage.setItem('currentSessionId', session.id);
      this.chatHistory = [];
      
      return session;
    } catch (error) {
      console.error('Failed to create new session:', error);
      throw error;
    }
  }

  setSubject(subject) {
    if (subject && typeof subject === 'string') {
      this.currentSubject = subject.toLowerCase();
      
      // Trigger subject change event
      if (typeof window.onSubjectChange === 'function') {
        window.onSubjectChange(this.currentSubject);
      }
    }
  }

  getCurrentSessionId() {
    return localStorage.getItem('currentSessionId') || this.generateSessionId();
  }

  generateSessionId() {
    const sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem('currentSessionId', sessionId);
    return sessionId;
  }

  addToHistory(entry) {
    this.chatHistory.push(entry);
    
    // Limit history size to prevent memory issues
    if (this.chatHistory.length > 100) {
      this.chatHistory = this.chatHistory.slice(-50);
    }
  }

  clearHistory() {
    this.chatHistory = [];
    localStorage.removeItem('currentSessionId');
  }

  async makeRequest(url, options = {}) {
    if (window.config && window.config.fetch) {
      return await window.config.fetch(url, options);
    } else {
      // Fallback to regular fetch
      return await fetch(url, options);
    }
  }

  // Utility methods
  formatMessage(message) {
    // Basic message formatting
    return message
      .replace(/\n/g, '<br>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>');
  }

  extractCodeBlocks(message) {
    const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
    const codeBlocks = [];
    let match;

    while ((match = codeBlockRegex.exec(message)) !== null) {
      codeBlocks.push({
        language: match[1] || 'text',
        code: match[2].trim()
      });
    }

    return codeBlocks;
  }

  // Voice input support
  async startVoiceInput() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      throw new Error('Speech recognition not supported in this browser');
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    return new Promise((resolve, reject) => {
      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        resolve(transcript);
      };

      recognition.onerror = (event) => {
        reject(new Error(`Speech recognition error: ${event.error}`));
      };

      recognition.start();
    });
  }
}

// Global AI instance
window.ai = new AIManager();

// Enhanced chat interface helpers
window.sendChatMessage = async (message, displayCallback) => {
  try {
    if (typeof displayCallback === 'function') {
      displayCallback({ type: 'user', message, timestamp: new Date() });
      displayCallback({ type: 'loading', message: 'AI is thinking...', timestamp: new Date() });
    }

    const response = await window.ai.sendMessage(message);
    
    if (typeof displayCallback === 'function') {
      displayCallback({ 
        type: 'ai', 
        message: response.message || response.response,
        citations: response.citations,
        timestamp: new Date() 
      });
    }

    return response;
  } catch (error) {
    if (typeof displayCallback === 'function') {
      displayCallback({ 
        type: 'error', 
        message: `Error: ${error.message}`,
        timestamp: new Date() 
      });
    }
    throw error;
  }
};
