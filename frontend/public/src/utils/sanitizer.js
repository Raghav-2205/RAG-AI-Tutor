const ALLOWED_TAGS = new Set([
  "A",
  "B",
  "BLOCKQUOTE",
  "BUTTON",
  "BR",
  "CODE",
  "DETAILS",
  "DIV",
  "EM",
  "H2",
  "H3",
  "H4",
  "HR",
  "I",
  "KBD",
  "LI",
  "OL",
  "P",
  "PRE",
  "S",
  "SMALL",
  "SPAN",
  "STRONG",
  "SUB",
  "SUP",
  "SUMMARY",
  "UL"
]);

const ALLOWED_ATTRS = new Set([
  "class",
  "href",
  "title",
  "target",
  "rel",
  "type",
  "aria-label",
  "aria-hidden",
  "role",
  "data-chunk-id",
  "data-action"
]);

function isSafeUrl(url) {
  if (!url) return false;
  try {
    const u = new URL(url, window.location.origin);
    return u.protocol === "http:" || u.protocol === "https:" || u.protocol === "mailto:";
  } catch {
    return false;
  }
}

function sanitizeElement(el) {
  // Drop forbidden tags by replacing with their text content.
  if (!ALLOWED_TAGS.has(el.tagName)) {
    const text = document.createTextNode(el.textContent || "");
    el.replaceWith(text);
    return;
  }

  // Remove dangerous attributes.
  for (const attr of Array.from(el.attributes)) {
    const name = attr.name.toLowerCase();
    const value = attr.value;
    if (name.startsWith("on")) {
      el.removeAttribute(attr.name);
      continue;
    }
    if (name === "style" || name === "srcdoc") {
      el.removeAttribute(attr.name);
      continue;
    }
    if (!ALLOWED_ATTRS.has(attr.name)) {
      el.removeAttribute(attr.name);
      continue;
    }
    if (name === "href") {
      if (!isSafeUrl(value)) el.removeAttribute("href");
      else {
        // Avoid window.opener issues if target=_blank
        if (el.getAttribute("target") === "_blank") {
          el.setAttribute("rel", "noreferrer noopener");
        }
      }
    }
  }
}

/**
 * Sanitize an HTML string into a DocumentFragment.
 * Use for markdown output before injecting into the DOM.
 */
export function sanitizeToFragment(unsafeHtml) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(String(unsafeHtml || ""), "text/html");

  // Remove whole dangerous nodes early.
  for (const bad of doc.querySelectorAll("script, style, iframe, object, embed, link, meta")) {
    bad.remove();
  }

  const treeWalker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_ELEMENT);
  const toSanitize = [];
  while (treeWalker.nextNode()) toSanitize.push(treeWalker.currentNode);
  for (const node of toSanitize) sanitizeElement(node);

  const frag = document.createDocumentFragment();
  while (doc.body.firstChild) frag.appendChild(doc.body.firstChild);
  return frag;
}

