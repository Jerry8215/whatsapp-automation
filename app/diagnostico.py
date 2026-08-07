"""
Diagnóstico de la configuración de Meta, desde el servidor.

**Por qué existe.** Todo lo que se configura en la consola de Meta —el
número, el webhook, las plantillas, la calificación de calidad— se puede
consultar por la Graph API con el mismo token que usa el sistema.

Eso permite verificar y diagnosticar sin entrar a la consola: útil cuando
quien configura es el consultorio y quien desarrolla necesita saber qué
quedó mal. En lugar de pedir capturas de pantalla, se abre esta página y
dice exactamente qué falta.

Solo para el administrador del panel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.config import config
from app.models import RolUsuario, Usuario
from app.panel.auth import solo_admin, usuario_actual

log = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostico", tags=["diagnóstico"])

TIEMPO_ESPERA = 15.0

OK, AVISO, FALLA, SIN_DATO = "ok", "aviso", "falla", "sin_dato"


@dataclass
class Prueba:
    nombre: str
    estado: str = SIN_DATO
    detalle: str = ""
    ayuda: str = ""
    datos: dict[str, Any] = field(default_factory=dict)


async def _consultar(ruta: str, params: dict | None = None) -> tuple[bool, Any]:
    """Devuelve (ok, datos o mensaje de error)."""
    if not config.wa_token:
        return False, "No hay token configurado"

    url = f"{config.wa_api_base}/{ruta.lstrip('/')}"
    cabeceras = {"Authorization": f"Bearer {config.wa_token}"}

    try:
        async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as c:
            r = await c.get(url, headers=cabeceras, params=params or {})
    except Exception as e:
        return False, f"No se pudo contactar a Meta: {e}"

    if r.status_code >= 400:
        try:
            error = r.json().get("error", {})
            mensaje = error.get("message", r.text)
            codigo = error.get("code", r.status_code)
            return False, f"[{codigo}] {mensaje}"
        except Exception:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"

    return True, r.json()


# ======================================================================
#  Pruebas
# ======================================================================

async def _variables() -> Prueba:
    faltan = [
        nombre for nombre, valor in [
            ("WA_TOKEN", config.wa_token),
            ("WA_PHONE_NUMBER_ID", config.wa_phone_number_id),
            ("WA_BUSINESS_ACCOUNT_ID", config.wa_business_account_id),
            ("WA_APP_SECRET", config.wa_app_secret),
            ("WA_VERIFY_TOKEN", config.wa_verify_token),
        ] if not valor or valor == "cambiar-esto"
    ]
    if faltan:
        return Prueba(
            "Variables de entorno",
            FALLA,
            f"Faltan: {', '.join(faltan)}",
            "Se copian de la consola de Meta al archivo .env del servidor.",
        )
    return Prueba("Variables de entorno", OK, "Todas configuradas")


async def _token() -> Prueba:
    """El token es lo primero: si no sirve, todo lo demás falla igual."""
    ok, datos = await _consultar(
        config.wa_phone_number_id,
        {"fields": "display_phone_number,verified_name,quality_rating,"
                   "code_verification_status,platform_type,throughput"},
    )
    if not ok:
        texto = str(datos)
        bajo = texto.lower()

        # Meta usa el código 190 tanto para «vencido» como para «mal
        # copiado». Distinguirlos importa: mandan a buscar el problema a
        # lugares distintos.
        if "malformed" in bajo or "cannot parse" in bajo:
            return Prueba(
                "Token de acceso", FALLA, texto,
                "El token está mal copiado o incompleto. Son cadenas muy "
                "largas: hay que copiarla entera, sin espacios ni saltos de "
                "línea, y sin las comillas.",
            )
        if "expired" in bajo or "session has expired" in bajo:
            return Prueba(
                "Token de acceso", FALLA, texto,
                "El token venció. Los temporales duran 24 horas: hay que "
                "crear un usuario del sistema con token permanente en "
                "Configuración del negocio → Usuarios → Usuarios del sistema.",
            )
        if "190" in texto:
            return Prueba(
                "Token de acceso", FALLA, texto,
                "Token inválido: puede estar vencido, mal copiado o revocado. "
                "Lo más seguro es generar uno nuevo desde un usuario del "
                "sistema, que no caduca.",
            )
        if "permission" in bajo or "(#200)" in texto or "(#10)" in texto:
            return Prueba(
                "Token de acceso", FALLA, texto,
                "El token es válido pero no tiene permisos sobre este número. "
                "Verificar que el usuario del sistema tenga asignada la cuenta "
                "de WhatsApp con control total.",
            )
        return Prueba(
            "Token de acceso", FALLA, texto,
            "Verificar que el token corresponda a esta cuenta y tenga "
            "permisos sobre este número.",
        )

    return Prueba(
        "Token de acceso", OK,
        f"Válido · número {datos.get('display_phone_number', '—')}",
        datos=datos,
    )


async def _numero() -> Prueba:
    ok, datos = await _consultar(
        config.wa_phone_number_id,
        {"fields": "display_phone_number,verified_name,quality_rating,"
                   "code_verification_status,name_status"},
    )
    if not ok:
        return Prueba("Número de WhatsApp", SIN_DATO, str(datos))

    calidad = (datos.get("quality_rating") or "").upper()
    verificacion = datos.get("code_verification_status", "")

    if calidad in ("RED", "LOW"):
        return Prueba(
            "Número de WhatsApp", FALLA,
            f"Calificación de calidad BAJA · {datos.get('display_phone_number', '')}",
            "Los pacientes están bloqueando o reportando los mensajes. Meta "
            "puede reducir el límite de envío. Revisar los recordatorios: "
            "que sean relevantes y esperados.",
            datos,
        )
    if calidad == "YELLOW" or calidad == "MEDIUM":
        return Prueba(
            "Número de WhatsApp", AVISO,
            f"Calificación media · {datos.get('display_phone_number', '')}",
            "Conviene vigilarla. Si baja más, Meta reduce el límite de envío.",
            datos,
        )
    if verificacion and verificacion != "VERIFIED":
        return Prueba(
            "Número de WhatsApp", AVISO,
            f"Verificación del número: {verificacion}",
            "Completar la verificación en WhatsApp Manager.",
            datos,
        )

    return Prueba(
        "Número de WhatsApp", OK,
        f"{datos.get('display_phone_number', '—')} · "
        f"«{datos.get('verified_name', '—')}» · calidad {calidad or 'sin datos'}",
        datos=datos,
    )


async def _webhook() -> Prueba:
    """¿La app está suscrita a los mensajes de esta cuenta?"""
    if not config.wa_business_account_id:
        return Prueba(
            "Suscripción del webhook", SIN_DATO,
            "Falta WA_BUSINESS_ACCOUNT_ID",
        )

    ok, datos = await _consultar(f"{config.wa_business_account_id}/subscribed_apps")
    if not ok:
        return Prueba("Suscripción del webhook", SIN_DATO, str(datos))

    apps = datos.get("data", [])
    if not apps:
        return Prueba(
            "Suscripción del webhook", FALLA,
            "Ninguna aplicación suscrita a esta cuenta",
            "En la consola de Meta: WhatsApp → Configuration → Webhook, "
            "suscribirse al campo «messages». Sin esto, los mensajes de los "
            "pacientes nunca llegan al sistema.",
        )

    nombres = ", ".join(
        a.get("whatsapp_business_api_data", {}).get("name", "—") for a in apps
    )
    return Prueba("Suscripción del webhook", OK, f"Suscrita: {nombres}", datos=datos)


async def _plantillas() -> Prueba:
    """
    Las plantillas son la única forma de escribirle primero al paciente.
    Sin ellas aprobadas no hay recordatorios.
    """
    from app.recordatorios import (
        PLANTILLA_CONFIRMACION,
        PLANTILLA_RECORDATORIO,
        PLANTILLA_REPROGRAMADA,
    )

    necesarias = {
        PLANTILLA_RECORDATORIO, PLANTILLA_CONFIRMACION, PLANTILLA_REPROGRAMADA,
    }

    if not config.wa_business_account_id:
        return Prueba("Plantillas", SIN_DATO, "Falta WA_BUSINESS_ACCOUNT_ID")

    ok, datos = await _consultar(
        f"{config.wa_business_account_id}/message_templates",
        {"fields": "name,status,category,language,rejected_reason", "limit": 100},
    )
    if not ok:
        return Prueba("Plantillas", SIN_DATO, str(datos))

    plantillas = datos.get("data", [])
    por_nombre = {p.get("name"): p for p in plantillas}

    faltantes = sorted(necesarias - set(por_nombre))
    rechazadas = [p for p in plantillas if p.get("status") == "REJECTED"]
    pendientes = [p for p in plantillas if p.get("status") == "PENDING"]

    resumen = {
        "aprobadas": [p["name"] for p in plantillas if p.get("status") == "APPROVED"],
        "pendientes": [p["name"] for p in pendientes],
        "rechazadas": [
            f"{p['name']} ({p.get('rejected_reason', 'sin motivo')})"
            for p in rechazadas
        ],
        "faltantes": faltantes,
    }

    if rechazadas:
        return Prueba(
            "Plantillas", FALLA,
            f"{len(rechazadas)} rechazada(s): "
            + ", ".join(resumen["rechazadas"]),
            "Los motivos habituales son: variable al inicio o al final del "
            "cuerpo, dos variables seguidas, o categoría mal elegida. Se "
            "corrige y se reenvía, sin penalización. Ver "
            "docs/plantillas-whatsapp.md.",
            resumen,
        )
    if faltantes:
        return Prueba(
            "Plantillas", FALLA,
            f"Sin crear: {', '.join(faltantes)}",
            "Sin plantilla aprobada no se pueden enviar recordatorios: el "
            "texto libre solo funciona dentro de las 24 horas posteriores al "
            "mensaje del paciente. Ver docs/plantillas-whatsapp.md.",
            resumen,
        )
    if pendientes:
        return Prueba(
            "Plantillas", AVISO,
            f"{len(pendientes)} en revisión de Meta: "
            + ", ".join(resumen["pendientes"]),
            "Meta suele tardar entre unos minutos y 48 horas.",
            resumen,
        )

    return Prueba(
        "Plantillas", OK,
        f"{len(resumen['aprobadas'])} aprobada(s)",
        datos=resumen,
    )


async def _limite_envio() -> Prueba:
    ok, datos = await _consultar(
        config.wa_business_account_id or config.wa_phone_number_id,
        {"fields": "message_template_namespace,account_review_status"},
    )
    if not ok:
        return Prueba("Estado de la cuenta", SIN_DATO, str(datos))

    revision = datos.get("account_review_status", "")
    if revision and revision.upper() not in ("APPROVED", "VERIFIED"):
        return Prueba(
            "Estado de la cuenta", AVISO,
            f"Revisión de la cuenta: {revision}",
            "Mientras la verificación del negocio no esté aprobada, el "
            "límite de mensajes es reducido.",
            datos,
        )
    return Prueba("Estado de la cuenta", OK, revision or "Sin observaciones", datos=datos)


async def ejecutar() -> list[Prueba]:
    """
    Corre las pruebas en orden de dependencia: si el token no sirve, las
    demás fallarían igual y no aportan información.
    """
    pruebas = [await _variables()]
    if pruebas[0].estado is FALLA and not config.wa_token:
        return pruebas

    token = await _token()
    pruebas.append(token)
    if token.estado == FALLA:
        return pruebas

    pruebas.append(await _numero())
    pruebas.append(await _webhook())
    pruebas.append(await _plantillas())
    pruebas.append(await _limite_envio())
    return pruebas


# ======================================================================
#  Interfaz
# ======================================================================

@router.get("/datos")
async def datos(usuario: Usuario = Depends(usuario_actual)) -> dict:
    solo_admin(usuario)
    pruebas = await ejecutar()
    return {
        "entorno": config.entorno,
        "version_api": config.wa_api_version,
        "pruebas": [
            {
                "nombre": p.nombre,
                "estado": p.estado,
                "detalle": p.detalle,
                "ayuda": p.ayuda,
                "datos": p.datos,
            }
            for p in pruebas
        ],
        "resumen": {
            "ok": sum(1 for p in pruebas if p.estado == OK),
            "aviso": sum(1 for p in pruebas if p.estado == AVISO),
            "falla": sum(1 for p in pruebas if p.estado == FALLA),
        },
    }


@router.get("", response_class=HTMLResponse)
async def pagina() -> HTMLResponse:
    return HTMLResponse(PAGINA)


PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Diagnóstico de Meta · Consultorio Dr. Padilla</title>
<style>
:root{
  --ground:#F1F4F3;--surface:#FFF;--surface-2:#EAEFED;--line:#D8E0DD;
  --ink:#0F1A18;--ink-2:#42534E;--ink-3:#788883;
  --accent:#0B6A5F;--accent-soft:#DFEEEB;
  --critical:#A63A2C;--critical-soft:#F9E8E5;
  --warn:#8E6314;--warn-soft:#F8F0DD;--good:#256B4E;--good-soft:#E0EFE7;
  --sans:ui-sans-serif,"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --mono:ui-monospace,"Cascadia Mono",Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --ground:#0B1113;--surface:#141B1E;--surface-2:#1B2427;--line:#2A3639;
  --ink:#E3EBE8;--ink-2:#A3B2AE;--ink-3:#74837F;
  --accent:#45B5A4;--accent-soft:#14322D;
  --critical:#E58374;--critical-soft:#37201C;
  --warn:#D8A45B;--warn-soft:#332714;--good:#63C096;--good-soft:#173026;
}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit;cursor:pointer}
.wrap{max-width:820px;margin:0 auto;padding:26px 18px 60px}
h1{font-family:var(--serif);font-size:22px;margin:0}
.sub{font-size:13px;color:var(--ink-3);margin-top:3px}
.cab{display:flex;flex-wrap:wrap;align-items:flex-end;gap:14px;margin-bottom:20px}
.cab .sp{margin-left:auto;display:flex;gap:8px}
.btn{font-size:12.5px;font-weight:620;padding:7px 14px;border-radius:6px;
  border:1px solid var(--line);background:var(--surface)}
.btn:hover{border-color:var(--ink-3)}
.btn.p{background:var(--accent);border-color:var(--accent);color:#fff}
@media (prefers-color-scheme:dark){.btn.p{color:#08191A}}

.marcador{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.m{flex:1;min-width:110px;padding:12px 14px;border-radius:9px;background:var(--surface-2);
  border:1px solid var(--line)}
.m .n{font-size:24px;font-weight:640;line-height:1.1;font-variant-numeric:tabular-nums}
.m .l{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3)}
.m.ok{background:var(--good-soft);border-color:transparent}.m.ok .n{color:var(--good)}
.m.aviso{background:var(--warn-soft);border-color:transparent}.m.aviso .n{color:var(--warn)}
.m.falla{background:var(--critical-soft);border-color:transparent}.m.falla .n{color:var(--critical)}

.p{background:var(--surface);border:1px solid var(--line);border-radius:9px;
  padding:14px 16px;margin-bottom:9px;display:grid;grid-template-columns:auto minmax(0,1fr);
  gap:0 13px;align-items:start}
.pt{width:9px;height:9px;border-radius:50%;margin-top:7px;background:var(--ink-3)}
.p.ok .pt{background:var(--good)}
.p.aviso .pt{background:var(--warn)}
.p.falla .pt{background:var(--critical)}
.p.sin_dato .pt{background:var(--ink-3);opacity:.5}
.pn{font-size:14.5px;font-weight:640}
.pd{font-size:13px;color:var(--ink-2);margin-top:2px;word-break:break-word}
.pa{font-size:12.5px;color:var(--ink-2);background:var(--surface-2);border-left:2px solid var(--accent);
  padding:9px 12px;border-radius:0 6px 6px 0;margin-top:9px;line-height:1.5}
.p.falla .pa{border-left-color:var(--critical)}
.p.aviso .pa{border-left-color:var(--warn)}
details{margin-top:8px}
summary{font-size:12px;color:var(--ink-3);cursor:pointer}
pre{font-family:var(--mono);font-size:11.5px;background:var(--surface-2);padding:10px 12px;
  border-radius:6px;overflow-x:auto;margin:7px 0 0;color:var(--ink-2)}
.cargando{text-align:center;color:var(--ink-3);padding:40px;font-size:14px}
.nota{font-size:12.5px;color:var(--ink-3);margin-top:18px;line-height:1.6}
</style>
</head>
<body>
<div class="wrap">
  <div class="cab">
    <div>
      <h1>Diagnóstico de Meta</h1>
      <div class="sub">Consulta el estado de la configuración sin entrar a la consola</div>
    </div>
    <div class="sp">
      <button class="btn p" id="rev" type="button">Revisar de nuevo</button>
      <a class="btn" href="/panel">Volver al panel</a>
    </div>
  </div>

  <div id="marcador"></div>
  <div id="lista"><div class="cargando">Consultando a Meta…</div></div>

  <p class="nota">
    Todo lo que se ve acá sale de la Graph API de Meta, consultada desde el
    servidor con el mismo token que usa el sistema. Es la misma información
    que muestra la consola, y sirve para diagnosticar sin entrar a ella.
  </p>
</div>

<script>
(function(){
"use strict";
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

async function revisar(){
  $("#lista").innerHTML='<div class="cargando">Consultando a Meta…</div>';
  let d;
  try{
    const r=await fetch("/diagnostico/datos",{credentials:"same-origin"});
    if(r.status===401){location.href="/panel";return;}
    if(r.status===403){
      $("#lista").innerHTML='<div class="cargando">Esta sección es solo para el administrador.</div>';
      $("#marcador").innerHTML="";return;
    }
    d=await r.json();
  }catch(e){
    $("#lista").innerHTML='<div class="cargando">No se pudo consultar: '+esc(e.message)+'</div>';
    return;
  }

  $("#marcador").innerHTML=
    '<div class="marcador">'+
    `<div class="m ok"><div class="n">${d.resumen.ok}</div><div class="l">En orden</div></div>`+
    `<div class="m aviso"><div class="n">${d.resumen.aviso}</div><div class="l">Con avisos</div></div>`+
    `<div class="m falla"><div class="n">${d.resumen.falla}</div><div class="l">Con fallas</div></div>`+
    '</div>';

  $("#lista").innerHTML=d.pruebas.map(p=>{
    const tieneDatos=p.datos&&Object.keys(p.datos).length;
    return `<div class="p ${esc(p.estado)}">
      <div class="pt"></div>
      <div>
        <div class="pn">${esc(p.nombre)}</div>
        <div class="pd">${esc(p.detalle)}</div>
        ${p.ayuda?`<div class="pa">${esc(p.ayuda)}</div>`:""}
        ${tieneDatos?`<details><summary>Ver la respuesta de Meta</summary>
          <pre>${esc(JSON.stringify(p.datos,null,2))}</pre></details>`:""}
      </div>
    </div>`;
  }).join("");
}

$("#rev").addEventListener("click",revisar);
revisar();
})();
</script>
</body>
</html>
"""
