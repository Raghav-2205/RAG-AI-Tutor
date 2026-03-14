class Feedback {
  submit(rating, comment) {
    fetch("http://127.0.0.1:8000/api/feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("token")}`
      },
      body: JSON.stringify({ rating, comment })
    });
  }
}

window.feedback = new Feedback();
