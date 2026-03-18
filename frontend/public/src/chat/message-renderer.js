import { el, clear, on } from "../utils/dom.js";
import { sanitizeToFragment } from "../utils/sanitizer.js";
import { renderValidationStrip } from "../components/validation-card.js";

function fmtTime(ts = Date.now()) {
  const d = ts instanceof Date ? ts : new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function chunkIdFor(chunk) {
  return chunk?.id || chunk?.metadata?.id || chunk?._id || null;
}

function enhanceCodePanels(container) {
  const pres = Array.from(container.querySelectorAll("pre"));
  for (const pre of pres) {
    const code = pre.querySelector("code");
    const lang = (code?.className || "").match(/language-([a-z0-9-]+)/i)?.[1] || "code";
    const codePanel = el("div", { class: "codepanel" }, [
      el("div", { class: "codepanel__bar" }, [
        el("div", { text: lang.toUpperCase() }),
        el("button", {
          class: "btn",
          type: "button",
          text: "Copy",
          dataset: { action: "copy-code" },
          "aria-label": "Copy code"
        })
      ])
    ]);
    const body = el("div", {});
    body.appendChild(pre.cloneNode(true));
    codePanel.appendChild(body);
    pre.replaceWith(codePanel);
  }
}

export class MessageRenderer {
  constructor({ onOpenCitation }) {
    this.onOpenCitation = onOpenCitation;
  }

  renderUser(text, { timestamp } = {}) {
    return this._base("You", "msg msg--user", [
      el("div", { class: "msg__content", text: String(text || "") })
    ], { timestamp });
  }

  renderSystem(text, { timestamp } = {}) {
    return this._base("System", "msg msg--ai", [
      el("div", { class: "msg__content" }, [el("p", { text: String(text || "") })])
    ], { timestamp });
  }

  renderAiMarkdown(markdownText, { chunks = [], validation = null, timestamp } = {}) {
    const content = el("div", { class: "msg__content" });
    const html = this._markdownToHtml(markdownText, chunks);
    content.appendChild(sanitizeToFragment(html));
    enhanceCodePanels(content);

    const msg = this._base("Tutor", "msg msg--ai", [content], { timestamp });

    const chips = this._citationChips(chunks);
    if (chips) msg.appendChild(chips);

    const v = renderValidationStrip(validation);
    if (v) msg.appendChild(v);

    // event delegation for code copy + chips
    on(msg, "click", 'button[data-action="copy-code"]', async (e, btn) => {
      const panel = btn.closest(".codepanel");
      const code = panel?.querySelector("pre code")?.textContent || "";
      try {
        await navigator.clipboard.writeText(code);
        const prev = btn.textContent;
        btn.textContent = "Copied";
        window.setTimeout(() => (btn.textContent = prev), 900);
      } catch {
        btn.textContent = "Copy failed";
        window.setTimeout(() => (btn.textContent = "Copy"), 900);
      }
    });

    on(msg, "click", ".c-chip", (e, chip) => {
      const id = chip.dataset.chunkId;
      if (!id) return;
      this.onOpenCitation?.(id);
    });

    return msg;
  }

  createStreamingAiBubble({ timestamp } = {}) {
    const content = el("div", { class: "msg__content" }, [
      el("span", { class: "typing", "aria-label": "Assistant typing" }, [
        el("span", { class: "dot" }),
        el("span", { class: "dot" }),
        el("span", { class: "dot" })
      ])
    ]);
    const msg = this._base("Tutor", "msg msg--ai", [content], { timestamp });
    return { msg, contentEl: content };
  }

  setStreamingText(contentEl, text) {
    // while streaming, keep as plain text (fast + safe)
    clear(contentEl);
    contentEl.appendChild(document.createTextNode(String(text || "")));
  }

  finalizeStreamingBubble(msgEl, markdownText, { chunks = [], validation = null } = {}) {
    // replace content with markdown view
    const content = msgEl.querySelector(".msg__content");
    if (!content) return;
    clear(content);
    const html = this._markdownToHtml(markdownText, chunks);
    content.appendChild(sanitizeToFragment(html));
    enhanceCodePanels(content);

    const chips = this._citationChips(chunks);
    if (chips) msgEl.appendChild(chips);

    // Avoid duplicating the strip if validation arrived early
    if (!msgEl.querySelector(".vstrip")) {
      const v = renderValidationStrip(validation);
      if (v) msgEl.appendChild(v);
    }
  }

  _markdownToHtml(text, chunks) {
    // Marked already loaded globally via subjects.html
    if (typeof marked !== "undefined") {
      marked.setOptions({ breaks: true, gfm: true, headerIds: false, mangle: false });
    }
    const raw = typeof marked !== "undefined" ? marked.parse(String(text || "")) : String(text || "");
    // Replace (CHUNK n) with safe buttons after markdown parse: do it in HTML string
    const html = raw.replace(/\(CHUNK (\d+)\)|\[CHUNK (\d+)\]/gi, (match, n1, n2) => {
      const idx = (parseInt(n1 || n2, 10) || 0) - 1;
      const chunk = Array.isArray(chunks) ? chunks[idx] : null;
      const id = chunkIdFor(chunk);
      const label = `CHUNK ${idx + 1}`;
      if (!id) return `<span>${label}</span>`;
      return `<button type="button" class="c-chip" data-chunk-id="${String(id).replace(/"/g, "&quot;")}" aria-label="Open citation ${label}">${label}</button>`;
    });
    return html;
  }

  _citationChips(chunks) {
    if (!Array.isArray(chunks) || !chunks.length) return null;
    const buttons = [];
    for (let i = 0; i < chunks.length; i++) {
      const c = chunks[i];
      const id = chunkIdFor(c);
      if (!id) continue;
      const source = c?.metadata?.source || c?.metadata?.filename || "Source";
      buttons.push(
        el("button", {
          type: "button",
          class: "c-chip",
          dataset: { chunkId: id },
          title: source,
          "aria-label": `Open citation chunk ${i + 1}`
        }, [`CHUNK ${i + 1}`])
      );
    }
    if (!buttons.length) return null;
    return el("div", { class: "c-chips", "aria-label": "Citations" }, buttons);
  }

  _base(roleLabel, className, bodyChildren, { timestamp } = {}) {
    return el("article", { class: className }, [
      el("div", { class: "msg__meta" }, [
        el("div", { class: "msg__role", text: roleLabel }),
        el("div", { text: fmtTime(timestamp || Date.now()) })
      ]),
      ...bodyChildren
    ]);
  }
}

