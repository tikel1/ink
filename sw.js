// App-shell cache so the PWA installs and opens offline.
// Strategy: NETWORK-FIRST for the shell — always try the network so a new deploy
// shows up on the next load, and fall back to the cache only when offline. (This
// replaced cache-first, which kept serving stale CSS/JS until a version bump.)
// API + media always hit the network directly.
const CACHE = "ink-app-v104";
const SHELL = ["./", "index.html", "app.js", "styles.css", "jsqr.js", "walnut.jpg", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png", "icon-192-maskable.png", "icon-512-maskable.png", "apple-touch-icon.png"];

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
  // Network-first: fresh when online (deploys appear immediately), cache offline.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
          return res;
        }
        return caches.match(e.request).then((hit) => hit || res);
      })
      .catch(() => caches.match(e.request))
  );
});
