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
    Profesional,
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
    "calendario_google_id",
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
            "calendario_google_id": x.calendario_google_id,
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
#  Profesionales
#
#  Dos usos, una sola tabla:
#
#    · El Dr. Padilla — el titular del número. El asistente le agenda.
#    · Otro profesional que atiende por su propio número (la agenda de su
#      esposa, un colega). Con «deriva» activado el asistente reconoce que
#      el paciente lo busca a él y le pasa el número correcto, en vez de
#      agendarle con el médico equivocado.
# ======================================================================

CAMPOS_PROFESIONAL = {
    "nombre", "titulo", "especialidad", "principal", "deriva",
    "telefono_whatsapp", "palabras_clave", "mensaje_derivacion",
    "calendario_google_id", "activo", "orden",
}


def _telefono_limpio(crudo: str) -> str:
    """Solo dígitos y un + inicial. Un número con espacios no es clicable."""
    t = (crudo or "").strip()
    if not t:
        return ""
    mas = t.startswith("+")
    digitos = "".join(c for c in t if c.isdigit())
    return ("+" if mas else "") + digitos


def _vista_profesional(p) -> dict:
    return {
        "id": p.id,
        "nombre": p.nombre,
        "titulo": p.titulo,
        "nombre_completo": p.nombre_completo,
        "especialidad": p.especialidad,
        "principal": p.principal,
        "deriva": p.deriva,
        "telefono_whatsapp": p.telefono_whatsapp,
        "palabras_clave": p.palabras_clave,
        "mensaje_derivacion": p.mensaje_derivacion,
        "calendario_google_id": p.calendario_google_id,
        "activo": p.activo,
        "orden": p.orden,
        # Un profesional que deriva sin número cargado no sirve de nada: el
        # asistente lo reconoce y no tiene qué contestar. El panel lo avisa.
        "incompleto": bool(p.deriva and p.activo and not p.telefono_whatsapp),
    }


@router.get("/profesionales")
async def listar_profesionales(usuario: Usuario = Depends(usuario_actual)) -> list[dict]:
    with sesion() as s:
        listado = list(s.exec(
            select(Profesional).order_by(Profesional.orden)  # type: ignore[arg-type]
        ).all())
    return [_vista_profesional(p) for p in listado]


