"""
Simulador de WhatsApp para desarrollo.

Permite conversar con el asistente sin tener nada configurado en Meta: los
mensajes entran por el mismo circuito que los reales —barrera clínica,
clasificación, escalado, flujos, agenda— y las respuestas se leen de la base
de datos, que es donde el sistema las guarda.

Sirve para probar el asistente completo antes de tocar Meta, y para ver el
panel actualizarse en vivo mientras se conversa.

**Solo disponible fuera de producción.** El router lo desactiva cuando
ENTORNO=produccion.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import select

from app.config import config
from app.db import sesion
from app.models import Conversacion, Mensaje, Paciente, Remitente
from app.tiempo import hora
from app.whatsapp.parser import MensajeEntrante

log = logging.getLogger(__name__)

router = APIRouter(prefix="/simulador", tags=["desarrollo"])


def _solo_desarrollo() -> None:
    if config.entorno == "produccion":
        raise HTTPException(status_code=404, detail="No disponible")


@router.post("/mensaje")
async def enviar(
    telefono: str = Body(..., embed=True),
    texto: str = Body(default="", embed=True),
    nombre: str = Body(default="Paciente de prueba", embed=True),
    adjunto: str = Body(default="", embed=True),
    boton: str = Body(default="", embed=True),
) -> dict:
    """Mete un mensaje por el circuito real y devuelve lo que respondió."""
    _solo_desarrollo()

    from app.brain.router import procesar_mensaje

    ultimo = _ultimo_id(telefono)

    await procesar_mensaje(MensajeEntrante(
        wa_message_id=f"sim.{uuid.uuid4().hex[:12]}",
        telefono=telefono,
        nombre_perfil=nombre,
        texto=texto,
        tipo="button" if boton else ("image" if adjunto else "text"),
        tipo_adjunto=adjunto,
        respuesta_id=boton,
    ))

    return {"mensajes": _nuevos(telefono, ultimo), "estado": _estado(telefono)}


@router.get("/historial")
async def historial(telefono: str) -> dict:
    _solo_desarrollo()
    return {"mensajes": _nuevos(telefono, 0), "estado": _estado(telefono)}


@router.post("/reiniciar")
async def reiniciar(telefono: str = Body(..., embed=True)) -> dict:
    """Borra el paciente de prueba y todo su historial."""
    _solo_desarrollo()
    from app.models import Cita

    with sesion() as s:
        paciente = s.exec(
            select(Paciente).where(Paciente.telefono == telefono)
        ).first()
        if not paciente:
            return {"ok": True}

        convs = list(s.exec(
            select(Conversacion).where(Conversacion.paciente_id == paciente.id)
        ).all())
        for c in convs:
            for m in s.exec(
                select(Mensaje).where(Mensaje.conversacion_id == c.id)
            ).all():
                s.delete(m)
            s.delete(c)
        for cita in s.exec(select(Cita).where(Cita.paciente_id == paciente.id)).all():
            s.delete(cita)
        s.delete(paciente)
        s.commit()
    return {"ok": True}


# ----------------------------------------------------------------------


def _conversacion(telefono: str) -> Conversacion | None:
    with sesion() as s:
        paciente = s.exec(
            select(Paciente).where(Paciente.telefono == telefono)
        ).first()
        if not paciente:
            return None
        return s.exec(
            select(Conversacion)
            .where(Conversacion.paciente_id == paciente.id)
            .order_by(Conversacion.id.desc())  # type: ignore[attr-defined]
        ).first()


def _ultimo_id(telefono: str) -> int:
    c = _conversacion(telefono)
    if not c:
        return 0
    with sesion() as s:
        m = s.exec(
            select(Mensaje)
            .where(Mensaje.conversacion_id == c.id)
            .order_by(Mensaje.id.desc())  # type: ignore[attr-defined]
        ).first()
    return m.id if m else 0


def _nuevos(telefono: str, desde_id: int) -> list[dict]:
    c = _conversacion(telefono)
    if not c:
        return []
    with sesion() as s:
        mensajes = list(s.exec(
            select(Mensaje)
            .where(Mensaje.conversacion_id == c.id, Mensaje.id > desde_id)
            .order_by(Mensaje.id)  # type: ignore[arg-type]
        ).all())
    return [
        {
            "quien": m.remitente.value,
            "texto": m.texto,
            "hora": hora(m.enviado_en),
            "ia": m.generado_por_ia,
            "adjunto": m.tipo_adjunto,
        }
        for m in mensajes
    ]


def _estado(telefono: str) -> dict:
    c = _conversacion(telefono)
    if not c:
        return {}
    return {
        "estado": c.estado.value,
        "motivo": c.motivo_escalado.value if c.motivo_escalado else "",
        "intencion": c.intencion.value,
        "paso": c.paso,
        "intentos_fallidos": c.intentos_fallidos,
        "conversacion_id": c.id,
    }


# ======================================================================
#  Interfaz
# ======================================================================

@router.get("", response_class=HTMLResponse)
async def pagina() -> HTMLResponse:
    _solo_desarrollo()
    return HTMLResponse(PAGINA)


PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulador · Asistente Dr. Padilla</title>
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
button,input{font:inherit;color:inherit}button{cursor:pointer}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 40px;
  display:grid;grid-template-columns:minmax(0,360px) minmax(0,1fr);gap:20px;align-items:start}
@media (max-width:820px){.wrap{grid-template-columns:minmax(0,1fr)}}

.cab{grid-column:1/-1;display:flex;flex-wrap:wrap;align-items:center;gap:12px;
  padding:12px 16px;background:var(--surface);border:1px solid var(--line);
  border-radius:10px;margin-bottom:2px}
.cab h1{margin:0;font-family:var(--serif);font-size:17px}
.cab .tag{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  color:var(--accent);background:var(--accent-soft);padding:4px 9px;border-radius:5px}
.cab .sp{margin-left:auto;display:flex;gap:8px;align-items:center}
.btn{font-size:12.5px;font-weight:600;padding:6px 12px;border-radius:6px;
  border:1px solid var(--line);background:var(--surface)}
.btn:hover{border-color:var(--ink-3)}
.btn.p{background:var(--accent);border-color:var(--accent);color:#fff}
:root[data-theme=dark] .btn.p,@media (prefers-color-scheme:dark){.btn.p{color:#08191A}}

/* teléfono */
.tel{background:var(--surface);border:1px solid var(--line);border-radius:22px;
  padding:8px;box-shadow:0 10px 30px -18px rgba(0,0,0,.4)}
.pant{border-radius:16px;overflow:hidden;border:1px solid var(--line);
  background:var(--ground);display:flex;flex-direction:column;height:min(70vh,620px)}
.tel-cab{display:flex;align-items:center;gap:10px;padding:10px 13px;
  background:var(--surface);border-bottom:1px solid var(--line)}
.av{width:32px;height:32px;border-radius:50%;background:var(--accent);color:#fff;
  display:grid;place-items:center;font-family:var(--serif);font-size:15px;flex:none}
.tel-n{font-size:14px;font-weight:620;line-height:1.2}
.tel-s{font-size:11px;color:var(--ink-3)}
.chat{flex:1;overflow-y:auto;padding:14px 12px;display:flex;flex-direction:column;gap:8px}
.m{max-width:82%}
.m .b{padding:8px 11px;border-radius:11px;font-size:13.5px;line-height:1.45;
  white-space:pre-wrap;word-break:break-word}
.m .t{font-size:10px;color:var(--ink-3);margin-top:3px}
.m.paciente{align-self:flex-end}
.m.paciente .b{background:var(--accent-soft);border-bottom-right-radius:3px}
.m.paciente .t{text-align:right}
.m.bot{align-self:flex-start}
.m.bot .b{background:var(--surface);border:1px solid var(--line);border-bottom-left-radius:3px}
.m.humano{align-self:flex-start}
.m.humano .b{background:var(--warn-soft);border-bottom-left-radius:3px}
.m.sistema{align-self:center;max-width:92%;text-align:center}
.m.sistema .b{background:var(--warn-soft);color:var(--warn);font-size:11.5px;
  border-radius:20px;padding:5px 12px}
.vacio{color:var(--ink-3);font-size:13px;text-align:center;padding:24px 12px}
.esc{padding:9px 12px;display:flex;gap:8px;background:var(--surface);border-top:1px solid var(--line)}
.esc input{flex:1;min-width:0;padding:9px 12px;border:1px solid var(--line);
  border-radius:20px;background:var(--surface-2)}

/* panel lateral */
.lat{display:flex;flex-direction:column;gap:14px}
.tar{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px 16px}
.tar h2{margin:0 0 10px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-2)}
.est{display:flex;flex-wrap:wrap;gap:7px}
.chip{font-size:11px;font-weight:650;padding:4px 9px;border-radius:5px;
  background:var(--surface-2);color:var(--ink-2)}
.chip.critical{background:var(--critical-soft);color:var(--critical)}
.chip.warn{background:var(--warn-soft);color:var(--warn)}
.chip.good{background:var(--good-soft);color:var(--good)}
.chip.accent{background:var(--accent-soft);color:var(--accent)}
.pruebas{display:flex;flex-direction:column;gap:5px}
.pr{text-align:left;width:100%;padding:8px 11px;border:1px solid var(--line);
  border-radius:7px;background:var(--surface-2);font-size:12.5px;line-height:1.35}
.pr:hover{border-color:var(--accent);color:var(--accent)}
.pr b{display:block;font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ink-3);margin-bottom:2px;font-weight:700}
.pr.rojo b{color:var(--critical)}
.nota{font-size:11.5px;color:var(--ink-3);line-height:1.5;margin-top:10px}
.tel-num{font-family:var(--mono);font-size:12px;color:var(--ink-3)}
</style>
</head>
<body>
<div class="wrap">

  <div class="cab">
    <span class="tag">Simulador</span>
    <h1>Asistente · Consultorio Dr. Padilla</h1>
    <div class="sp">
      <span class="tel-num" id="num"></span>
      <button class="btn" id="reset" type="button">Empezar de nuevo</button>
      <a class="btn p" href="/panel" target="_blank" rel="noopener">Abrir el panel</a>
    </div>
  </div>

  <div class="tel">
    <div class="pant">
      <div class="tel-cab">
        <div class="av">P</div>
        <div>
          <div class="tel-n">Dr. José G. Padilla</div>
          <div class="tel-s">Consultorio · en línea</div>
        </div>
      </div>
      <div class="chat" id="chat">
        <div class="vacio">Escriba un mensaje, o use una prueba rápida de la derecha.</div>
      </div>
      <form class="esc" id="form">
        <input id="txt" placeholder="Escriba un mensaje…" autocomplete="off">
        <button class="btn p" type="submit">Enviar</button>
      </form>
    </div>
  </div>

  <div class="lat">
    <div class="tar">
      <h2>Estado de la conversación</h2>
      <div class="est" id="estado"><span class="chip">Sin empezar</span></div>
      <p class="nota" id="nota">
        Todo lo que escriba pasa por el circuito real: barrera clínica,
        clasificación, escalado y agenda. Abra el panel en otra pestaña para
        verlo actualizarse en vivo.
      </p>
    </div>

    <div class="tar">
      <h2>Pruebas rápidas</h2>
      <div class="pruebas" id="pruebas"></div>
    </div>
  </div>

</div>

<script>
(function(){
"use strict";
const $=s=>document.querySelector(s);
const TEL="52133"+Math.random().toString().slice(2,9);
$("#num").textContent="+"+TEL;

const PRUEBAS=[
 ["Saludo","Hola, buenos días"],
 ["Costos","¿Cuánto cuesta la consulta?"],
 ["Ubicación","¿Dónde están ubicados?"],
 ["Horarios","¿Qué horarios manejan?"],
 ["Agendar","Quiero agendar una cita"],
 ["Urgencia","Tengo un dolor muy fuerte del lado derecho y fiebre alta",1],
 ["Contenido clínico","¿Es normal que la herida se vea rosada?",1],
 ["Medicamento","¿Qué me puedo tomar para el dolor?",1],
 ["Pide al doctor","Quiero hablar con el doctor Padilla",1],
 ["Paciente molesto","Ya van tres veces que me cambian la cita, no me parece",1],
 ["Facturación","Necesito una factura"],
 ["No se entiende","zzz qqq xyz"],
];

$("#pruebas").innerHTML=PRUEBAS.map(([t,m,rojo],i)=>
  `<button class="pr${rojo?" rojo":""}" data-i="${i}" type="button"><b>${t}</b>${m}</button>`
).join("");
$("#pruebas").querySelectorAll(".pr").forEach(b=>{
  b.addEventListener("click",()=>enviar(PRUEBAS[+b.dataset.i][1]));
});

const ETIQ={
 posible_urgencia:["critical","Posible urgencia"],
 contenido_clinico:["critical","Contenido clínico"],
 pidio_doctor:["warn","Pidió al doctor"],
 molestia:["warn","Paciente molesto"],
 no_comprendido:["warn","No comprendido"],
 estancada:["warn","Estancada"],
 facturacion:["","Facturación"],
};
const EST={bot:["accent","El asistente responde"],atencion:["critical","Requiere una persona"],
 humano:["warn","La lleva una persona"],resuelta:["good","Resuelta"]};

let vacio=true;
function pintar(msgs){
  if(vacio&&msgs.length){$("#chat").innerHTML="";vacio=false;}
  for(const m of msgs){
    const d=document.createElement("div");
    d.className="m "+m.quien;
    const cuerpo=document.createElement("div");
    cuerpo.className="b";cuerpo.textContent=m.texto;
    d.appendChild(cuerpo);
    if(m.quien!=="sistema"){
      const t=document.createElement("div");
      t.className="t";t.textContent=m.hora+(m.ia?" · IA":"");
      d.appendChild(t);
    }
    $("#chat").appendChild(d);
  }
  $("#chat").scrollTop=$("#chat").scrollHeight;
}

function pintarEstado(e){
  if(!e||!e.estado){$("#estado").innerHTML='<span class="chip">Sin empezar</span>';return;}
  const chips=[];
  const est=EST[e.estado]||["","—"];
  chips.push(`<span class="chip ${est[0]}">${est[1]}</span>`);
  if(e.motivo){const x=ETIQ[e.motivo]||["","—"];chips.push(`<span class="chip ${x[0]}">${x[1]}</span>`);}
  if(e.intencion&&e.intencion!=="desconocida")chips.push(`<span class="chip">${e.intencion}</span>`);
  if(e.paso)chips.push(`<span class="chip">${e.paso}</span>`);
  if(e.intentos_fallidos)chips.push(`<span class="chip warn">${e.intentos_fallidos} sin entender</span>`);
  $("#estado").innerHTML=chips.join("");
}

async function enviar(texto){
  if(!texto.trim())return;
  pintar([{quien:"paciente",texto,hora:""}]);
  $("#txt").value="";
  try{
    const r=await fetch("/simulador/mensaje",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({telefono:TEL,texto})});
    const d=await r.json();
    pintar((d.mensajes||[]).filter(m=>m.quien!=="paciente"));
    pintarEstado(d.estado);
  }catch(e){
    pintar([{quien:"sistema",texto:"No se pudo enviar: "+e.message,hora:""}]);
  }
}

$("#form").addEventListener("submit",e=>{e.preventDefault();enviar($("#txt").value);});
$("#reset").addEventListener("click",async()=>{
  await fetch("/simulador/reiniciar",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify({telefono:TEL})});
  location.reload();
});
})();
</script>
</body>
</html>
"""
