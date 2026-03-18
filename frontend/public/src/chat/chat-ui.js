import { qs, clear, el, on } from "../utils/dom.js";
import { inlineError } from "../components/loading-skeleton.js";
import { ConfirmModal } from "../components/confirm-modal.js";
import { CitationModal } from "../components/citation-modal.js";
import { SessionList } from "../sidebar/session-list.js";
import { MessageRenderer } from "./message-renderer.js";
import { StreamHandler } from "./stream-handler.js";
import { renderValidationStrip } from "../components/validation-card.js";

class ChatApp {
  constructor() {
    this.apiBase = window.config?.apiBase || "http://127.0.0.1:8002/api";
    this.activeChatId = null;
    this.sessionsById = new Map();

    this.shell = qs(document, "#appShell");
    this.sidebar = qs(document, "#sidebar");
    this.sidebarToggle = qs(document, "#sidebarToggle");
    this.logoutBtn = qs(document, "#logoutBtn");

    this.newChatBtn = qs(document, "#newChatBtn");
    this.emptyNewChatBtn = qs(document, "#emptyNewChatBtn");

    this.uploadBtn = qs(document, "#uploadBtn");
    this.emptyUploadBtn = qs(document, "#emptyUploadBtn");
    this.hiddenFileInput = qs(document, "#hiddenFileInput");
    this.clearDocsBtn = qs(document, "#clearDocsBtn");

    this.feed = qs(document, "#chatFeed");
    this.chatScroll = qs(document, "#chatScroll");
    this.emptyState = qs(document, "#emptyState");

    this.composer = qs(document, "#composer");
    this.input = qs(document, "#chatInput");
    this.sendBtn = qs(document, "#sendBtn");

    this.confirmModal = new ConfirmModal();
    this.citationModal = new CitationModal({ apiBase: this.apiBase });
    this.renderer = new MessageRenderer({
      onOpenCitation: (chunkId) => this.citationModal.openChunk(chunkId)
    });

    this.sessionList = new SessionList({
      apiBase: this.apiBase,
      activeChatId: this.activeChatId,
      onSelect: (chatId) => this.switchToChat(chatId),
      onDeleteRequest: (chatId, session) => this.confirmDelete(chatId, session)
    });

    this._bindUi();
  }

