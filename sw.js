const CACHE_NAME = "fx-trade-lab-v3";
const SHELL_FILES = [
  "./",
  "./index.html",
  "./css/style.css",
  "./js/api.js",
  "./js/app.js",
  "./manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
});

// API通信(/api/, /health)はキャッシュせず常にネットワークから取得する
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return; // バックエンドAPIはそのまま素通り

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
