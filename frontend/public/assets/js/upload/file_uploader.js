class FileUploader {
  constructor() {
    const input = document.getElementById("fileInput");
    if (input) {
      input.addEventListener("change", (e) => this.upload(e.target.files));
    }
  }

  async upload(files) {
    const apiBase = window.config?.apiBase || (window.location.origin + '/api');
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      form.append("subject", "general");

      await fetch(`${apiBase}/upload/`, {
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
