"""
Pruebas de configuración.

La normalización de la URL de base de datos existe porque Railway, Render
y Heroku inyectan `postgresql://`, y con esa forma SQLAlchemy busca
psycopg2 — que no está instalado, porque el proyecto usa psycopg 3. Sin
esto, el despliegue falla al arrancar con un error que no dice nada útil.
"""

import pytest

from app.config import Config


@pytest.mark.parametrize("crudo,esperado", [
    # Lo que inyecta Railway
    ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
    # La forma antigua, que todavía usan algunos proveedores
    ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    # Ya normalizada: no se toca
    ("postgresql+psycopg://u@h/d", "postgresql+psycopg://u@h/d"),
    # SQLite en desarrollo: no se toca
    ("sqlite:///./datos/consultorio.db", "sqlite:///./datos/consultorio.db"),
])
def test_la_url_de_la_base_se_normaliza(monkeypatch, crudo, esperado):
    monkeypatch.setenv("DATABASE_URL", crudo)
    assert Config().url_base_datos == esperado


def test_la_contrasena_de_la_base_no_se_altera(monkeypatch):
    """Las contraseñas traen caracteres raros; no deben tocarse."""
    url = "postgresql://usuario:aB3$%40x!@host:5432/basededatos"
    monkeypatch.setenv("DATABASE_URL", url)
    assert Config().url_base_datos.endswith("usuario:aB3$%40x!@host:5432/basededatos")
