// PriceWatch GR — Service Worker
const CACHE_NAME = 'pricewatch-v1';
const DATA_CACHE = 'pricewatch-data-v1';

const SHELL_FILES = [
  '/index.html',
  '/manifest.json',
];

// ── Install: cache app shell ────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: clean old caches ──────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME && k !== DATA_CACHE)
            .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: network-first για data, cache-first για shell ────────
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // prices.json — network first, fallback to cache
  if (url.pathname.endsWith('prices.json')) {
    e.respondWith(
      fetch(e.request)
        .then(resp => {
          const clone = resp.clone();
          caches.open(DATA_CACHE).then(c => c.put(e.request, clone));
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // App shell — cache first
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

// ── Background sync για refresh τιμών ──────────────────────────
self.addEventListener('sync', e => {
  if (e.tag === 'refresh-prices') {
    e.waitUntil(
      fetch('/prices.json')
        .then(resp => resp.json())
        .then(data => {
          return caches.open(DATA_CACHE).then(cache =>
            cache.put('/prices.json', new Response(JSON.stringify(data), {
              headers: { 'Content-Type': 'application/json' }
            }))
          );
        })
    );
  }
});

// ── Push notifications (για προσφορές) ─────────────────────────
self.addEventListener('push', e => {
  const data = e.data?.json() || {};
  e.waitUntil(
    self.registration.showNotification(data.title || 'PriceWatch GR', {
      body: data.body || 'Νέες προσφορές διαθέσιμες!',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-96.png',
      tag: 'pricewatch-offer',
      renotify: true,
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    clients.openWindow(e.notification.data?.url || '/')
  );
});
