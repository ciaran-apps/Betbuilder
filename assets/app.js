// "Data updated" line and offline support.
(function () {
  const el = document.getElementById('app-updated');
  fetch('data/meta.json', { cache: 'no-cache' }).then((r) => r.json()).then((m) => {
    const d = new Date(m.updated);
    const f = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London' });
    el.textContent = `Data updated ${f.format(d)} · gameweeks ${m.gw_first}–${m.gw_last}`;
  }).catch(() => { el.textContent = ''; });
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
})();
