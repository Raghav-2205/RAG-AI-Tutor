/**
 * notifications.js — Shared notification badge loader
 * Include in any page that shows a notification bell.
 * Call: loadNotificationBadge('your-badge-element-id')
 */
async function loadNotificationBadge(badgeId) {
    try {
        const token = localStorage.getItem('token');
        if (!token) return;
        const res = await fetch('/api/lms/notifications?unread=true', {
            headers: { Authorization: 'Bearer ' + token }
        });
        if (!res.ok) return;
        const data = await res.json();
        const count = Array.isArray(data) ? data.filter(n => !n.read).length : 0;
        const el = document.getElementById(badgeId);
        if (el) {
            el.textContent = count;
            el.style.display = count > 0 ? 'inline' : 'none';
        }
    } catch (_) { /* silent fail — non-critical */ }
}
