"""
Edición del contenido del consultorio y gestión de la agenda.

Todo esto se edita desde el panel, sin depender del desarrollador: precios,
horarios, direcciones, franjas reservadas y respuestas frecuentes. Era una
de las promesas del proyecto y es lo que evita tener que pedir un cambio de
código cada vez que sube el precio de la consulta.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import select

from app.db import sesion
from app.models import (
    Cita,
    Intencion,
    Paciente,
    RegistroAuditoria,
    RespuestaFrecuente,
    Sede,
    Usuario,
)
from app.panel.auth import solo_admin, usuario_actual
from app.tiempo import a_local, fecha_corta, hace, hora

log = logging.getLogger(__name__)

router = APIRouter(prefix="/panel/api", tags=["panel"])


def _auditar(usuario: Usuario, accion: str, detalle: str = "", entidad_id: int | None = None) -> None:
    with sesion() as s:
        s.add(RegistroAuditoria(
            usuario_id=usuario.id,
            actor=usuario.correo,
            accion=accion,
            entidad_id=entidad_id,
            detalle=detalle,
        ))
        s.commit()


# ======================================================================
#  Sedes
# ======================================================================

CAMPOS_EDITABLES = {
    "nombre", "direccion", "referencias", "mapa_url", "telefono",
    "precio_valoracion", "convenios", "horarios", "horario_json",
    "franjas_json", "duracion_cita_min", "activa", "orden",
}


def validar_bloques(crudo) -> str:
    """
    Comprueba el formato de horarios y franjas antes de guardarlos.

    Formato: [{"dia": 0-6, "desde": "HH:MM", "hasta": "HH:MM"}]

    Si se guardara algo inválido, el asistente dejaría de ofrecer turnos y
    nadie entendería por qué. Devuelve "" si está bien.
    """
    if isinstance(crudo, list):
        bloques = crudo
    else:
        try:
            bloques = json.loads(crudo or "[]")
        except (json.JSONDecodeError, TypeError):
            return "no tiene un formato válido"

    if not isinstance(bloques, list):
        return "debe ser una lista de bloques"

    for i, b in enumerate(bloques, start=1):
        if not isinstance(b, dict):
            return f"el bloque {i} no es válido"
        dia = b.get("dia")
        if not isinstance(dia, int) or not 0 <= dia <= 6:
            return f"el bloque {i} tiene un día inválido (0 = lunes, 6 = domingo)"
        try:
            desde = time.fromisoformat(b["desde"])
            hasta = time.fromisoformat(b["hasta"])
        except (KeyError, ValueError, TypeError):
            return f"el bloque {i} tiene una hora inválida (formato HH:MM)"
        if desde >= hasta:
            return f"el bloque {i} termina antes de empezar"

    return ""


@router.get("/sedes")
async def listar_sedes(usuario: Usuario = Depends(usuario_actual)) -> list[dict]:
    with sesion() as s:
        sedes = list(s.exec(select(Sede).order_by(Sede.orden)).all())  # type: ignore[arg-type]

    return [
        {
            "id": x.id,
            "nombre": x.nombre,
            "direccion": x.direccion,
            "referencias": x.referencias,
            "mapa_url": x.mapa_url,
            "telefono": x.telefono,
            "precio_valoracion": x.precio_valoracion,
            "convenios": x.convenios,
            "horarios": x.horarios,
            "horario": _leer(x.horario_json),
            "franjas": _leer(x.franjas_json),
            "duracion_cita_min": x.duracion_cita_min,
            "activa": x.activa,
            "orden": x.orden,
            "completa": bool(
                x.direccion
                and not x.direccion.startswith("(")
                and x.precio_valoracion
                and _leer(x.horario_json)
            ),
        }
        for x in sedes
    ]


def _leer(crudo: str) -> list[dict]:
    try:
        datos = json.loads(crudo or "[]")
        return datos if isinstance(datos, list) else []
    except json.JSONDecodeError:
        return []


@router.put("/sedes/{sede_id}")
async def editar_sede(
    sede_id: int,
    datos: dict = Body(...),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    solo_admin(usuario)

    for campo in ("horario_json", "franjas_json"):
        if campo in datos:
            error = validar_bloques(datos[campo])
            if error:
                nombre = "El horario" if campo == "horario_json" else "Las franjas"
                raise HTTPException(status_code=400, detail=f"{nombre}: {error}")
            if isinstance(datos[campo], list):
                datos[campo] = json.dumps(datos[campo])

    with sesion() as s:
        sede = s.get(Sede, sede_id)
        if not sede:
            raise HTTPException(status_code=404, detail="Sede inexistente")

        cambios = []
        for clave, valor in datos.items():
            if clave not in CAMPOS_EDITABLES:
                continue
            if getattr(sede, clave) != valor:
                cambios.append(clave)
                setattr(sede, clave, valor)

        s.add(sede)
        s.commit()
        nombre = sede.nombre

    if cambios:
        _auditar(
            usuario, "sede.editada",
            detalle=f"{nombre}: {', '.join(cambios)}",
            entidad_id=sede_id,
        )
    return {"id": sede_id, "cambios": cambios}


# ======================================================================
#  Respuestas frecuentes
# ======================================================================

@router.get("/respuestas")
async def listar_respuestas(usuario: Usuario = Depends(usuario_actual)) -> list[dict]:
    with sesion() as s:
        listado = list(s.exec(select(RespuestaFrecuente)).all())
        sedes = {x.id: x.nombre for x in s.exec(select(Sede)).all()}

    return [
        {
            "id": r.id,
            "intencion": r.intencion.value,
            "disparadores": r.disparadores,
            "respuesta": r.respuesta,
            "sede": sedes.get(r.sede_id or 0, ""),
            "sede_id": r.sede_id,
            "activa": r.activa,
        }
        for r in listado
    ]


@router.post("/respuestas")
async def crear_respuesta(
    datos: dict = Body(...),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    solo_admin(usuario)

    texto = (datos.get("respuesta") or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="La respuesta está vacía")

    try:
        intencion = Intencion(datos.get("intencion") or "informacion")
    except ValueError:
        raise HTTPException(status_code=400, detail="Intención desconocida")

    with sesion() as s:
        r = RespuestaFrecuente(
            intencion=intencion,
            disparadores=(datos.get("disparadores") or "").strip(),
            respuesta=texto,
            sede_id=datos.get("sede_id"),
            activa=bool(datos.get("activa", True)),
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        nuevo = r.id

    _auditar(usuario, "respuesta.creada", detalle=texto[:100], entidad_id=nuevo)
    return {"id": nuevo}


@router.put("/respuestas/{respuesta_id}")
async def editar_respuesta(
    respuesta_id: int,
    datos: dict = Body(...),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    solo_admin(usuario)

    with sesion() as s:
        r = s.get(RespuestaFrecuente, respuesta_id)
        if not r:
            raise HTTPException(status_code=404, detail="Respuesta inexistente")
        if "respuesta" in datos:
            nuevo = (datos["respuesta"] or "").strip()
            if not nuevo:
                raise HTTPException(status_code=400, detail="La respuesta está vacía")
            r.respuesta = nuevo
        if "disparadores" in datos:
            r.disparadores = (datos["disparadores"] or "").strip()
        if "activa" in datos:
            r.activa = bool(datos["activa"])
        s.add(r)
        s.commit()

    _auditar(usuario, "respuesta.editada", entidad_id=respuesta_id)
    return {"id": respuesta_id}


@router.delete("/respuestas/{respuesta_id}")
async def borrar_respuesta(
    respuesta_id: int, usuario: Usuario = Depends(usuario_actual)
) -> dict:
    solo_admin(usuario)

    with sesion() as s:
        r = s.get(RespuestaFrecuente, respuesta_id)
        if not r:
            raise HTTPException(status_code=404, detail="Respuesta inexistente")
        detalle = r.respuesta[:80]
        s.delete(r)
        s.commit()

    _auditar(usuario, "respuesta.borrada", detalle=detalle, entidad_id=respuesta_id)
    return {"ok": True}


# ======================================================================
#  Agenda
# ======================================================================

@router.get("/citas")
async def listar_citas(
    desde_dias: int = -7,
    hasta_dias: int = 30,
    usuario: Usuario = Depends(usuario_actual),
) -> list[dict]:
    desde = datetime.utcnow() + timedelta(days=desde_dias)
    hasta = datetime.utcnow() + timedelta(days=hasta_dias)

    with sesion() as s:
        citas = list(s.exec(
            select(Cita)
            .where(Cita.inicio >= desde, Cita.inicio <= hasta)
            .order_by(Cita.inicio)  # type: ignore[arg-type]
            .limit(300)
        ).all())
        pacientes = {p.id: p for p in s.exec(select(Paciente)).all()}
        sedes = {x.id: x.nombre for x in s.exec(select(Sede)).all()}

    salida = []
    for c in citas:
        p = pacientes.get(c.paciente_id)
        salida.append({
            "id": c.id,
            "paciente": (p.nombre or p.telefono) if p else "—",
            "telefono": p.telefono if p else "",
            "whatsapp_url": f"https://wa.me/{p.telefono}" if p else "",
            "cuando": fecha_corta(c.inicio),
            "hora": hora(c.inicio),
            "fecha": f"{a_local(c.inicio):%d/%m}",
            "sede": sedes.get(c.sede_id, ""),
            "tipo": c.tipo,
            "estado": c.estado.value,
            "cargada": c.cargada_en_doctoralia,
            "recordada": c.recordatorio_enviado_en is not None,
            "creada_hace": hace(c.creada_en),
            "pasada": c.inicio < datetime.utcnow(),
        })
    return salida


@router.post("/citas/{cita_id}/cancelar")
async def cancelar_cita(
    cita_id: int, usuario: Usuario = Depends(usuario_actual)
) -> dict:
    from app.agenda.service import cancelar

    if not await cancelar(cita_id, por=usuario.correo):
        raise HTTPException(status_code=404, detail="Cita inexistente")
    _auditar(usuario, "cita.cancelada.panel", entidad_id=cita_id)
    return {"ok": True}


# ======================================================================
#  Contraseña
# ======================================================================

@router.post("/cambiar-clave")
async def cambiar_clave(
    actual: str = Body(..., embed=True),
    nueva: str = Body(..., embed=True),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    """
    Las contraseñas que crea el `seed` son provisionales y están en el
    repositorio. Hay que poder cambiarlas sin tocar la base a mano.
    """
    from app.security import cifrar_clave, clave_correcta

    if not clave_correcta(actual, usuario.hash_clave):
        raise HTTPException(
            status_code=401, detail="La contraseña actual no es correcta"
        )
    if len(nueva) < 10:
        raise HTTPException(
            status_code=400,
            detail="La nueva contraseña debe tener al menos 10 caracteres",
        )
    if nueva == actual:
        raise HTTPException(
            status_code=400, detail="La nueva contraseña es igual a la anterior"
        )

    with sesion() as s:
        u = s.get(Usuario, usuario.id)
        u.hash_clave = cifrar_clave(nueva)
        s.add(u)
        s.commit()

    _auditar(usuario, "clave.cambiada")
    return {"ok": True}