@router.post("/profesionales")
async def crear_profesional(
    datos: dict = Body(...),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    solo_admin(usuario)

    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="Falta el nombre")

    with sesion() as s:
        p = Profesional(
            nombre=nombre,
            titulo=(datos.get("titulo") or "Dr.").strip(),
            especialidad=(datos.get("especialidad") or "").strip(),
            deriva=bool(datos.get("deriva", True)),
            telefono_whatsapp=_telefono_limpio(datos.get("telefono_whatsapp", "")),
            palabras_clave=(datos.get("palabras_clave") or "").strip(),
            mensaje_derivacion=(datos.get("mensaje_derivacion") or "").strip(),
            calendario_google_id=(datos.get("calendario_google_id") or "").strip(),
            activo=bool(datos.get("activo", True)),
            orden=int(datos.get("orden") or 99),
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        nuevo = p.id

    _auditar(usuario, "profesional.creado", detalle=nombre, entidad_id=nuevo)
    return {"id": nuevo}


@router.put("/profesionales/{profesional_id}")
async def editar_profesional(
    profesional_id: int,
    datos: dict = Body(...),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    solo_admin(usuario)

    with sesion() as s:
        p = s.get(Profesional, profesional_id)
        if not p:
            raise HTTPException(status_code=404, detail="Profesional inexistente")

        cambios = []
        for clave, valor in datos.items():
            if clave not in CAMPOS_PROFESIONAL:
                continue
            if clave == "telefono_whatsapp":
                valor = _telefono_limpio(valor)
            if clave in ("nombre", "titulo") and not str(valor or "").strip():
                raise HTTPException(status_code=400, detail=f"«{clave}» no puede quedar vacío")
            if getattr(p, clave) != valor:
                cambios.append(clave)
                setattr(p, clave, valor)

        # El titular del número nunca puede derivar a sí mismo: el asistente
        # le contestaría a un paciente que escriba al número correcto que se
        # vaya a ese mismo número.
        if p.principal and p.deriva:
            raise HTTPException(
                status_code=400,
                detail="El profesional principal atiende por este número; no puede derivar.",
            )

        s.add(p)
        s.commit()
        nombre = p.nombre

    if cambios:
        _auditar(
            usuario, "profesional.editado",
            detalle=f"{nombre}: {', '.join(cambios)}",
            entidad_id=profesional_id,
        )
    return {"id": profesional_id, "cambios": cambios}


@router.delete("/profesionales/{profesional_id}")
async def borrar_profesional(
    profesional_id: int, usuario: Usuario = Depends(usuario_actual)
) -> dict:
    solo_admin(usuario)

    with sesion() as s:
        p = s.get(Profesional, profesional_id)
        if not p:
            raise HTTPException(status_code=404, detail="Profesional inexistente")
        if p.principal:
            raise HTTPException(
                status_code=400,
                detail="No se puede borrar al profesional principal.",
            )
        # Se conserva la fila si tiene citas: borrarla dejaría citas
        # apuntando a nadie. Se desactiva, que es lo que se busca igual.
        tiene_citas = s.exec(
            select(Cita).where(Cita.profesional_id == profesional_id)
        ).first() is not None
        nombre = p.nombre
        if tiene_citas:
            p.activo = False
            s.add(p)
        else:
            s.delete(p)
        s.commit()

    _auditar(usuario, "profesional.borrado", detalle=nombre, entidad_id=profesional_id)
    return {"ok": True, "desactivado": tiene_citas}


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


@router.post("/citas")
async def registrar_cita(
    datos: dict = Body(...),
    usuario: Usuario = Depends(usuario_actual),
) -> dict:
    """
    Registrar una cita que entró por otro lado.

    Es la pieza que hace que el asistente deje de ser ciego. Hasta acá solo
    conocía las citas que él mismo agendó: una cita tomada por Doctoralia o
    por teléfono no existía para el sistema, así que no podía confirmarla,
    ni recordarla, ni reprogramarla, y el paciente que escribía por ella
    recibía a una persona.

    Con esto, la asistente la carga en segundos y a partir de ese momento el
    asistente la trata como cualquier otra: recordatorio de 24 horas con la
    dirección de esa sede, confirmación por WhatsApp y reprogramación.

    No verifica disponibilidad a propósito. No se está pidiendo un lugar: se
    está registrando algo que ya ocurrió. Si hay superposición se avisa,
    pero la decisión es del consultorio.
    """
    from app.agenda.service import origen as origen_agenda
    from app.models import Cita, EstadoCita
    from app.tiempo import a_utc

    telefono = "".join(c for c in str(datos.get("telefono") or "") if c.isdigit())
    if not telefono:
        raise HTTPException(status_code=400, detail="Falta el teléfono del paciente")

    try:
        inicio_local = datetime.fromisoformat(str(datos.get("inicio") or ""))
    except ValueError:
        raise HTTPException(status_code=400, detail="La fecha y hora no son válidas")

    #: Lo que escribe una persona es hora del consultorio; lo que se guarda
    #: es UTC. Mezclarlo manda al paciente seis horas antes o después.
    inicio = a_utc(inicio_local)

    with sesion() as s:
        sede = s.get(Sede, int(datos.get("sede_id") or 0))
        if not sede:
            raise HTTPException(status_code=404, detail="Sede inexistente")
        duracion = sede.duracion_cita_min or 30
        nombre_sede = sede.nombre

    fin = inicio + timedelta(minutes=int(datos.get("duracion_min") or duracion))

    with sesion() as s:
        paciente = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        if not paciente:
            paciente = Paciente(
                telefono=telefono,
                nombre=(datos.get("nombre") or "").strip(),
                fuente=(datos.get("fuente") or "doctoralia").strip(),
            )
            s.add(paciente)
            s.commit()
            s.refresh(paciente)
        elif datos.get("nombre") and not paciente.nombre:
            paciente.nombre = str(datos["nombre"]).strip()
            s.add(paciente)
            s.commit()
        paciente_id = paciente.id
        nombre_paciente = paciente.nombre or "Paciente"

        choque = s.exec(
            select(Cita).where(
                Cita.sede_id == sede.id,
                Cita.inicio < fin,
                Cita.fin > inicio,
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.SOLICITADA, EstadoCita.AGENDADA, EstadoCita.CONFIRMADA,
                ]),
            )
        ).first()

    if choque and not datos.get("forzar"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ya hay una cita en {nombre_sede} a esa hora "
                f"({fecha_corta(choque.inicio)}). Confirme si desea registrarla igual."
            ),
        )

    # Con Google como agenda, la cita se escribe también allá: si no, el
    # asistente la conocería pero la agenda del doctor no.
    externo_id = ""
    if origen_agenda() == "google":
        from app.agenda.google_calendar import registrar_evento

        with sesion() as s:
            sede_obj = s.get(Sede, int(datos.get("sede_id") or 0))
        try:
            externo_id = await registrar_evento(
                sede=sede_obj, inicio=inicio, fin=fin,
                nombre_paciente=nombre_paciente, telefono=telefono,
                motivo=str(datos.get("tipo") or "valoracion"),
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"No se pudo escribir en Google Calendar: {e}",
            )

    with sesion() as s:
        cita = Cita(
            paciente_id=paciente_id,  # type: ignore[arg-type]
            sede_id=int(datos.get("sede_id") or 0),
            inicio=inicio,
            fin=fin,
            estado=EstadoCita.AGENDADA,
            tipo=str(datos.get("tipo") or "valoracion"),
            externo_id=externo_id,
            creada_por=usuario.correo,
            # Vino de Doctoralia: allá ya está. Marcarla como pendiente de
            # cargar la mandaría a la lista de tareas de la asistente, que
            # es justo lo contrario de lo que hace falta.
            cargada_en_doctoralia=True,
            cargada_en_doctoralia_en=datetime.utcnow(),
            notas=str(datos.get("notas") or ""),
        )
        s.add(cita)
        s.commit()
        s.refresh(cita)
        nueva = cita.id

    _auditar(
        usuario, "cita.registrada",
        detalle=f"{nombre_paciente} · {nombre_sede} · {fecha_corta(inicio)}",
        entidad_id=nueva,
    )
    return {"id": nueva, "en_google": bool(externo_id)}


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
