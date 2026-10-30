// Offline support: pages and data are fetched fresh when online and served
// from the cache when offline. Bump VERSION when the app shell changes.
const VERSION = 'betbuilder-v1';
const SHELL = ['./', 'index.html', 'stats.html', 'assets/app.css', 'assets/dash.js', 'assets/app.js',
  'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png',
  'assets/d3.min.js'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  e.respondWith(
    fetch(req).then((res) => {
      if (res.ok || res.type === 'opaque') { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req, { ignoreSearch: true }).then((m) => m || caches.match('index.html')))
  );
});
