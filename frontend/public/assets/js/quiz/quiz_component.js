class QuizComponent {
  async openQuiz(subject = "general") {
    const apiBase = window.config?.apiBase || (window.location.origin + '/api');
    const res = await fetch(`${apiBase}/quiz/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("token")}`
      },
      body: JSON.stringify({ subject, num_questions: 5 })
    });

    const quiz = await res.json();
    alert("Quiz generated! Check console.");
    console.log(quiz);
  }
}

window.quizComponent = new QuizComponent();
