/**
 * voice.js
 * Handles Web Speech API for Speech-to-Text (STT) and Text-to-Speech (TTS)
 */

export class VoiceManager {
    constructor(inputElementId, micBtnId, onResultCallback) {
        this.inputElement = document.getElementById(inputElementId);
        this.micBtn = document.getElementById(micBtnId);
        this.onResultCallback = onResultCallback;
        
        this.isRecording = false;
        this.recognition = null;
        this.ttsEnabled = false;

        this.initSTT();
    }

    initSTT() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn("Speech Recognition API not supported in this browser.");
            if (this.micBtn) {
                this.micBtn.style.display = 'none'; // Hide if not supported
            }
            return;
        }

        this.recognition = new SpeechRecognition();
        this.recognition.continuous = false;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-US';

        this.recognition.onstart = () => {
            this.isRecording = true;
            if (this.micBtn) {
                this.micBtn.classList.add('recording');
                this.micBtn.innerHTML = '🔴'; // Keep simple visual indicator
            }
        };

        this.recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }

            if (finalTranscript) {
                const currentVal = this.inputElement.value;
                this.inputElement.value = currentVal ? currentVal + ' ' + finalTranscript : finalTranscript;
                if (this.onResultCallback) this.onResultCallback(); // e.g. resize textarea
            } 
        };

        this.recognition.onerror = (event) => {
            console.error("Speech Recognition Error:", event.error);
            this.stopRecording();
        };

        this.recognition.onend = () => {
            this.stopRecording();
        };

        if (this.micBtn) {
            this.micBtn.addEventListener('click', () => {
                if (this.isRecording) {
                    this.stopRecording();
                } else {
                    this.startRecording();
                }
            });
        }
    }

    startRecording() {
        if (!this.recognition) return;
        try {
            this.recognition.start();
        } catch (e) {
            console.error("Could not start recognition", e);
        }
    }

    stopRecording() {
        if (!this.recognition) return;
        this.isRecording = false;
        try {
            this.recognition.stop();
        } catch(e) {}
        if (this.micBtn) {
            this.micBtn.classList.remove('recording');
            this.micBtn.innerHTML = '🎤'; // Reset icon
        }
    }

    toggleTTS(enabled) {
        this.ttsEnabled = enabled;
        if (!enabled) {
            window.speechSynthesis.cancel();
        }
    }

    readAloud(htmlText) {
        if (!this.ttsEnabled || !window.speechSynthesis) return;

        // Strip HTML tags and citation brackets e.g. [1] or [CHUNK 1]
        let cleanText = htmlText.replace(/<[^>]+>/g, ' '); 
        cleanText = cleanText.replace(/\[\s*(?:CHUNK\s*)?\d+\s*\]/gi, '');
        // Strip markdown asterisks and hash symbols
        cleanText = cleanText.replace(/[\*#_]/g, '');

        if (!cleanText.trim()) return;

        // Cancel previous speech
        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        
        // Try to pick a natural English voice if available
        const voices = window.speechSynthesis.getVoices();
        const preferredVoice = voices.find(v => v.lang.startsWith('en') && (v.name.includes('Google') || v.name.includes('Natural')));
        if (preferredVoice) {
            utterance.voice = preferredVoice;
        }

        window.speechSynthesis.speak(utterance);
    }
}
