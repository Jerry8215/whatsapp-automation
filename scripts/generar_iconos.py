"""
SUPERSEDIDO. Los iconos ahora se generan del logotipo real del
consultorio (scripts/generar_logo.py). Este archivo se conserva solo como
referencia del codificador de PNG hecho a mano; NO lo ejecute: sobrescribe
los iconos de la marca con la cruz generica.
Genera los íconos del panel instalado en el celular.

Se escriben los PNG a mano —sin dependencias de imagen— porque son cuatro
archivos de geometría simple y no vale la pena arrastrar una biblioteca de
imágenes al servidor por esto.

    python -m scripts.generar_iconos

Salida en app/panel/static/iconos/. Solo hay que volver a correrlo si
cambian los colores de la marca.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SALIDA = Path(__file__).resolve().parent.parent / "app" / "panel" / "static" / "iconos"

#: El verde del panel (--accent en panel.html). Los íconos y la interfaz
#: tienen que ser el mismo color, o la app instalada parece de otra cosa.
FONDO = (11, 106, 95, 255)
MARCA = (255, 255, 255, 255)
TRANSPARENTE = (0, 0, 0, 0)


def _png(pixeles: list[list[tuple[int, int, int, int]]]) -> bytes:
    """Codifica RGBA a PNG. Sin filtro por fila: el zlib se encarga."""
    alto = len(pixeles)
    ancho = len(pixeles[0])

    crudo = bytearray()
    for fila in pixeles:
        crudo.append(0)                       # filtro «none»
        for r, g, b, a in fila:
            crudo += bytes((r, g, b, a))

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (
            struct.pack(">I", len(datos))
            + tipo + datos
            + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
        )

    cabecera = struct.pack(">IIBBBBB", ancho, alto, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + trozo(b"IHDR", cabecera)
        + trozo(b"IDAT", zlib.compress(bytes(crudo), 9))
        + trozo(b"IEND", b"")
    )


def _dentro_del_redondeado(x: float, y: float, lado: float, radio: float) -> bool:
    """¿El punto cae dentro de un cuadrado de esquinas redondeadas?"""
    cx = min(max(x, radio), lado - radio)
    cy = min(max(y, radio), lado - radio)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radio ** 2 + 1e-9


def _cruz(x: float, y: float, lado: float, grosor: float, largo: float) -> bool:
    """La cruz médica, centrada."""
    c = lado / 2
    horizontal = abs(x - c) <= largo / 2 and abs(y - c) <= grosor / 2
    vertical = abs(y - c) <= largo / 2 and abs(x - c) <= grosor / 2
    return horizontal or vertical


def dibujar(lado: int, *, redondeado: bool, proporcion_marca: float) -> bytes:
    """
    Un ícono cuadrado.

    `redondeado=False` deja el fondo a sangre: es lo que piden los íconos
    «maskable» de Android y el de iOS, porque el sistema recorta la forma
    él mismo y un borde redondeado propio quedaría recortado dos veces.
    """
    radio = lado * 0.22
    grosor = lado * proporcion_marca * 0.30
    largo = lado * proporcion_marca

    lienzo: list[list[tuple[int, int, int, int]]] = []
    for py in range(lado):
        fila = []
        for px in range(lado):
            x, y = px + 0.5, py + 0.5
            if redondeado and not _dentro_del_redondeado(x, y, lado, radio):
                fila.append(TRANSPARENTE)
            elif _cruz(x, y, lado, grosor, largo):
                fila.append(MARCA)
            else:
                fila.append(FONDO)
        lienzo.append(fila)
    return _png(lienzo)


ICONOS = [
    # archivo, lado, redondeado, cuánto del ancho ocupa la cruz
    ("icono-192.png", 192, True, 0.52),
    ("icono-512.png", 512, True, 0.52),
    # Maskable: la marca vive dentro del 80% central, que es la zona que
    # Android garantiza que no recorta.
    ("icono-maskable-512.png", 512, False, 0.40),
    # iOS recorta y redondea por su cuenta.
    ("apple-touch-icon.png", 180, False, 0.46),
]


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, lado, redondeado, proporcion in ICONOS:
        destino = SALIDA / nombre
        destino.write_bytes(dibujar(lado, redondeado=redondeado, proporcion_marca=proporcion))
        print(f"  {destino.relative_to(SALIDA.parent.parent.parent.parent)}  ({lado}×{lado})")


if __name__ == "__main__":
    main()
