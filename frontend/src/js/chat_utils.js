/* OpenLearnHub - Chat with RAG AI Tutor */
(function () {
  const chatMessages = document.getElementById('chatMessages');
  const chatInput = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');
  const chatStatus = document.getElementById('chatStatus');
  const welcomeMsg = document.getElementById('welcomeMsg');

  let sessionId = 'session-' + Date.now();

  function addMessage(text, role, timeLabel) {
    if (!chatMessages) return;
    const div = document.createElement('div');
    div.className = 'message ' + role;
    const p = document.createElement('p');
    p.textContent = text || '';
    div.appendChild(p);
    const time = document.createElement('span');
    time.className = 'message-time';
    time.textContent = timeLabel || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    div.appendChild(time);
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function setStatus(msg) {
    if (chatStatus) chatStatus.textContent = msg;
  }

  async function sendMessage() {
    const raw = chatInput && chatInput.value ? chatInput.value.trim() : '';
    if (!raw) return;

    if (chatInput) chatInput.value = '';
    if (sendBtn) sendBtn.disabled = true;
    setStatus('RAG AI Tutor is thinking...');

    addMessage(raw, 'user');

    const apiBase = (window.OLH_AUTH && window.OLH_AUTH.API_BASE) ? window.OLH_AUTH.API_BASE : '/api';
    const token = window.OLH_AUTH && window.OLH_AUTH.getToken ? window.OLH_AUTH.getToken() : null;

    try {
      const res = await fetch(apiBase + '/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: 'Bearer ' + token } : {}),
        },
        body: JSON.stringify({ message: raw, session_id: sessionId }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const errMsg = data.detail || data.message || 'Request failed';
        const msg = Array.isArray(errMsg) ? (errMsg[0] && errMsg[0].msg) || JSON.stringify(errMsg) : errMsg;
        addMessage('Error: ' + msg, 'ai');
        setStatus('');
        if (sendBtn) sendBtn.disabled = false;
        if (chatInput) chatInput.focus();
        return;
      }

      const reply = data.reply || data.message || 'No reply.';
      addMessage(reply, 'ai');
      setStatus('');
    } catch (err) {
      addMessage('Error: ' + (err.message || 'Could not reach the tutor.'), 'ai');
      setStatus('');
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      if (chatInput) chatInput.focus();
    }
  }

  if (sendBtn) sendBtn.addEventListener('click', sendMessage);
  if (chatInput) {
    chatInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  if (chatInput) chatInput.focus();
})();
