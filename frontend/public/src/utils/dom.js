export function qs(root, sel) {
  return (root || document).querySelector(sel);
}

export function qsa(root, sel) {
  return Array.from((root || document).querySelectorAll(sel));
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null) continue;
    if (k === "class") node.className = String(v);
    else if (k === "dataset" && v && typeof v === "object") {
      for (const [dk, dv] of Object.entries(v)) node.dataset[dk] = String(dv);
    } else if (k === "text") node.textContent = String(v);
    else if (k === "html") node.innerHTML = String(v); // use only with sanitized content
    else if (k.startsWith("aria-")) node.setAttribute(k, String(v));
    else if (k === "role") node.setAttribute("role", String(v));
    else if (k in node) node[k] = v;
    else node.setAttribute(k, String(v));
  }

  const kids = Array.isArray(children) ? children : [children];
  for (const child of kids) {
    if (child === undefined || child === null) continue;
    if (typeof child === "string") node.appendChild(document.createTextNode(child));
    else node.appendChild(child);
  }
  return node;
}

export function on(target, event, selectorOrHandler, handler, options) {
  // on(el, "click", fn)
  if (typeof selectorOrHandler === "function") {
    target.addEventListener(event, selectorOrHandler, options);
    return () => target.removeEventListener(event, selectorOrHandler, options);
  }
  // on(el, "click", ".btn", fn)
  const selector = selectorOrHandler;
  const delegated = (e) => {
    const match = e.target?.closest?.(selector);
    if (!match || !target.contains(match)) return;
    handler(e, match);
  };
  target.addEventListener(event, delegated, options);
  return () => target.removeEventListener(event, delegated, options);
}

export function debounce(fn, waitMs = 120) {
  let t = null;
  return (...args) => {
    if (t) window.clearTimeout(t);
    t = window.setTimeout(() => fn(...args), waitMs);
  };
}

