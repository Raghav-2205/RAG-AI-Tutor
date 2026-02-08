class QuizComponent {
  async openQuiz(subject = "general") {
    const res = await fetch("http://127.0.0.1:8000/api/quiz/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("token")}`
      },
      body: JSON.stringify({ subject, numQuestions: 5 })
    });

    const quiz = await res.json();
    alert("Quiz generated! Check console.");
    console.log(quiz);
  }
}

window.quizComponent = new QuizComponent();
