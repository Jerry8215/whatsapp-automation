"""
Genera los íconos del panel a partir del logotipo del consultorio.

    python -m scripts.generar_logo

Lee `marca/logo.png` —el logotipo original, tal como lo entregó el
consultorio— y produce los tamaños que usa el sistema:

  * `logo-96` y `logo-192`   la marca dentro del panel, sobre fondo propio
  * `icono-192` y `icono-512`  la app instalada en el celular
  * `apple-touch-icon`         iOS, que lo busca en la raíz
  * `icono-maskable-512`       Android, que recorta según la forma del aparato

Solo hay que volver a ejecutarlo si cambia el logotipo. Requiere Pillow,
que es una dependencia de desarrollo y no viaja al servidor.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "marca" / "logo.png"
DESTINO = RAIZ / "app" / "panel" / "static" / "iconos"

#: Los íconos de la app no pueden ser transparentes: el sistema los pinta
#: sobre blanco o sobre negro según el tema, y en el segundo caso el
#: logotipo —que es azul sobre claro— desaparece.
FONDO = (255, 255, 255, 255)

#: Android recorta los bordes del ícono «maskable». La marca vive dentro
#: de este porcentaje central para que no le corten el texto.
ZONA_SEGURA = 0.78


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Falta Pillow.  pip install pillow")
        return 1

    if not ORIGEN.is_file():
        print(f"No encuentro el logotipo en {ORIGEN}")
        return 1

    DESTINO.mkdir(parents=True, exist_ok=True)
    original = Image.open(ORIGEN).convert("RGBA")

    # El archivo trae margen transparente alrededor del círculo. Sin
    # recortarlo, el logotipo se ve más chico de lo que es.
    logo = original.crop(original.getbbox())

    def guardar(nombre: str, lado: int, fondo=None) -> None:
        img = logo.resize((lado, lado), Image.LANCZOS)
        if fondo:
            base = Image.new("RGBA", (lado, lado), fondo)
            base.alpha_composite(img)
            img = base
        destino = DESTINO / nombre
        img.save(destino, "PNG", optimize=True)
        print(f"  {nombre:<26} {lado}x{lado}  {destino.stat().st_size // 1024} KB")

    guardar("logo-96.png", 96)
    guardar("logo-192.png", 192)
    guardar("icono-192.png", 192, FONDO)
    guardar("icono-512.png", 512, FONDO)
    guardar("apple-touch-icon.png", 180, FONDO)

    lado = 512
    seguro = int(lado * ZONA_SEGURA)
    base = Image.new("RGBA", (lado, lado), FONDO)
    base.alpha_composite(logo.resize((seguro, seguro), Image.LANCZOS),
                         ((lado - seguro) // 2, (lado - seguro) // 2))
    base.save(DESTINO / "icono-maskable-512.png", "PNG", optimize=True)
    print(f"  {'icono-maskable-512.png':<26} {lado}x{lado}  "
          f"{(DESTINO / 'icono-maskable-512.png').stat().st_size // 1024} KB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
