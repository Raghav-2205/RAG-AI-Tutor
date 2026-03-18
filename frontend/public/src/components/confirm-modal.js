import { qs, el, on } from "../utils/dom.js";

export class ConfirmModal {
  constructor({
    modalId = "confirmModal",
    titleId = "confirmTitle",
    messageId = "confirmMessage",
    okId = "confirmOk",
    cancelId = "confirmCancel",
    closeId = "confirmClose"
  } = {}) {
    this.modal = qs(document, `#${modalId}`);
    this.title = qs(document, `#${titleId}`);
    this.message = qs(document, `#${messageId}`);
    this.ok = qs(document, `#${okId}`);
    this.cancel = qs(document, `#${cancelId}`);
    this.close = qs(document, `#${closeId}`);

    this._resolve = null;
    this._lastFocus = null;

    on(this.ok, "click", () => this._finish(true));
    on(this.cancel, "click", () => this._finish(false));
    on(this.close, "click", () => this._finish(false));
    on(this.modal, "click", (e) => {
      if (e.target === this.modal) this._finish(false);
    });
    on(document, "keydown", (e) => {
      if (this.modal.getAttribute("aria-hidden") !== "false") return;
      if (e.key === "Escape") this._finish(false);
    });
  }

  async open({ title = "Confirm", message = "Are you sure?", okText = "OK", cancelText = "Cancel" } = {}) {
    this._lastFocus = document.activeElement;
    this.title.textContent = title;
    this.message.textContent = message;
    this.ok.textContent = okText;
    this.cancel.textContent = cancelText;

    this.modal.setAttribute("aria-hidden", "false");
    // basic focus target
    this.ok.focus();

    return await new Promise((resolve) => {
      this._resolve = resolve;
    });
  }

  _finish(result) {
    if (this._resolve) this._resolve(result);
    this._resolve = null;
    this.modal.setAttribute("aria-hidden", "true");
    if (this._lastFocus && typeof this._lastFocus.focus === "function") this._lastFocus.focus();
  }
}

