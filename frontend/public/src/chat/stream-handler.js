export class StreamHandler {
  constructor({ onTokenFlush }) {
    this.onTokenFlush = onTokenFlush;
    this.buffer = "";
    this.full = "";
    this._raf = null;
  }

  push(token) {
    this.full += token;
    this.buffer += token;
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      const chunk = this.buffer;
      this.buffer = "";
      this.onTokenFlush?.(this.full, chunk);
    });
  }

  finalize() {
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
    if (this.buffer) {
      this.onTokenFlush?.(this.full, this.buffer);
      this.buffer = "";
    }
    return this.full;
  }
}

