"""
Genera el par de claves de los avisos push. Se corre una sola vez.

    python -m scripts.generar_claves_vapid

Imprime las tres líneas que van al .env del servidor. Guardar la privada
como cualquier otra credencial: nunca en el repositorio.

Si algún día se cambian estas claves, todos los teléfonos registrados dejan
de recibir avisos y hay que volver a activarlos desde el panel. No es una
operación de rutina.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def generar() -> tuple[str, str]:
    """Devuelve (privada, publica) en base64url, como las quiere el navegador."""
    clave = ec.generate_private_key(ec.SECP256R1())

    privada = _b64url(clave.private_numbers().private_value.to_bytes(32, "big"))
    publica = _b64url(clave.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    ))
    return privada, publica


def main() -> None:
    privada, publica = generar()
    print("\nPegar en el .env del servidor:\n")
    print(f"VAPID_CLAVE_PUBLICA={publica}")
    print(f"VAPID_CLAVE_PRIVADA={privada}")
    print("VAPID_CONTACTO=mailto:soporte@consultorio.local")
    print("\nLa clave privada no se comparte ni se sube al repositorio.\n")


if __name__ == "__main__":
    main()
