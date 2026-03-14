class FileUploader {
  constructor() {
    const input = document.getElementById("fileInput");
    if (input) {
      input.addEventListener("change", (e) => this.upload(e.target.files));
    }
  }

  async upload(files) {
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      form.append("subject", "general");

      await fetch("http://127.0.0.1:8000/api/upload", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${localStorage.getItem("token")}`
        },
        body: form
      });
    }
    alert("✅ Files uploaded successfully");
  }
}

window.fileUploader = new FileUploader();
