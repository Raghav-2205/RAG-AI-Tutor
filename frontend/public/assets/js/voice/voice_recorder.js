class VoiceRecorder {
  constructor() {
    if ("webkitSpeechRecognition" in window) {
      this.recognition = new webkitSpeechRecognition();
      this.recognition.onresult = (e) => {
        document.getElementById("chatInput").value =
          e.results[0][0].transcript;
      };
    }
  }

  start() {
    this.recognition?.start();
  }
}

window.voiceRecorder = new VoiceRecorder();
