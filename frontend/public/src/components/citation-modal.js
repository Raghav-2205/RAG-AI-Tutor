import { qs, clear, el, on } from "../utils/dom.js";

export class CitationModal {
  constructor({ apiBase }) {
    this.apiBase = apiBase;
    this.modal = qs(document, "#citationModal");
    this.title = qs(document, "#citationTitle");
    this.body = qs(document, "#citationBody");
    this.closeBtn = qs(document, "#citationClose");
    this._lastFocus = null;

    on(this.closeBtn, "click", () => this.close());
    on(this.modal, "click", (e) => {
      if (e.target === this.modal) this.close();
    });
    on(document, "keydown", (e) => {
      if (this.modal.getAttribute("aria-hidden") !== "false") return;
      if (e.key === "Escape") this.close();
    });
  }

  openLoading(title = "Citation") {
    this._lastFocus = document.activeElement;
    this.title.textContent = title;
    clear(this.body);
    this.body.appendChild(el("div", { class: "skeleton", style: "height:16px; margin-bottom:12px;" }));
    this.body.appendChild(el("div", { class: "skeleton", style: "height:16px; width:70%; margin-bottom:12px;" }));
    this.body.appendChild(el("div", { class: "skeleton", style: "height:240px;" }));
    this.modal.setAttribute("aria-hidden", "false");
    this.closeBtn.focus();
  }

  close() {
    this.modal.setAttribute("aria-hidden", "true");
    if (this._lastFocus && typeof this._lastFocus.focus === "function") this._lastFocus.focus();
  }

  async openChunk(chunkId) {
    this.openLoading("Citation");
    try {
      const token = window.auth?.token || localStorage.getItem("token");
      if (!token) throw new Error("Authentication required");

      const res = await fetch(`${this.apiBase}/chunks/${encodeURIComponent(chunkId)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error("Failed to load citation");
      const data = await res.json();

      this.title.textContent = data?.metadata?.filename || data?.metadata?.source || "Citation";
      clear(this.body);

      const meta = el("div", {
        class: "codepanel",
        style: "margin-bottom:12px;"
      }, [
        el("div", { class: "codepanel__bar" }, [
          el("div", { text: "Metadata" }),
          el("div", { text: "" })
        ]),
        el("div", { style: "padding:12px; color: rgba(255,255,255,0.82); font-size: 0.9rem;" }, [
          el("div", {}, [el("strong", { text: "Source: " }), el("span", { text: data?.metadata?.source || "Unknown" })]),
          el("div", { style: "margin-top:6px;" }, [el("strong", { text: "Page: " }), el("span", { text: (data?.metadata?.page ?? "N/A") + "" })]),
          el("div", { style: "margin-top:6px;" }, [el("strong", { text: "Type: " }), el("span", { text: data?.metadata?.type || "N/A" })])
        ])
      ]);

      const content = el("div", { class: "codepanel" }, [
        el("div", { class: "codepanel__bar" }, [
          el("div", { text: "Chunk text" }),
          el("div", { text: `ID ${chunkId}` })
        ]),
        el("pre", {}, [el("code", { text: data?.text || "" })])
      ]);

      this.body.appendChild(meta);
      this.body.appendChild(content);
    } catch (e) {
      clear(this.body);
      this.body.appendChild(el("div", { class: "msg msg--ai" }, [
        el("div", { class: "msg__content" }, [
          el("p", { text: `Couldn’t load citation: ${e.message || e}` })
        ])
      ]));
    }
  }
}

