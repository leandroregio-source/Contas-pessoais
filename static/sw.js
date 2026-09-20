/* Service worker.
   Regras simples e deliberadas:
   - Casca do app (HTML/CSS/JS/ícones): cache-first, para abrir instantâneo.
   - /api/*: SEMPRE rede. Dado financeiro velho servido do cache seria pior que
     erro de conexão — o usuário tomaria decisão com número errado.
   - Sem cache em POST/PATCH/DELETE.
*/
const VERSAO = "gastos-v1";
const CASCA = [
  "/",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/api.js",
  "/static/js/charts.js",
  "/static/js/screens.js",
  "/static/js/orcamento.js",
  "/static/icons/icone.svg",
  "/manifest.webmanifest",
];

self.addEventListener("install", (ev) => {
  ev.waitUntil(
    caches.open(VERSAO)
      // addAll falha inteiro se um item faltar; individual é mais tolerante.
      .then((c) => Promise.allSettled(CASCA.map((u) => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(
        nomes.filter((n) => n !== VERSAO).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (ev) => {
  const req = ev.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/login")) return;

  ev.respondWith(
    caches.match(req).then((cacheado) => {
      const daRede = fetch(req)
        .then((resp) => {
          if (resp.ok && resp.type === "basic") {
            const copia = resp.clone();
            caches.open(VERSAO).then((c) => c.put(req, copia));
          }
          return resp;
        })
        .catch(() => cacheado);
      // Cache primeiro para abrir rápido, revalidando em segundo plano.
      return cacheado || daRede;
    })
  );
});
