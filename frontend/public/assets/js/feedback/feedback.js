class Feedback {
  submit(ratingOrPayload, comment = "") {
    const apiBase = window.config?.apiBase || (window.location.origin + '/api');
    const payload = typeof ratingOrPayload === "object"
      ? ratingOrPayload
      : {
          source: "chat",
          subject: "general",
          reference_id: localStorage.getItem("currentSessionId") || "",
          rating: ratingOrPayload,
          comment
        };

    return fetch(`${apiBase}/feedback/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("token")}`
      },
      body: JSON.stringify(payload)
    });
  }
}

window.feedback = new Feedback();
