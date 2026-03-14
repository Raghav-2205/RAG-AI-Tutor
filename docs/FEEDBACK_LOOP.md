# 🔄 Adaptive Feedback & Self-Correction

The **RAG AI Tutor** implements an advanced feedback loop that allows the system to "learn" from user interactions, improving retrieval accuracy and answer quality over time.

---

## 🔁 The Feedback Cycle

### 1. Data Collection
Users interact with the AI in two ways:
-   **Chat**: Rating answers with Thumbs Up/Down.
-   **Quiz**: Answering generated questions (Correct/Incorrect).

This data is captured via the `/api/feedback/` endpoint and stored in MongoDB (`feedback` collection).

**Schema:**
```json
{
  "_id": "ObjectId(...)",
  "user_id": "user_123",
  "source": "chat",          // or "quiz"
  "reference_id": "chunk_456", // ID of the chunk cited
  "rating": "negative",      // "positive" or "negative"
  "subject": "physics",
  "comment": "This explanation was too complex.",
  "timestamp": "2024-03-15T10:00:00Z"
}
```

### 2. Chunk Reputation Scoring
Each document chunk has a dynamic **Reputation Score** (default: 1.0).
-   **Positive Feedback**: Increases score (+0.1).
-   **Negative Feedback**: Decreases score (-0.2).

*Logic:*
```python
new_score = current_score + (0.1 if feedback == 'positive' else -0.2)
```
This score is stored in ChromaDB metadata or a separate mapping table.

### 3. Adaptive Retrieval
The `HybridSearchEngine` uses the Reputation Score to weight search results:
1.  **Search**: Perform standard Hybrid Search (BM25 + Vector).
2.  **Weighting**: Multiply the retrieval score by the chunk's Reputation Score.
    ```python
    final_score = rrf_score * chunk.reputation
    ```
3.  **Reranking**: The Cross-Encoder re-evaluates the weighted list.

**Outcome**: Chunks that consistently receive negative feedback (e.g., outdated or confusing content) gradually "sink" to the bottom of the results, while high-quality chunks rise to the top.

---

## 🧠 Adaptive System Prompts

The system also adapts the LLM's persona based on user feedback trends.

### Weak Topic Identification
If a student consistently fails quizzes in specific topics (e.g., "Quantum Mechanics"), the system:
1.  Tags the user profile with `weak_topics: ["Quantum Mechanics"]`.
2.  Injects a special instruction into the system prompt:
    > "The user struggles with Quantum Mechanics. Break down concepts into simpler terms and use analogies."

### Difficulty Adjustment
Based on the user's explicit preference or quiz performance:
-   **Beginner**: "Explain like I'm 5."
-   **Intermediate**: "Standard academic tone."
-   **Advanced**: "Technical depth, assumes prior knowledge."
