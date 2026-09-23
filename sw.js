/* Daily Wire service worker.
 *
 * Two policies:
 *   - the shell (page, manifest, icons) is served cache-first, so opening the
 *     app from the home screen is instant and works with no signal;
 *   - the briefs under data/ are network-first, so you always get today's if
 *     you are online and the last one you opened if you are not.
 *
 * Bump CACHE_VERSION whenever index.html changes, or returning visitors will
 * keep the old shell until their browser evicts it.
 */

const CACHE_VERSION = "wire-v3";
const SHELL = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icons/icon.svg",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      // addAll fails the whole install if any single file 404s; this way a
      // missing icon cannot stop the app from working offline.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // let fonts go to the network

  if (url.pathname.includes("/data/")) {
    event.respondWith(networkFirst(request));
  } else {
    event.respondWith(cacheFirst(request));
  }
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) cache.put(request, fresh.clone());
    return fresh;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  if (cached) {
    // Refresh in the background so the next open has the newer shell.
    fetch(request)
      .then((fresh) => {
        if (fresh && fresh.ok) cache.put(request, fresh.clone());
      })
      .catch(() => {});
    return cached;
  }
  const fresh = await fetch(request);
  if (fresh && fresh.ok) cache.put(request, fresh.clone());
  return fresh;
}
