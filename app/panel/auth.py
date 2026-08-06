"""
Acceso al panel.

Cada persona entra con su propio usuario. Nada de cuenta compartida: si
algo pasa, tiene que poder saberse quién hizo qué.

La sesión viaja en una cookie httpOnly firmada. No es accesible desde
JavaScript, así que un script inyectado en la página no puede robarla.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Cookie, HTTPException, Response, status
from jose import JWTError, jwt
from sqlmodel import select

from app.config import config
from app.db import sesion
from app.models import RolUsuario, Usuario

COOKIE = "sesion_consultorio"
ALGORITMO = "HS256"
HORAS_SESION = 12

NO_AUTORIZADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sesión no válida o vencida",
)


def crear_sesion(respuesta: Response, usuario: Usuario) -> None:
    vence = datetime.now(timezone.utc) + timedelta(hours=HORAS_SESION)
    ficha = jwt.encode(
        {"sub": str(usuario.id), "rol": usuario.rol.value, "exp": vence},
        config.panel_secreto,
        algorithm=ALGORITMO,
    )
    respuesta.set_cookie(
        COOKIE,
        ficha,
        httponly=True,
        samesite="lax",
        secure=config.entorno == "produccion",
        max_age=HORAS_SESION * 3600,
        path="/",
    )


def cerrar_sesion(respuesta: Response) -> None:
    respuesta.delete_cookie(COOKIE, path="/")


def autenticar(correo: str, clave: str) -> Usuario | None:
    from app.security import clave_correcta

    with sesion() as s:
        usuario = s.exec(
            select(Usuario).where(Usuario.correo == correo.strip().lower())
        ).first()
        if not usuario or not usuario.activo:
            return None
        if not clave_correcta(clave, usuario.hash_clave):
            return None
        usuario.ultimo_acceso = datetime.utcnow()
        s.add(usuario)
        s.commit()
        s.refresh(usuario)
        return usuario


def usuario_actual(
    sesion_consultorio: str | None = Cookie(default=None),
) -> Usuario:
    """Dependencia de FastAPI. Todas las rutas del panel la exigen."""
    if not sesion_consultorio:
        raise NO_AUTORIZADO
    try:
        datos = jwt.decode(
            sesion_consultorio, config.panel_secreto, algorithms=[ALGORITMO]
        )
    except JWTError:
        raise NO_AUTORIZADO

    with sesion() as s:
        usuario = s.get(Usuario, int(datos.get("sub", 0)))
    if not usuario or not usuario.activo:
        raise NO_AUTORIZADO
    return usuario


def solo_admin(usuario: Usuario) -> Usuario:
    """Configuración y reportes: únicamente el doctor."""
    if usuario.rol is not RolUsuario.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta sección es solo para el administrador",
        )
    return usuario