  async hydrateLatestValidationOnce(chatId) {
    const token = this.ensureAuthed();
    if (!token || !chatId) return null;

    try {
      const res = await fetch(`${this.apiBase}/chat/sessions/${encodeURIComponent(chatId)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) return null;
      const chat = await res.json();
      const msgs = Array.isArray(chat.messages) ? [...chat.messages].reverse() : [];
      const lastAssistantWithValidation = msgs.find((m) => m.role !== "user" && m.validation_result);
      return lastAssistantWithValidation?.validation_result || null;
    } catch {
      return null;
    }
  }

  _bindUi() {
    on(this.logoutBtn, "click", () => {
      window.auth?.logout?.();
      // fallback
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      window.location.href = "/views/login.html";
    });

    on(this.sidebarToggle, "click", () => this.toggleSidebar());

    on(this.newChatBtn, "click", () => this.newChat());
    on(this.emptyNewChatBtn, "click", () => this.newChat());

    on(this.uploadBtn, "click", () => this.hiddenFileInput.click());
    on(this.emptyUploadBtn, "click", () => this.hiddenFileInput.click());
    on(this.hiddenFileInput, "change", (e) => this.handleFileSelect(e));

    on(this.clearDocsBtn, "click", () => this.clearAllDocuments());

    on(this.composer, "submit", (e) => {
      e.preventDefault();
      this.sendMessage();
    });

    // Enter to send, Shift+Enter for newline
    on(this.input, "keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });
  }

  toggleSidebar(force) {
    const open = typeof force === "boolean" ? force : this.shell.dataset.sidebarOpen !== "true";
    this.shell.dataset.sidebarOpen = open ? "true" : "false";
    this.sidebarToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  ensureAuthed() {
    const token = window.auth?.token || localStorage.getItem("token");
    if (!token) {
      window.location.href = "/views/login.html";
      return null;
    }
    return token;
  }

  async init() {
    const token = this.ensureAuthed();
    if (!token) return;

    const params = new URLSearchParams(window.location.search);
    const deepLinkedChatId = params.get("chat_id");

    try {
      const sessions = await this.sessionList.load();
      this.sessionsById.clear();
      for (const s of sessions) this.sessionsById.set(String(s.chat_id), s);

      if (deepLinkedChatId && this.sessionsById.has(String(deepLinkedChatId))) {
        await this.switchToChat(String(deepLinkedChatId));
      } else if (sessions.length) {
        await this.switchToChat(String(sessions[0].chat_id));
      } else {
        this.newChat();
      }
    } catch (e) {
      clear(this.feed);
      this.feed.appendChild(
        inlineError(`Couldn’t load sessions: ${e.message || e}`, {
          actionLabel: "Retry",
          onAction: () => window.location.reload()
        })
      );
    }
  }

  newChat() {
    this.activeChatId = null;
    this.sessionList.setActive(null);
    clear(this.feed);
    this.feed.appendChild(this.emptyState);
    this.emptyState.style.display = "";
    this.input.focus();
    // collapse sidebar on mobile after selecting
    this.toggleSidebar(false);
  }

  async refreshSessionsKeepActive() {
    const sessions = await this.sessionList.load();
    this.sessionsById.clear();
    for (const s of sessions) this.sessionsById.set(String(s.chat_id), s);
    this.sessionList.setActive(this.activeChatId);
  }

  async switchToChat(chatId) {
    const token = this.ensureAuthed();
    if (!token) return;

    this.activeChatId = String(chatId);
    this.sessionList.setActive(this.activeChatId);
    this.toggleSidebar(false);

    clear(this.feed);
    this.emptyState.style.display = "none";

    // light skeleton while loading messages
    this.feed.appendChild(el("div", { class: "skeleton", style: "height: 88px; margin-bottom: 12px;" }));
    this.feed.appendChild(el("div", { class: "skeleton", style: "height: 112px; margin-bottom: 12px;" }));

    try {
      const res = await fetch(`${this.apiBase}/chat/sessions/${encodeURIComponent(chatId)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) {
        window.auth?.logout?.();
        return;
      }
      if (!res.ok) throw new Error("Failed to load chat");
      const chat = await res.json();

      clear(this.feed);
      const frag = document.createDocumentFragment();
      const msgs = Array.isArray(chat.messages) ? chat.messages : [];
      for (const m of msgs) {
        if (m.role === "user") {
          frag.appendChild(this.renderer.renderUser(m.content, { timestamp: m.timestamp }));
        } else {
          frag.appendChild(
            this.renderer.renderAiMarkdown(m.content, {
              chunks: m.chunks || [],
              validation: m.validation_result || null,
              timestamp: m.timestamp
            })
          );
        }
      }
      this.feed.appendChild(frag);
      this.scrollToBottom();
    } catch (e) {
      clear(this.feed);
      this.feed.appendChild(
        inlineError(`Couldn’t load this session: ${e.message || e}`, {
          actionLabel: "Retry",
          onAction: () => this.switchToChat(chatId)
        })
      );
    }
  }

  scrollToBottom() {
    this.chatScroll.scrollTop = this.chatScroll.scrollHeight;
  }

  setComposerDisabled(disabled) {
    this.sendBtn.disabled = !!disabled;
    this.input.disabled = !!disabled;
  }

  async sendMessage() {
    const token = this.ensureAuthed();
    if (!token) return;

    const text = (this.input.value || "").trim();
    if (!text) return;
    if (window.ai?.isProcessing) return;

    // remove empty state if present
    this.emptyState.style.display = "none";

    const userMsg = this.renderer.renderUser(text);
    const { msg: aiMsg, contentEl } = this.renderer.createStreamingAiBubble();

    this.feed.appendChild(userMsg);
    this.feed.appendChild(aiMsg);
    this.scrollToBottom();

    this.input.value = "";
    this.setComposerDisabled(true);

    const session = this.activeChatId ? this.sessionsById.get(String(this.activeChatId)) : null;
    const documentId = session?.document_id || null;

    const stream = new StreamHandler({
      onTokenFlush: (fullText) => {
        this.renderer.setStreamingText(contentEl, fullText);
        this.scrollToBottom();
      }
    });

    let metaInfo = null;
    let latestValidation = null;

    await window.ai.sendMessageStream(text, "general", this.activeChatId, documentId, {
      onMeta: (meta) => {
        metaInfo = meta;
      },
      onToken: (tok) => {
        stream.push(tok);
      },
      onValidation: (v) => {
        latestValidation = v;
        // validation can arrive before completion; append strip without re-rendering content
        const existing = aiMsg.querySelector(".vstrip");
        if (!existing) {
          const strip = renderValidationStrip(latestValidation);
          if (strip) aiMsg.appendChild(strip);
          this.scrollToBottom();
        }
      },
      onDone: async (fullText, meta) => {
        const finalText = fullText || stream.finalize();
        const chunks = (meta || metaInfo)?.chunks || [];
        const chatId = String((meta || metaInfo)?.chat_id || this.activeChatId || "");

        this.renderer.finalizeStreamingBubble(aiMsg, finalText, {
          chunks,
          validation: latestValidation
        });

        if (chatId) {
          this.activeChatId = chatId;
          await this.refreshSessionsKeepActive();
        }

        // If backend didn't stream validation, hydrate it once from persisted session.
        if (!latestValidation && chatId && !aiMsg.querySelector(".vstrip")) {
          const hydrated = await this.hydrateLatestValidationOnce(chatId);
          if (hydrated) {
            const strip = renderValidationStrip(hydrated);
            if (strip) aiMsg.appendChild(strip);
          }
        }

        this.scrollToBottom();
      },
      onError: (err) => {
        const msg = err?.message || "Failed to contact AI";
        this.renderer.finalizeStreamingBubble(aiMsg, `❌ ${msg}`, { chunks: [], validation: null });
        this.scrollToBottom();
      }
    });

    this.setComposerDisabled(false);
    this.input.focus();
  }

  async confirmDelete(chatId, session) {
    const ok = await this.confirmModal.open({
      title: "Delete this session?",
      message: `This will permanently delete “${session?.title || session?.document_name || "this chat"}”.`,
      okText: "Delete",
      cancelText: "Cancel"
    });
    if (!ok) return;
    await this.deleteChat(chatId);
  }

  async deleteChat(chatId) {
    const token = this.ensureAuthed();
    if (!token) return;

    try {
      const res = await fetch(`${this.apiBase}/chat/sessions/${encodeURIComponent(chatId)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) {
        window.auth?.logout?.();
        return;
      }
      if (!res.ok) throw new Error("Delete failed");

      // if we deleted the active chat, reset UI
      if (String(this.activeChatId) === String(chatId)) {
        this.activeChatId = null;
      }
      await this.refreshSessionsKeepActive();

      if (!this.activeChatId) {
        const first = this.sessionList.sessions?.[0]?.chat_id;
        if (first) await this.switchToChat(String(first));
        else this.newChat();
      } else {
        this.sessionList.setActive(this.activeChatId);
      }
    } catch (e) {
      this.feed.appendChild(inlineError(`Couldn’t delete session: ${e.message || e}`));
      this.scrollToBottom();
    }
  }

  async handleFileSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const token = this.ensureAuthed();
    if (!token) return;

    this.emptyState.style.display = "none";
    this.feed.appendChild(this.renderer.renderSystem(`Uploading ${file.name}…`));
    this.scrollToBottom();

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("subject", "general");

      const res = await fetch(`${this.apiBase}/upload/`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData
      });
      if (res.status === 401) {
        window.auth?.logout?.();
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Upload failed");
      }
      const data = await res.json();
      const chunkCount = data.chunks || data.chunks_stored || 0;

      if (chunkCount > 0) {
        this.feed.appendChild(this.renderer.renderSystem(`Uploaded “${file.name}”. Indexed ${chunkCount} chunks.`));
      } else {
        this.feed.appendChild(
          this.renderer.renderSystem(
            `Uploaded “${file.name}”, but no text was extracted. If this is a scanned PDF, try an image upload.`
          )
        );
      }

      if (data.chat_id) {
        await this.refreshSessionsKeepActive();
        await this.switchToChat(String(data.chat_id));
        this.feed.appendChild(
          this.renderer.renderSystem(
            `Document indexed. This chat is now scoped to “${file.name}”. I’ll answer using only this document.`
          )
        );
        this.scrollToBottom();
      }
    } catch (err) {
      this.feed.appendChild(inlineError(`Upload failed: ${err.message || err}`));
      this.scrollToBottom();
    } finally {
      e.target.value = "";
    }
  }

  async clearAllDocuments() {
    const token = this.ensureAuthed();
    if (!token) return;

    const ok = await this.confirmModal.open({
      title: "Clear all documents?",
      message: "This deletes ALL uploaded documents. This cannot be undone.",
      okText: "Clear",
      cancelText: "Cancel"
    });
    if (!ok) return;

    this.feed.appendChild(this.renderer.renderSystem("Deleting all documents…"));
    this.scrollToBottom();

    try {
      const res = await fetch(`${this.apiBase}/upload/all`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) {
        window.auth?.logout?.();
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Delete failed");
      }
      const data = await res.json().catch(() => ({}));
      this.feed.appendChild(this.renderer.renderSystem(data.message || "Documents cleared. You can upload new ones."));
      this.scrollToBottom();
    } catch (e) {
      this.feed.appendChild(inlineError(`Clear failed: ${e.message || e}`));
      this.scrollToBottom();
    }
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const app = new ChatApp();
  app.init();
});

