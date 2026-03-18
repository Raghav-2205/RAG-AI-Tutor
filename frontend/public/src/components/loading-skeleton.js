import { el } from "../utils/dom.js";

export function sessionListSkeleton(count = 6) {
  const items = [];
  for (let i = 0; i < count; i++) {
    items.push(el("div", { class: "skeleton", style: "height:56px; margin-bottom:10px;" }));
  }
  return el("div", {}, items);
}

export function inlineError(message, { actionLabel, onAction } = {}) {
  const root = el("div", {
    class: "msg msg--ai",
    role: "status",
    "aria-live": "polite"
  });
  root.appendChild(el("div", { class: "msg__meta" }, [
    el("div", { class: "msg__role", text: "System" }),
    el("div", { text: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) })
  ]));
  root.appendChild(el("div", { class: "msg__content" }, [
    el("p", { text: message || "Something went wrong." })
  ]));

  if (actionLabel && typeof onAction === "function") {
    root.appendChild(el("div", { style: "margin-top:12px; display:flex; gap:8px;" }, [
      el("button", { class: "btn btn--primary", type: "button", text: actionLabel, onclick: onAction })
    ]));
  }
  return root;
}

