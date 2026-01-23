/* OpenLearnHub - Subjects: search, voice, level-based grid */

(function () {
  const API_BASE = 'http://localhost:5000/api';
  const grid = document.getElementById('subjectsGrid');
  const searchInput = document.getElementById('subjectSearch');
  const micBtn = document.getElementById('micBtn');

  const SUBJECTS = [
    { id: 'math', name: 'Mathematics', icon: '📐', levels: ['school', 'intermediate', 'engineering'] },
    { id: 'science', name: 'Science', icon: '🔬', levels: ['school', 'intermediate'] },
    { id: 'cs', name: 'Computer Science', icon: '💻', levels: ['intermediate', 'engineering'] },
    { id: 'ml', name: 'Machine Learning', icon: '🧠', levels: ['engineering'] },
    { id: 'physics', name: 'Physics', icon: '⚛️', levels: ['school', 'intermediate', 'engineering'] },
    { id: 'chemistry', name: 'Chemistry', icon: '🧪', levels: ['school', 'intermediate', 'engineering'] },
  ];

  function getLevel() {
    const params = new URLSearchParams(window.location.search);
    return params.get('level') || 'school';
  }

  function filterByLevel(list, level) {
    return list.filter(s => s.levels.includes(level));
  }

  function filterByQuery(list, q) {
    if (!q || !q.trim()) return list;
    const lower = q.trim().toLowerCase();
    return list.filter(s =>
      s.name.toLowerCase().includes(lower) || s.id.toLowerCase().includes(lower)
    );
  }

  function render(list) {
    if (!grid) return;
    grid.innerHTML = list.map(s => `
      <div class="subject-card card" data-id="${s.id}">
        <span class="subject-card-icon">${s.icon}</span>
        <h3>${s.name}</h3>
        <p>Explore ${s.name} topics and practice.</p>
      </div>
    `).join('');

    grid.querySelectorAll('.subject-card').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.id;
        if (id) window.location.href = `chatbot.html?subject=${id}`;
      });
    });
  }

  function run() {
    const level = getLevel();
    let list = filterByLevel(SUBJECTS, level);
    const q = (searchInput && searchInput.value) || '';
    list = filterByQuery(list, q);
    render(list);
  }

  if (searchInput) {
    searchInput.addEventListener('input', run);
    searchInput.addEventListener('change', run);
  }

  if (micBtn) {
    micBtn.addEventListener('click', function () {
      if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        alert('Voice search is not supported in this browser.');
        return;
      }
      const R = window.SpeechRecognition || window.webkitSpeechRecognition;
      const rec = new R();
      rec.continuous = false;
      rec.interimResults = false;
      rec.lang = 'en-IN';
      micBtn.classList.add('recording');
      rec.onresult = function (e) {
        const t = e.results[0][0].transcript;
        if (searchInput) searchInput.value = t;
        run();
      };
      rec.onend = rec.onerror = function () { micBtn.classList.remove('recording'); };
      rec.start();
    });
  }

  run();
})();
