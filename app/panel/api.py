"""
API del panel.

Todo lo que ve y hace el consultorio pasa por aquí. Cada acción que
modifica algo deja registro de auditoría con el usuario que la hizo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlmodel import func, select

from app.config import config
from app.db import sesion
from app.models import (
    Ajuste,
    Cita,
    Conversacion,
    EstadoCita,
    EstadoConversacion,
    Mensaje,
    ModoAsistente,
    Paciente,
    RegistroAuditoria,
    Remitente,
    RolUsuario,
    Sede,
    Usuario,
)
from app.panel.auth import (
    autenticar,
    cerrar_sesion,
    crear_sesion,
    solo_admin,
    usuario_actual,
)

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


def _hace(dt: datetime | None) -> str:
    if not dt:
        return ""
    seg = (datetime.utcnow() - dt).total_seconds()
    if seg < 60:
        return f"{int(seg)} s"
    if seg < 3600:
        return f"{int(seg // 60)} min"
    if seg < 86400:
        return f"{int(seg // 3600)} h"
    return f"{int(seg // 86400)} d"


# ======================================================================
#  Sesión
# ======================================================================

@router.post("/login")
async def login(
    respuesta: Response,
    correo: str = Body(..., embed=True),
    clave: str = Body(..., embed=True),
) -> dict:
    usuario = autenticar(correo, clave)
    if not usuario:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    crear_sesion(respuesta, usuario)
    _auditar(usuario, "sesion.inicio")
    return {"nombre": usuario.nombre, "rol": usuario.rol.value}


@router.post("/logout")
async def logout(respuesta: Response, usuario: Usuario = Depends(usuario_actual)) -> dict:
    cerrar_sesion(respuesta)
    _auditar(usuario, "sesion.cierre")
    return {"ok": True}


@router.get("/yo")
async def yo(usuario: Usuario = Depends(usuario_actual)) -> dict:
    return {
        "id": usuario.id,
        "nombre": usuario.nombre,
        "correo": usuario.correo,
        "rol": usuario.rol.value,
        "iniciales": "".join(p[0] for p in usuario.nombre.split()[:2]).upper(),
    }


# ======================================================================
#  Resumen del día
# ======================================================================

@router.get("/resumen")
async def resumen(usuario: Usuario = Depends(usuario_actual)) -> dict:
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ayer = hoy - timedelta(days=1)

    with sesion() as s:
        atencion = list(s.exec(
            select(Conversacion).where(
                Conversacion.estado == EstadoConversacion.REQUIERE_ATENCION
            )
        ).all())

        hoy_convs = list(s.exec(
            select(Conversacion).where(Conversacion.abierta_en >= hoy)
        ).all())
        ayer_convs = s.exec(
            select(func.count(Conversacion.id)).where(  # type: ignore[arg-type]
                Conversacion.abierta_en >= ayer, Conversacion.abierta_en < hoy
            )
        ).one()

        citas_hoy = list(s.exec(
            select(Cita).where(
                Cita.creada_en >= hoy,
                Cita.estado != EstadoCita.CANCELADA,
            )
        ).all())

        proximas = list(s.exec(
            select(Cita)
            .where(
                Cita.inicio >= datetime.utcnow(),
                Cita.inicio < datetime.utcnow() + timedelta(days=2),
                Cita.estado != EstadoCita.CANCELADA,
            )
            .order_by(Cita.inicio)  # type: ignore[arg-type]
            .limit(6)
        ).all())

        sedes = {x.id: x.nombre for x in s.exec(select(Sede)).all()}
        pacientes = {
            p.id: p for p in s.exec(select(Paciente)).all()
        }

        # tiempo de respuesta: primer mensaje del bot tras uno del paciente
        tiempos: list[float] = []
        for c in hoy_convs:
            msgs = list(s.exec(
                select(Mensaje)
                .where(Mensaje.conversacion_id == c.id)
                .order_by(Mensaje.id)  # type: ignore[arg-type]
            ).all())
            for a, b in zip(msgs, msgs[1:]):
                if a.remitente is Remitente.PACIENTE and b.remitente is Remitente.BOT:
                    tiempos.append((b.enviado_en - a.enviado_en).total_seconds())

        fuentes: dict[str, int] = {}
        for p in pacientes.values():
            if p.fuente:
                fuentes[p.fuente] = fuentes.get(p.fuente, 0) + 1

        perdidas: dict[str, int] = {}
        for c in s.exec(select(Conversacion).where(Conversacion.motivo_perdida != "")).all():
            perdidas[c.motivo_perdida] = perdidas.get(c.motivo_perdida, 0) + 1

        # serie de los últimos 7 días
        serie = []
        for i in range(6, -1, -1):
            d0 = hoy - timedelta(days=i)
            d1 = d0 + timedelta(days=1)
            serie.append({
                "dia": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][d0.weekday()],
                "conversaciones": s.exec(
                    select(func.count(Conversacion.id)).where(  # type: ignore[arg-type]
                        Conversacion.abierta_en >= d0, Conversacion.abierta_en < d1
                    )
                ).one(),
                "citas": s.exec(
                    select(func.count(Cita.id)).where(  # type: ignore[arg-type]
                        Cita.creada_en >= d0, Cita.creada_en < d1
                    )
                ).one(),
            })

    convertidas = sum(1 for c in hoy_convs if c.convirtio)
    urgencias = sum(
        1 for c in hoy_convs
        if c.motivo_escalado and c.motivo_escalado.value == "posible_urgencia"
    )
    sin_intervencion = sum(
        1 for c in hoy_convs if c.estado is EstadoConversacion.BOT
    )

    return {
        "requieren_atencion": len(atencion),
        "mas_antigua": _hace(min((c.ultima_actividad for c in atencion), default=None)),
        "conversaciones_hoy": len(hoy_convs),
        "conversaciones_ayer": int(ayer_convs or 0),
        "citas_hoy": len(citas_hoy),
        "conversion": round(100 * convertidas / len(hoy_convs)) if hoy_convs else 0,
        "respuesta_promedio_s": round(sum(tiempos) / len(tiempos), 1) if tiempos else 0.0,
        "sin_intervencion": round(100 * sin_intervencion / len(hoy_convs)) if hoy_convs else 0,
        "urgencias": urgencias,
        "serie": serie,
        "fuentes": sorted(
            [{"nombre": k, "total": v} for k, v in fuentes.items()],
            key=lambda x: -x["total"],
        ),
        "perdidas": sorted(
            [{"motivo": k, "total": v} for k, v in perdidas.items()],
            key=lambda x: -x["total"],
        ),
        "proximas_citas": [
            {
                "id": c.id,
                "hora": c.inicio.strftime("%H:%M"),
                "fecha": c.inicio.strftime("%d/%m"),
                "paciente": pacientes[c.paciente_id].nombre or pacientes[c.paciente_id].telefono
                if c.paciente_id in pacientes else "",
                "telefono": pacientes[c.paciente_id].telefono if c.paciente_id in pacientes else "",
                "sede": sedes.get(c.sede_id, ""),
                "tipo": c.tipo,
                "estado": c.estado.value,
            }
            for c in proximas
        ],
    }


# ======================================================================
#  Conversaciones
# ======================================================================

@router.get("/conversaciones")
async def listar(
    filtro: str = "todas",
    usuario: Usuario = Depends(usuario_actual),
) -> list[dict]:
    with sesion() as s:
        consulta = select(Conversacion).order_by(
            Conversacion.ultima_actividad.desc()  # type: ignore[attr-defined]
        )
        if filtro == "atencion":
            consulta = consulta.where(
                Conversacion.estado == EstadoConversacion.REQUIERE_ATENCION
            )
        elif filtro == "bot":
            consulta = consulta.where(
                Conversacion.estado.in_([  # type: ignore[attr-defined]
                    EstadoConversacion.BOT, EstadoConversacion.RESUELTA
                ])
            )
        elif filtro == "humano":
            consulta = consulta.where(
                Conversacion.estado == EstadoConversacion.HUMANO
            )

        convs = list(s.exec(consulta.limit(80)).all())
        pacientes = {p.id: p for p in s.exec(select(Paciente)).all()}
        sedes = {x.id: x.nombre for x in s.exec(select(Sede)).all()}

        salida = []
        for c in convs:
            p = pacientes.get(c.paciente_id)
            ultimo = s.exec(
                select(Mensaje)
                .where(Mensaje.conversacion_id == c.id)
                .order_by(Mensaje.id.desc())  # type: ignore[attr-defined]
            ).first()
            salida.append({
                "id": c.id,
                "nombre": (p.nombre if p and p.nombre else (p.telefono if p else "—")),
                "telefono": p.telefono if p else "",
                "estado": c.estado.value,
                "motivo": c.motivo_escalado.value if c.motivo_escalado else "",
                "intencion": c.intencion.value,
                "sede": sedes.get(c.sede_id or 0, ""),
                "ultimo": (ultimo.texto[:90] if ultimo else ""),
                "hace": _hace(c.ultima_actividad),
                "convirtio": c.convirtio,
            })
        return salida


@router.get("/conversaciones/{conversacion_id}")
async def detalle(
    conversacion_id: int, usuario: Usuario = Depends(usuario_actual)
) -> dict:
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if not c:
            raise HTTPException(status_code=404, detail="Conversación inexistente")

        p = s.get(Paciente, c.paciente_id)
        sede = s.get(Sede, c.sede_id) if c.sede_id else None
        sede_pref = s.get(Sede, p.sede_preferida_id) if p and p.sede_preferida_id else None

        mensajes = list(s.exec(
            select(Mensaje)
            .where(Mensaje.conversacion_id == conversacion_id)
            .order_by(Mensaje.id)  # type: ignore[arg-type]
        ).all())

        citas = list(s.exec(
            select(Cita)
            .where(Cita.paciente_id == c.paciente_id)
            .order_by(Cita.inicio.desc())  # type: ignore[attr-defined]
            .limit(8)
        ).all()) if p else []

        sedes = {x.id: x.nombre for x in s.exec(select(Sede)).all()}
        tomada_por = s.get(Usuario, c.tomada_por_id) if c.tomada_por_id else None

    return {
        "id": c.id,
        "estado": c.estado.value,
        "motivo": c.motivo_escalado.value if c.motivo_escalado else "",
        "intencion": c.intencion.value,
        "tomada_por": tomada_por.nombre if tomada_por else "",
        "sede": sede.nombre if sede else "",
        # --- información de contacto del paciente ---
        "paciente": {
            "id": p.id if p else None,
            "nombre": (p.nombre or "Sin nombre registrado") if p else "—",
            "telefono": p.telefono if p else "",
            "whatsapp_url": f"https://wa.me/{p.telefono}" if p else "",
            "ciudad": (p.ciudad or "—") if p else "—",
            "fuente": (p.fuente or "—") if p else "—",
            "motivo_consulta": (p.motivo_consulta or "—") if p else "—",
            "sede_preferida": sede_pref.nombre if sede_pref else "—",
            "es_conocido": bool(p and p.nombre),
            "alta": p.creado_en.strftime("%d/%m/%Y") if p else "",
            "ultima_interaccion": _hace(p.ultima_interaccion) if p else "",
        },
        "mensajes": [
            {
                "quien": m.remitente.value,
                "texto": m.texto,
                "hora": m.enviado_en.strftime("%H:%M"),
                "fecha": m.enviado_en.strftime("%d/%m"),
                "adjunto": m.tipo_adjunto,
                "ia": m.generado_por_ia,
            }
            for m in mensajes
        ],
        "citas": [
            {
                "cuando": c2.inicio.strftime("%d/%m/%Y %H:%M"),
                "sede": sedes.get(c2.sede_id, ""),
                "tipo": c2.tipo,
                "estado": c2.estado.value,
            }
            for c2 in citas
        ],
    }


@router.post("/conversaciones/{conversacion_id}/tomar")
async def tomar(
    conversacion_id: int, usuario: Usuario = Depends(usuario_actual)
) -> dict:
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if not c:
            raise HTTPException(status_code=404, detail="Conversación inexistente")
        c.estado = EstadoConversacion.HUMANO
        c.tomada_por_id = usuario.id
        c.tomada_en = datetime.utcnow()
        s.add(c)
        s.commit()
    _auditar(usuario, "conversacion.tomada", entidad_id=conversacion_id)
    return {"estado": "humano", "tomada_por": usuario.nombre}


@router.post("/conversaciones/{conversacion_id}/devolver")
async def devolver(
    conversacion_id: int, usuario: Usuario = Depends(usuario_actual)
) -> dict:
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if not c:
            raise HTTPException(status_code=404, detail="Conversación inexistente")
        c.estado = EstadoConversacion.BOT
        c.tomada_por_id = None
        c.tomada_en = None
        c.motivo_escalado = None
        c.intentos_fallidos = 0
        s.add(c)
        s.commit()
    _auditar(usuario, "conversacion.devuelta", entidad_id=conversacion_id)
    return {"estado": "bot"}


@router.post("/conversaciones/{conversacion_id}/resolver")
async def resolver(
    conversacion_id: int,
    motivo_perdida: str = Body(default="", embed=True),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if not c:
            raise HTTPException(status_code=404, detail="Conversación inexistente")
        c.estado = EstadoConversacion.RESUELTA
        c.cerrada_en = datetime.utcnow()
        c.motivo_perdida = motivo_perdida
        s.add(c)
        s.commit()
    _auditar(usuario, "conversacion.resuelta", detalle=motivo_perdida, entidad_id=conversacion_id)
    return {"estado": "resuelta"}


@router.post("/conversaciones/{conversacion_id}/mensajes")
async def responder(
    conversacion_id: int,
    texto: str = Body(..., embed=True),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    from app.whatsapp import client

    texto = texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="El mensaje está vacío")

    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if not c:
            raise HTTPException(status_code=404, detail="Conversación inexistente")
        p = s.get(Paciente, c.paciente_id)
        if not p:
            raise HTTPException(status_code=404, detail="Paciente inexistente")
        telefono = p.telefono

        # Responder desde el panel implica tomar el control: el asistente
        # deja de intervenir en esta conversación.
        if c.estado is not EstadoConversacion.HUMANO:
            c.estado = EstadoConversacion.HUMANO
            c.tomada_por_id = usuario.id
            c.tomada_en = datetime.utcnow()
            s.add(c)
            s.commit()

    try:
        await client.enviar_texto(telefono, texto)
    except Exception as e:
        log.exception("No se pudo enviar el mensaje al paciente")
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo entregar el mensaje. Si el paciente no escribe "
                "desde hace más de 24 horas, WhatsApp solo permite plantillas "
                f"aprobadas. Detalle: {e}"
            ),
        )

    with sesion() as s:
        s.add(Mensaje(
            conversacion_id=conversacion_id,
            remitente=Remitente.HUMANO,
            texto=texto,
            usuario_id=usuario.id,
        ))
        c = s.get(Conversacion, conversacion_id)
        if c:
            c.ultima_actividad = datetime.utcnow()
            s.add(c)
        s.commit()

    _auditar(usuario, "mensaje.enviado", detalle=texto[:120], entidad_id=conversacion_id)
    return {"ok": True, "hora": datetime.utcnow().strftime("%H:%M")}


# ======================================================================
#  Pacientes — la agenda de contactos del consultorio
# ======================================================================

@router.get("/pacientes")
async def pacientes(
    buscar: str = "",
    usuario: Usuario = Depends(usuario_actual),
) -> list[dict]:
    with sesion() as s:
        consulta = select(Paciente).order_by(
            Paciente.ultima_interaccion.desc()  # type: ignore[attr-defined]
        )
        if buscar:
            patron = f"%{buscar.strip()}%"
            consulta = consulta.where(
                (Paciente.nombre.ilike(patron))  # type: ignore[attr-defined]
                | (Paciente.telefono.ilike(patron))  # type: ignore[attr-defined]
            )
        listado = list(s.exec(consulta.limit(200)).all())
        sedes = {x.id: x.nombre for x in s.exec(select(Sede)).all()}

        salida = []
        for p in listado:
            citas = list(s.exec(select(Cita).where(Cita.paciente_id == p.id)).all())
            ultima_conv = s.exec(
                select(Conversacion)
                .where(Conversacion.paciente_id == p.id)
                .order_by(Conversacion.id.desc())  # type: ignore[attr-defined]
            ).first()
            salida.append({
                "id": p.id,
                "nombre": p.nombre or "Sin nombre registrado",
                "telefono": p.telefono,
                "whatsapp_url": f"https://wa.me/{p.telefono}",
                "ciudad": p.ciudad or "—",
                "fuente": p.fuente or "—",
                "motivo": p.motivo_consulta or "—",
                "sede": sedes.get(p.sede_preferida_id or 0, "—"),
                "citas": len([c for c in citas if c.estado is not EstadoCita.CANCELADA]),
                "ultima": _hace(p.ultima_interaccion),
                "alta": p.creado_en.strftime("%d/%m/%Y"),
                "conversacion_id": ultima_conv.id if ultima_conv else None,
            })
        return salida


# ======================================================================
#  Configuración
# ======================================================================

@router.get("/config")
async def leer_config(usuario: Usuario = Depends(usuario_actual)) -> dict:
    from app.brain.ai import consumo_del_mes, tope_alcanzado

    with sesion() as s:
        sedes = list(s.exec(select(Sede).order_by(Sede.orden)).all())  # type: ignore[arg-type]
        ajuste = s.get(Ajuste, "modo_asistente")
        usuarios = list(s.exec(select(Usuario)).all())

    consumo = consumo_del_mes()
    return {
        "modo": ajuste.valor if ajuste else config.modo_asistente,
        "tope_alcanzado": tope_alcanzado(),
        "ia": {
            "gasto": round(consumo.costo_usd, 2),
            "limite": config.ia_limite_mensual_usd,
            "llamadas": consumo.llamadas,
            "porcentaje": (
                min(100, round(100 * consumo.costo_usd / config.ia_limite_mensual_usd))
                if config.ia_limite_mensual_usd else 0
            ),
        },
        "agenda": {
            "proveedor": config.agenda_proveedor,
            "escribe_en_doctoralia": config.agenda_proveedor == "api",
            "traslado_min": config.minutos_traslado_entre_sedes,
        },
        "sedes": [
            {
                "id": x.id,
                "nombre": x.nombre,
                "direccion": x.direccion,
                "horarios": x.horarios or "Sin horario cargado",
                "precio": x.precio_valoracion,
                "activa": x.activa,
            }
            for x in sedes
        ],
        "usuarios": [
            {
                "nombre": u.nombre,
                "correo": u.correo,
                "rol": u.rol.value,
                "activo": u.activo,
                "ultimo_acceso": _hace(u.ultimo_acceso),
                "iniciales": "".join(p[0] for p in u.nombre.split()[:2]).upper(),
            }
            for u in usuarios
        ],
    }


@router.patch("/sedes/{sede_id}")
async def cambiar_sede(
    sede_id: int,
    activa: bool = Body(..., embed=True),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    solo_admin(usuario)
    with sesion() as s:
        sede = s.get(Sede, sede_id)
        if not sede:
            raise HTTPException(status_code=404, detail="Sede inexistente")
        sede.activa = activa
        s.add(sede)
        s.commit()
        nombre = sede.nombre
    _auditar(
        usuario, "sede.cambiada",
        detalle=f"{nombre} → {'activa' if activa else 'inactiva'}",
        entidad_id=sede_id,
    )
    return {"id": sede_id, "activa": activa}


@router.put("/modo")
async def cambiar_modo(
    modo: str = Body(..., embed=True),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    solo_admin(usuario)
    try:
        valor = ModoAsistente(modo).value
    except ValueError:
        raise HTTPException(status_code=400, detail="Modo desconocido")

    with sesion() as s:
        ajuste = s.get(Ajuste, "modo_asistente")
        if ajuste:
            ajuste.valor = valor
            ajuste.actualizado_en = datetime.utcnow()
        else:
            ajuste = Ajuste(clave="modo_asistente", valor=valor)
        s.add(ajuste)
        s.commit()

    _auditar(usuario, "modo.cambiado", detalle=valor)
    return {"modo": valor}


@router.get("/auditoria")
async def auditoria(usuario: Usuario = Depends(usuario_actual)) -> list[dict]:
    solo_admin(usuario)
    with sesion() as s:
        registros = list(s.exec(
            select(RegistroAuditoria)
            .order_by(RegistroAuditoria.ocurrido_en.desc())  # type: ignore[attr-defined]
            .limit(120)
        ).all())
    return [
        {
            "actor": r.actor,
            "accion": r.accion,
            "detalle": r.detalle,
            "cuando": r.ocurrido_en.strftime("%d/%m %H:%M"),
        }
        for r in registros
    ]
