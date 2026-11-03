// "Data updated" line, refresh button and offline support.
(function () {
  const el = document.getElementById('app-updated');
  const f = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London' });
  const label = document.createElement('span');
  const btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'app-refresh'; btn.textContent = '↻ Refresh'; btn.setAttribute('aria-label', 'Refresh the data');
  el.replaceChildren(label, btn);
  function showMeta() {
    return fetch('data/meta.json', { cache: 'no-cache' }).then((r) => r.json()).then((m) => {
      const d = new Date(m.updated);
      const old = Date.now() - d.getTime() > 26 * 3600 * 1000;
      label.textContent = `Data updated ${f.format(d)} · gameweeks ${m.gw_first}–${m.gw_last}${old ? ' · may be out of date' : ''}`;
      el.classList.toggle('stale', old);
    }).catch(() => { label.textContent = navigator.onLine ? '' : 'Offline · showing the last data loaded'; });
  }
  showMeta();
  window.addEventListener('dash-reloaded', showMeta);
  btn.addEventListener('click', () => {
    btn.disabled = true; btn.textContent = '↻ Refreshing…';
    const done = () => { btn.disabled = false; btn.textContent = '↻ Refresh'; };
    (window.dash && dash.refresh ? dash.refresh() : Promise.resolve()).then(showMeta).then(done, done);
  });
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').then((reg) => reg.update()).catch(() => {});
  }
})();
