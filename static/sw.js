// App-shell cache so the PWA installs and opens offline.
// API + media always hit the network.
const CACHE = "ink-app-v63";
const SHELL = ["./", "index.html", "app.js", "styles.css", "jsqr.js", "walnut.jpg", "manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Ignore cross-origin (fonts) and API/media — only the app shell is cached.
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/media")) return;
  // server.txt is the live backend pointer — always fetch fresh, never cache.
  if (url.pathname.endsWith("/server.txt")) return;
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
