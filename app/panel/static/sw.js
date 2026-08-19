/*
 * Service worker del panel.
 *
 * Hace dos cosas, y ninguna más:
 *
 *   1. Recibe los avisos push y los muestra aunque el panel esté cerrado.
 *   2. Guarda el armazón de la página para que abra al instante y muestre
 *      algo legible si el celular se queda sin señal.
 *
 * Lo que deliberadamente NO hace: guardar respuestas de la API. Una bandeja
 * de conversaciones vieja mostrada como si fuera actual es peor que un
 * error de red — la asistente creería que no hay nada pendiente. Todo lo
 * que sale de /panel/api va siempre a la red.
 */

const VERSION = "v1";
const CACHE = `panel-${VERSION}`;

/** El mínimo para que la app abra: la página y sus íconos. */
const ARMAZON = [
  "/panel",
  "/iconos/icono-192.png",
  "/iconos/icono-512.png",
];

self.addEventListener("install", function (evento) {
  evento.waitUntil(
    caches.open(CACHE)
      .then(function (c) { return c.addAll(ARMAZON); })
      .then(function () { return self.skipWaiting(); })
      .catch(function () { /* sin red al instalar: no es motivo de fallo */ })
  );
});

self.addEventListener("activate", function (evento) {
  evento.waitUntil(
    caches.keys()
      .then(function (nombres) {
        return Promise.all(nombres
          .filter(function (n) { return n !== CACHE; })
          .map(function (n) { return caches.delete(n); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (evento) {
  const peticion = evento.request;
  if (peticion.method !== "GET") return;

  const url = new URL(peticion.url);
  if (url.origin !== self.location.origin) return;

  // Datos: siempre de la red. Nunca se sirven de la caché.
  if (url.pathname.startsWith("/panel/api")) return;

  // La página: red primero, y la copia guardada solo si no hay señal. Así
  // una versión nueva del panel se ve en cuanto se publica.
  const esPagina = peticion.mode === "navigate" || url.pathname.startsWith("/panel");
  if (esPagina) {
    evento.respondWith(
      fetch(peticion)
        .then(function (respuesta) {
          const copia = respuesta.clone();
          caches.open(CACHE).then(function (c) { c.put("/panel", copia); });
          return respuesta;
        })
        .catch(function () {
          return caches.match("/panel").then(function (guardada) {
            return guardada || new Response(
              "<h1>Sin conexión</h1><p>El panel necesita internet para mostrar las conversaciones.</p>",
              { headers: { "Content-Type": "text/html; charset=utf-8" }, status: 503 }
            );
          });
        })
    );
    return;
  }

  // Íconos y estáticos: de la caché si están, y se refrescan de fondo.
  evento.respondWith(
    caches.match(peticion).then(function (guardada) {
      return guardada || fetch(peticion).then(function (respuesta) {
        const copia = respuesta.clone();
        caches.open(CACHE).then(function (c) { c.put(peticion, copia); });
        return respuesta;
      });
    })
  );
});

/* ---------------------------------------------------------------
 *  Avisos push
 * ------------------------------------------------------------- */

self.addEventListener("push", function (evento) {
  let datos = {};
  try { datos = evento.data ? evento.data.json() : {}; } catch (e) { datos = {}; }

  const titulo = datos.titulo || "Requiere atención";
  const enlace = datos.enlace || "/panel";
  const urgente = !!datos.urgente;

  evento.waitUntil(self.registration.showNotification(titulo, {
    body: datos.cuerpo || "Una conversación necesita a una persona.",
    icon: "/iconos/icono-192.png",
    badge: "/iconos/icono-192.png",
    lang: "es-MX",
    // Una urgencia no se descarta sola: se queda hasta que alguien la mire.
    requireInteraction: urgente,
    renotify: true,
    tag: datos.etiqueta || "panel",
    vibrate: urgente ? [200, 100, 200, 100, 200] : [120],
    data: { enlace: enlace },
    actions: [{ action: "abrir", title: "Abrir conversación" }],
  }));
});

self.addEventListener("notificationclick", function (evento) {
  evento.notification.close();
  const destino = (evento.notification.data && evento.notification.data.enlace) || "/panel";

  // Si el panel ya está abierto, se reutiliza esa ventana en lugar de
  // abrir una nueva: la asistente termina con quince pestañas si no.
  evento.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true })
      .then(function (ventanas) {
        for (const ventana of ventanas) {
          if (ventana.url.indexOf("/panel") !== -1 && "focus" in ventana) {
            ventana.navigate && ventana.navigate(destino);
            return ventana.focus();
          }
        }
        return self.clients.openWindow(destino);
      })
  );
});
