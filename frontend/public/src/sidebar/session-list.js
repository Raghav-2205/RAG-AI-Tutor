import { qs, clear, el, on, debounce } from "../utils/dom.js";
import { sessionListSkeleton } from "../components/loading-skeleton.js";

function relTime(ts) {
  const then = new Date(ts);
  const now = new Date();
  const diff = now - then;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (!Number.isFinite(diff)) return "";
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  return then.toLocaleDateString();
}

function titleFor(session) {
  const doc = session.document_name ? String(session.document_name) : "";
  const title = session.title ? String(session.title) : "Untitled";
  return doc || title;
}

export class SessionList {
  constructor({
    apiBase,
    listEl = "#sessionList",
    searchEl = "#sessionSearch",
    activeChatId = null,
    onSelect,
    onDeleteRequest
  }) {
    this.apiBase = apiBase;
    this.list = qs(document, listEl);
    this.search = qs(document, searchEl);
    this.activeChatId = activeChatId;
    this.onSelect = onSelect;
    this.onDeleteRequest = onDeleteRequest;

    this.sessions = [];
    this.filtered = [];
    this.query = "";

    clear(this.list);
    this.list.appendChild(sessionListSkeleton(6));

    const handle = debounce(() => {
      this.query = (this.search.value || "").trim().toLowerCase();
      this.applyFilter();
      this.render();
    }, 120);

    on(this.search, "input", handle);

    on(this.list, "click", ".session-row", (e, row) => {
      const id = row.dataset.chatId;
      if (!id) return;
      // If click was on a button inside actions, ignore here
      if (e.target.closest("button")) return;
      this.onSelect?.(id);
    });

    on(this.list, "click", 'button[data-action="delete"]', (e, btn) => {
      e.preventDefault();
      e.stopPropagation();
      const id = btn.dataset.chatId;
      if (!id) return;
      const session = this.sessions.find((s) => String(s.chat_id) === String(id));
      this.onDeleteRequest?.(id, session);
    });
  }

  setActive(chatId) {
    this.activeChatId = chatId;
    // fast update: toggle aria-current only
    for (const row of this.list.querySelectorAll(".session-row")) {
      row.setAttribute("aria-current", row.dataset.chatId === String(chatId) ? "true" : "false");
    }
  }

  async load() {
    const token = window.auth?.token || localStorage.getItem("token");
    if (!token) throw new Error("Not authenticated");
    const res = await fetch(`${this.apiBase}/chat/sessions`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (res.status === 401) throw new Error("Session expired");
    if (!res.ok) throw new Error("Failed to load sessions");
    this.sessions = await res.json();
    this.applyFilter();
    this.render();
    return this.sessions;
  }

  applyFilter() {
    if (!this.query) {
      this.filtered = this.sessions.slice();
      return;
    }
    this.filtered = this.sessions.filter((s) => {
      const t = (s.title || "").toLowerCase();
      const d = (s.document_name || "").toLowerCase();
      return t.includes(this.query) || d.includes(this.query);
    });
  }

  render() {
    clear(this.list);

    const data = this.filtered || [];
    if (!data.length) {
      this.list.appendChild(
        el("div", { class: "msg msg--ai", role: "status", "aria-live": "polite" }, [
          el("div", { class: "msg__content" }, [
            el("p", { text: this.query ? "No sessions match your search." : "No chats yet. Start a new one." })
          ])
        ])
      );
      return;
    }

    const frag = document.createDocumentFragment();
    for (const s of data) {
      const chatId = String(s.chat_id);
      const isActive = this.activeChatId && String(this.activeChatId) === chatId;
      const isDocScoped = !!s.document_name;

      const row = el(
        "div",
        {
          class: "session-row",
          role: "listitem",
          tabindex: 0,
          "aria-current": isActive ? "true" : "false",
          dataset: { chatId }
        },
        [
          el("div", { class: "session-meta" }, [
            el("div", { class: "session-title" }, [
              el("span", { text: titleFor(s) }),
              isDocScoped ? el("span", { class: "badge badge--doc", text: "DOC" }) : el("span", { text: "" })
            ]),
            el("div", { class: "session-time", text: relTime(s.updated_at) })
          ]),
          el("div", { class: "row-actions" }, [
            el("button", {
              class: "btn icon-btn",
              type: "button",
              title: "Delete session",
              "aria-label": "Delete session",
              dataset: { action: "delete", chatId },
              text: "🗑"
            })
          ])
        ]
      );

      // keyboard activation
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          this.onSelect?.(chatId);
        }
      });

      frag.appendChild(row);
    }
    this.list.appendChild(frag);
  }
}

