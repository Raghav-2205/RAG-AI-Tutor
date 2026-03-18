import { el } from "../utils/dom.js";

function clamp01(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return 0;
  return Math.max(0, Math.min(1, x));
}

function statusTone(status) {
  const s = String(status || "").toUpperCase();
  if (s === "VERIFIED" || s === "SAFE") return { tone: "safe", label: "Safe", icon: "✓" };
  if (s === "WARNING") return { tone: "warn", label: "Warning", icon: "⚠" };
  return { tone: "bad", label: s ? s.toLowerCase() : "Reject", icon: "✕" };
}

function meter(label, value) {
  const pct = Math.round(clamp01(value) * 100);
  return el("div", { class: "meter" }, [
    el("div", { text: label }),
    el("div", { class: "meter__bar", role: "img", "aria-label": `${label} ${pct} percent` }, [
      el("div", { class: "meter__fill", style: `width:${pct}%;` })
    ]),
    el("div", { text: `${pct}%` })
  ]);
}

export function renderValidationStrip(validation) {
  if (!validation) return null;

  const faith = validation.faithfulness_score ?? 0;
  const rel = validation.retrieval_confidence ?? validation.answer_relevance ?? 0;
  const { tone, label, icon } = statusTone(validation.validation_status);

  const evalId = validation._id || validation.id || "";
  const usedSourcesCount = validation?.chunk_usage?.used_chunks ?? 0;

  const details = el("details", {}, [
    el("summary", { text: "Metrics details" }),
    el("div", { style: "margin-top:10px; display:grid; gap:8px;" }, [
      el("div", { text: `RAG score: ${(validation.final_rag_score ?? 0).toFixed?.(2) ?? (validation.final_rag_score ?? 0)}` }),
      el("div", { text: `BERTScore: ${(validation.bert_score ?? 0).toFixed?.(2) ?? (validation.bert_score ?? 0)}` }),
      el("div", { text: `Answer relevance: ${(validation.answer_relevance ?? 0).toFixed?.(2) ?? (validation.answer_relevance ?? 0)}` }),
      el("div", { text: `Vector similarity: ${(validation.cosine_similarity ?? 0).toFixed?.(2) ?? (validation.cosine_similarity ?? 0)}` }),
      usedSourcesCount
        ? el("div", { text: `Sources used: ${usedSourcesCount}` })
        : el("div", { text: "Sources used: 0" }),
      evalId
        ? el("a", { href: `/views/evaldoc.html?id=${encodeURIComponent(evalId)}`, text: "Open full evaluation report →" })
        : el("div", { text: "" })
    ])
  ]);

  if (Array.isArray(validation.unsupported_sentences) && validation.unsupported_sentences.length) {
    const list = el("ul", { style: "margin:10px 0 0; padding-left: 1.2rem;" },
      validation.unsupported_sentences.slice(0, 6).map((s) => el("li", { text: String(s) })));
    details.appendChild(el("div", { style: "margin-top:10px;" }, [
      el("strong", { text: "Unsupported claims:" }),
      list
    ]));
  }

  return el("div", { class: "vstrip", role: "group", "aria-label": "Validation results" }, [
    el("div", { class: "vstrip__row" }, [
      meter("Faithfulness", faith),
      meter("Relevance", rel),
      el("div", { class: "vstrip__status", dataset: { tone }, "aria-label": `Validation status ${label}` }, [
        el("span", { text: icon }),
        el("span", { text: label })
      ])
    ]),
    details
  ]);
}

