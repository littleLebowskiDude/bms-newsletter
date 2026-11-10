// Offline support: the app shell and any issue you have opened keep working without signal.
const CACHE = 'bms-newsletter-v1';
const SHELL = ['./', 'index.html', 'app.css', 'app.js', 'manifest.webmanifest',
  'icons/icon-192.png', 'icons/logo.png', 'icons/mark.png',
  'fonts/dm-sans-normal.woff2', 'fonts/dm-sans-italic.woff2'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  const isData = url.pathname.includes('/data/');
  const save = (res) => {
    if (res.ok) caches.open(CACHE).then((c) => c.put(e.request, res.clone()));
    return res;
  };
  if (isData && !url.pathname.endsWith('.json')) {
    // pictures never change once published: cache first
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then(save)));
  } else {
    // everything else: fresh when online, cached copy when not
    e.respondWith(fetch(e.request).then(save).catch(() => caches.match(e.request, { ignoreSearch: true })));
  }
});
