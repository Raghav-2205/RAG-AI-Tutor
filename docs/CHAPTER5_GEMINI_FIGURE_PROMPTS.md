# Chapter 5 Gemini Figure Prompts

This file provides thesis-ready, copy-paste prompts for generating Chapter 5 figures in Gemini. The prompts are grounded in the LMS-V2 repository architecture, while preserving the Chapter 5 presentation choices approved for the thesis.

## Affected Domains

- LMS
- Upload and ingestion
- RAG chat
- Citations and GRAG
- Evaluation and performance

## Verified Contracts

- LMS classes use `id` and `class_id`, include `subject`, have teacher ownership, and maintain enrolled student lists.
- Chat and upload flows carry `chat_id`, `subject`, `class_id`, `document_ids`, `document_names`, and `file_count`.
- The retrieval pipeline includes query embedding, ChromaDB retrieval, reranking, Gemini generation, and citation or GRAG grounding.

## Shared Prompt Defaults

Use these defaults for both figures unless you intentionally override them:

- Style: academic diagram
- Orientation: landscape
- Aspect ratio: 16:9
- Background: white
- Palette: restrained blue, teal, gray, with one red warning accent
- Typography: crisp sans-serif, highly readable at thesis print size
- Quality goal: clean vector-style infographic suitable for a dissertation
- Avoid: photorealism, UI screenshots, 3D rendering, people faces, clutter, neon styling, watermarks, long paragraphs inside the image, spelling mistakes

## Figure 5.1.9 Prompt

### Title

`Figure 5.1.9 - LMS Integration Workflow`

### Gemini Prompt

```text
Create a clean academic workflow diagram for a university LMS with integrated RAG tutoring. The figure title is "Figure 5.1.9 - LMS Integration Workflow". Use a white background, 16:9 landscape layout, vector-style graphics, crisp sans-serif labels, and a restrained blue, teal, and gray palette with one red warning accent.

Show the workflow from left to right with short thesis-formal labels:

1. Instructor creates named course
2. Students enroll in course
3. Instructor uploads course documents
4. Document preprocessing pipeline
   - text extraction
   - chunking
   - embedding
5. ChromaDB stores separate course-labeled knowledge collections
   - Software Engineering Collection
   - Artificial Intelligence Collection
   - Database Systems Collection
6. Student submits question from enrolled course
7. Retrieval is routed only to the enrolled course collection
8. Gemini generates grounded answer
9. GRAG and citation mapping return traceable evidence

Include clear academic icons for instructor, students, documents, processing pipeline, vector database, AI model, and citations.

Very important: visually emphasize course-boundary enforcement. Show one Software Engineering student asking a question that goes only to the Software Engineering collection. Also show a blocked red arrow with a prohibition symbol from that student toward the Artificial Intelligence collection to represent cross-course retrieval prevention.

Add a small label near the retrieval control point saying: "Course-aware retrieval boundary".

The figure must communicate that LMS-V2 is not a generic chatbot attached to an LMS, but a natively integrated academic assistant where retrieval is governed by course enrollment.

Keep the diagram minimal, structured, and printable in grayscale. Do not include paragraphs inside the figure. Do not mimic a software UI screenshot.
```

### Notes

- Treat the per-course Chroma collections as thesis architecture for the figure, not as a literal code-level collection naming diagram.
- Keep only short labels inside the image. The explanatory paragraph belongs in the thesis body, not in the figure.

## Figure 5.1.10 Prompt

### Title

`Figure 5.1.10 - End-to-End Latency Analysis`

### Gemini Prompt

```text
Create a clean academic performance diagram titled "Figure 5.1.10 - End-to-End Latency Analysis". Use a white background, 16:9 landscape layout, vector-style academic infographic design, crisp sans-serif typography, and a restrained blue, teal, and gray palette with one warm highlight color for the bottleneck.

Show a horizontal pipeline with five clearly separated stages and exact timing labels:

1. Query Embedding - 12 ms
2. ChromaDB Retrieval - 240 ms
3. Cross-Encoder Reranking - 180 ms
4. Gemini API Generation - 1.8 s
5. GRAG Citation Mapping - 90 ms

Make the Gemini API Generation block visually largest to show that it is the dominant bottleneck. Add a callout bubble or annotation that says: "85% of total latency".

Add a secondary annotation below the pipeline saying:
"Internal pipeline total: 522 ms"

Add another summary annotation saying:
"Average end-to-end latency: 2.1 s (single user)"

Represent the latency contributions with proportional visual weight, such as bar widths or stage emphasis, while keeping the layout clear and thesis-formal.

Use subtle database and model icons where helpful, but keep the figure minimal and readable. Make sure the exact timing labels are easy to read in print and grayscale. Do not include any claim that 3.2 seconds satisfies a 3 second requirement. Do not include extra paragraphs inside the figure. Do not make it look like a dashboard screenshot.
```

### Notes

- Use `Figure 5.1.10` as the final figure number.
- Keep the figure focused on the single-user average and the per-stage breakdown.

## Quick QA Checklist

Use this checklist after Gemini generates the images:

- Figure 5.1.9 clearly shows course-aware retrieval and blocked cross-course access.
- Figure 5.1.9 includes separate course-labeled knowledge collections.
- Figure 5.1.10 contains all five stages with the exact timing values.
- Figure 5.1.10 shows `Internal pipeline total: 522 ms`.
- Figure 5.1.10 shows `Average end-to-end latency: 2.1 s (single user)`.
- Both figures are readable at thesis page width.
- Both figures still make sense when printed in grayscale.
- The titles match exactly: `Figure 5.1.9` and `Figure 5.1.10`.

## Assumptions and Risks

- These prompts follow thesis-ready framing rather than code-literal storage naming.
- The LMS workflow prompt intentionally visualizes per-course Chroma scoping as the thesis architecture.
- The latency breakdown values are treated as validated thesis measurements to be displayed in the diagram, not as numbers extracted directly from repository timing logs.
