"""
Genera el PDF del criterio de urgencias para que lo firme el Dr. Padilla.

    python scripts/generar_pdf_urgencias.py

Sale en `docs/Criterio-de-urgencias-Dr-Padilla.pdf`, tamaño carta, listo
para imprimir o para llenar en pantalla.

El contenido vive acá y no se parsea del Markdown a propósito: es un
documento que va a firmar un médico, y el control del formato importa.
Cuando cambie el criterio, se cambia en los dos lados.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "Criterio-de-urgencias-Dr-Padilla.pdf"
FUENTES = Path("C:/Windows/Fonts")

# Paleta sobria, la misma del panel.
TINTA = (18, 28, 26)
TINTA_2 = (72, 88, 84)
TINTA_3 = (128, 142, 138)
ACENTO = (11, 106, 95)
ALARMA = (166, 58, 44)
LINEA = (208, 218, 215)
FONDO = (240, 244, 243)
FONDO_ALARMA = (250, 235, 232)


class Documento(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(20, 18, 20)
        self._cargar_fuentes()
        self.set_title("Criterio de urgencias — Consultorio Dr. José Guadalupe Padilla")

    def _cargar_fuentes(self) -> None:
        candidatas = [
            ("Sans", "", "segoeui.ttf", "calibri.ttf", "arial.ttf"),
            ("Sans", "B", "segoeuib.ttf", "calibrib.ttf", "arialbd.ttf"),
            ("Sans", "I", "segoeuii.ttf", "calibrii.ttf", "ariali.ttf"),
        ]
        for familia, estilo, *opciones in candidatas:
            for archivo in opciones:
                ruta = FUENTES / archivo
                if ruta.exists():
                    self.add_font(familia, estilo, str(ruta))
                    break
            else:
                sys.exit(f"No se encontró una fuente para {familia}{estilo}")

        for archivo in ("georgiab.ttf", "timesbd.ttf", "segoeuib.ttf"):
            ruta = FUENTES / archivo
            if ruta.exists():
                self.add_font("Titular", "", str(ruta))
                break

    # ------------------------------------------------------------------

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-16)
        self.set_font("Sans", "", 7.5)
        self.set_text_color(*TINTA_3)
        self.cell(
            0, 5,
            f"Criterio de urgencias · Consultorio Dr. José Guadalupe Padilla"
            f"          {self.page_no()}",
            align="C",
        )

    # ------------------------------------------------------------------
    #  Componentes
    # ------------------------------------------------------------------

    def titulo_seccion(self, texto: str, color=ACENTO) -> None:
        self.ln(4)
        if self.get_y() > 225:
            self.add_page()
        self.set_font("Sans", "B", 8)
        self.set_text_color(*color)
        self.cell(0, 5, texto.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*color)
        self.set_line_width(0.4)
        y = self.get_y() + 0.6
        self.line(20, y, 196, y)
        self.ln(3.5)

    def subtitulo(self, texto: str) -> None:
        if self.get_y() > 235:
            self.add_page()
        self.ln(1.5)
        self.set_font("Sans", "B", 9.5)
        self.set_text_color(*TINTA)
        self.cell(0, 5.5, texto, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def parrafo(self, texto: str, tamano: float = 9, color=TINTA_2, alto: float = 4.6) -> None:
        self.set_font("Sans", "", tamano)
        self.set_text_color(*color)
        self.multi_cell(0, alto, texto, new_x="LMARGIN", new_y="NEXT")
        self.ln(1.2)

    def cita(self, texto: str, color_fondo=FONDO, color_barra=ACENTO) -> None:
        """Bloque destacado con barra lateral."""
        self.set_font("Sans", "I", 8.5)
        alto_linea = 4.3
        ancho = 176 - 8
        lineas = self.multi_cell(ancho, alto_linea, texto, dry_run=True, output="LINES")
        alto = len(lineas) * alto_linea + 5

        if self.get_y() + alto > 250:
            self.add_page()

        y0 = self.get_y()
        self.set_fill_color(*color_fondo)
        self.rect(20, y0, 176, alto, style="F")
        self.set_fill_color(*color_barra)
        self.rect(20, y0, 1.2, alto, style="F")

        self.set_xy(25, y0 + 2.5)
        self.set_text_color(*TINTA_2)
        self.multi_cell(ancho, alto_linea, texto, new_x="LMARGIN", new_y="NEXT")
        self.set_y(y0 + alto)
        self.ln(2.5)

    def casilla(self, x: float, y: float, lado: float = 3.4) -> None:
        self.set_draw_color(*TINTA_3)
        self.set_line_width(0.25)
        self.rect(x, y, lado, lado)

    def opciones(self, etiquetas: list[str], x: float, y: float) -> float:
        """Dibuja «☐ Sí  ☐ No» y devuelve el ancho ocupado."""
        self.set_font("Sans", "", 8.5)
        self.set_text_color(*TINTA_2)
        cursor = x
        for etiqueta in etiquetas:
            self.casilla(cursor, y + 1.1)
            self.set_xy(cursor + 4.6, y)
            self.cell(self.get_string_width(etiqueta) + 1, 5.5, etiqueta)
            cursor += 4.6 + self.get_string_width(etiqueta) + 5
        return cursor - x

    def fila_signo(self, numero: int, texto: str, opts: list[str] | None = None) -> None:
        opts = opts or ["Sí", "No"]
        alto = 7.4
        if self.get_y() + alto > 248:
            self.add_page()

        y0 = self.get_y()
        if numero % 2 == 0:
            self.set_fill_color(*FONDO)
            self.rect(20, y0, 176, alto, style="F")

        self.set_xy(22, y0)
        self.set_font("Sans", "B", 8)
        self.set_text_color(*TINTA_3)
        self.cell(7, alto, str(numero))

        self.set_font("Sans", "", 9)
        self.set_text_color(*TINTA)
        self.set_xy(29, y0)
        self.cell(122, alto, texto)

        self.opciones(opts, 153, y0 + 1)
        self.set_y(y0 + alto)

    def fila_pregunta(self, texto: str, opts: list[str]) -> None:
        """Pregunta con opciones debajo, para textos largos."""
        if self.get_y() + 13 > 248:
            self.add_page()
        self.set_font("Sans", "", 9)
        self.set_text_color(*TINTA)
        self.multi_cell(176, 4.8, texto, new_x="LMARGIN", new_y="NEXT")
        y = self.get_y() + 0.5
        self.opciones(opts, 24, y)
        self.set_y(y + 7)

    def renglones(self, cantidad: int = 3, sangria: float = 0) -> None:
        self.ln(1)
        self.set_draw_color(*LINEA)
        self.set_line_width(0.25)
        for _ in range(cantidad):
            if self.get_y() > 250:
                self.add_page()
            y = self.get_y() + 5
            self.line(20 + sangria, y, 196, y)
            self.set_y(y + 2.5)
        self.ln(2)


# ======================================================================
#  Contenido
# ======================================================================

def construir() -> Documento:
    d = Documento()
    d.add_page()

    # ---------- portada ----------
    d.set_font("Titular", "", 19)
    d.set_text_color(*TINTA)
    d.multi_cell(176, 8.5, "Criterio de urgencias", new_x="LMARGIN", new_y="NEXT")
    d.ln(1)
    d.set_font("Sans", "", 10.5)
    d.set_text_color(*TINTA_2)
    d.cell(0, 5.5, "Asistente de WhatsApp · Consultorio del Dr. José Guadalupe Padilla",
           new_x="LMARGIN", new_y="NEXT")
    d.set_font("Sans", "", 9)
    d.set_text_color(*TINTA_3)
    d.cell(0, 5, "Cirugía General y Laparoscópica · Guadalajara",
           new_x="LMARGIN", new_y="NEXT")
    d.ln(5)

    d.set_draw_color(*ACENTO)
    d.set_line_width(0.8)
    d.line(20, d.get_y(), 60, d.get_y())
    d.ln(6)

    d.subtitulo("Por qué esto lo define usted y no yo")
    d.parrafo(
        "El asistente está programado para detectar signos de alarma. Cuando los "
        "encuentra deja de responder por su cuenta: le indica al paciente que acuda a "
        "urgencias y les avisa a ustedes de inmediato. Nunca da un diagnóstico ni "
        "tranquiliza a nadie."
    )
    d.parrafo(
        "La lista de qué cuenta como signo de alarma es una decisión clínica, no "
        "técnica. Armé una propuesta con criterio de cirugía general —abdomen agudo y "
        "postoperatorio complicado— pero necesito que usted la revise y la apruebe "
        "antes de que el sistema atienda a un paciente real."
    )
    d.parrafo(
        "Es la única parte del proyecto donde un error no es un problema comercial.",
        tamano=9.5, color=ALARMA,
    )

    d.cita(
        "Cómo responder: marque cada punto y agregue lo que falte. Si le resulta más "
        "cómodo, grábeme un audio recorriendo la lista; con eso me alcanza para "
        "implementarlo.",
        color_fondo=FONDO, color_barra=ACENTO,
    )

    # ---------- Parte A ----------
    d.titulo_seccion("Parte A · Signos de alarma  →  «acuda a urgencias»", ALARMA)
    d.parrafo("Cuando el paciente escribe algo de esta lista, el asistente responde:", tamano=9)
    d.cita(
        "«Por lo que me describe es importante que la valoren hoy mismo de forma "
        "presencial. Le pido que acuda al servicio de urgencias más cercano sin "
        "esperar. Ya avisé al equipo del Dr. Padilla para que la contacten. Si el "
        "malestar aumenta, no espere la llamada y acuda de inmediato.»",
        color_fondo=FONDO_ALARMA, color_barra=ALARMA,
    )
    d.parrafo("Y a ustedes les llega el aviso marcado como urgente.", tamano=8.5, color=TINTA_3)

    d.subtitulo("A1 · Abdominal")
    for i, texto in enumerate([
        "Dolor «muy fuerte», «intenso» o «insoportable»",
        "«No aguanto el dolor» / «me duele muchísimo»",
        "Dolor que no cede ni se calma",
        "Abdomen duro, rígido o muy distendido",
        "No puede pasar gases ni evacuar",
    ], start=1):
        d.fila_signo(i, texto)

    d.subtitulo("A2 · Sistémicos")
    for i, texto in enumerate([
        "Fiebre alta (39 °C o más)",
        "Escalofríos",
        "Desmayo o sensación de desmayo",
        "Dificultad para respirar o falta de aire",
        "Dolor en el pecho",
    ], start=6):
        d.fila_signo(i, texto)

    d.ln(2)
    d.set_font("Sans", "B", 8.5)
    d.set_text_color(*ACENTO)
    d.cell(0, 5, "A definir: ¿desde qué temperatura quiere que se considere alarma?",
           new_x="LMARGIN", new_y="NEXT")
    y = d.get_y() + 0.5
    ancho = d.opciones(["38 °C", "38.5 °C", "39 °C  (actual)", "Otra:"], 24, y)
    d.set_draw_color(*LINEA)
    d.line(24 + ancho - 3, y + 5, 24 + ancho + 32, y + 5)
    d.set_y(y + 8)

    d.subtitulo("A3 · Sangrado y vómito")
    for i, texto in enumerate([
        "Sangrado abundante o que no se detiene",
        "Sangre en vómito, heces u orina",
        "Vómito persistente («llevo días vomitando», «vomito todo»)",
    ], start=11):
        d.fila_signo(i, texto)

    d.subtitulo("A4 · Ictericia")
    d.fila_signo(14, "Piel u ojos amarillos")

    d.subtitulo("A5 · Herida quirúrgica")
    for i, texto in enumerate([
        "La herida se abrió",
        "Sale pus o líquido por la herida",
        "Herida muy roja, caliente o con mal olor",
        "Se zafó un punto o una grapa",
    ], start=15):
        d.fila_signo(i, texto)

    d.subtitulo("A6 · ¿Falta algo?")
    d.parrafo(
        "Signos que usted agregaría, sobre todo los propios de los procedimientos que "
        "hace con más frecuencia. Es justo lo que yo no puedo saber.",
        tamano=8.5, color=TINTA_3,
    )
    d.renglones(3)

    # ---------- Parte B ----------
    d.titulo_seccion("Parte B · Cuándo quiere que lo contacten a usted")
    d.parrafo(
        "Distinto de mandar al paciente a urgencias: son los casos en que su asistente "
        "debe buscarlo a usted directamente."
    )

    d.subtitulo("Ante un signo de alarma de la Parte A, ¿a quién avisamos?")
    y = d.get_y()
    d.opciones(["A usted, siempre", "A usted, solo en horario", "Solo a la asistente"], 24, y)
    d.set_y(y + 9)

    d.subtitulo("¿Y en estos otros casos?")
    for n, texto in enumerate([
        "Paciente postoperado suyo con cualquier molestia",
        "Paciente que pide hablar con usted por su nombre",
        "Consulta de un colega o referencia médica",
        "Paciente molesto o con un reclamo",
        "Alguien preguntando por una cirugía ya programada",
    ], start=1):
        d.fila_signo(n, texto, ["Avisarme", "No"])

    d.ln(3)
    d.subtitulo("¿Por qué vía prefiere el aviso urgente?")
    y = d.get_y()
    d.opciones(["WhatsApp personal", "Telegram", "Llamada", "Solo el panel"], 24, y)
    d.set_y(y + 8)

    d.subtitulo("¿En qué horario acepta que lo contacten?")
    d.renglones(2, sangria=4)
    y = d.get_y()
    d.set_font("Sans", "", 9)
    d.set_text_color(*TINTA)
    d.cell(0, 5, "Fuera de ese horario:", new_x="LMARGIN", new_y="NEXT")
    y = d.get_y() + 0.5
    d.opciones(["Avísenme igual si es urgencia", "Que espere a la mañana"], 24, y)
    d.set_y(y + 9)

    # ---------- Parte C ----------
    d.titulo_seccion("Parte C · Fuera del horario de atención")

    d.parrafo(
        "Cuando el consultorio está cerrado y el mensaje NO parece urgencia, hoy el "
        "asistente responde y agenda con normalidad para el siguiente día hábil."
    )
    y = d.get_y()
    d.opciones(["Está bien así", "Prefiero otra cosa:"], 24, y)
    d.set_draw_color(*LINEA)
    d.line(120, y + 5, 196, y + 5)
    d.set_y(y + 9)

    d.parrafo("Cuando SÍ parece urgencia fuera de horario, hoy responde:")
    d.cita(
        "«En este momento el consultorio está cerrado, pero ya dejé su mensaje marcado "
        "como prioritario y la contactan en cuanto abran. Si se trata de algo que no "
        "puede esperar, acuda al servicio de urgencias más cercano.»",
        color_fondo=FONDO_ALARMA, color_barra=ALARMA,
    )
    y = d.get_y()
    d.opciones(["Está bien así", "Prefiero que diga:"], 24, y)
    d.line(115, y + 5, 196, y + 5)
    d.set_y(y + 10)

    d.subtitulo("¿Quiere dar un número de urgencias del consultorio?")
    y = d.get_y()
    d.opciones(["No", "Sí:"], 24, y)
    d.line(60, y + 5, 196, y + 5)
    d.set_y(y + 8)
    y = d.get_y()
    d.set_font("Sans", "", 8.5)
    d.set_text_color(*TINTA_3)
    d.cell(0, 5, "Si es que sí, ¿a quién se le da?", new_x="LMARGIN", new_y="NEXT")
    y = d.get_y() + 0.5
    d.opciones(["A todos los pacientes", "Solo a sus postoperados"], 24, y)
    d.set_y(y + 9)

    d.subtitulo("¿Hay algún hospital al que prefiera derivar?")
    d.renglones(2, sangria=4)

    # ---------- Parte D ----------
    d.titulo_seccion("Parte D · Lo que el asistente nunca hace")
    d.parrafo(
        "Esto ya está programado. Confírmeme que está de acuerdo, o agregue lo que falte."
    )
    for n, texto in enumerate([
        "Emitir diagnósticos ni sugerir qué puede tener el paciente",
        "Recomendar medicamentos, dosis o tratamientos",
        "Interpretar estudios, análisis o imágenes",
        "Prometer resultados o dar pronósticos de recuperación",
        "Negociar honorarios o modificar precios",
        "Tranquilizar sobre un síntoma («seguramente no es nada»)",
        "Abrir fotografías o estudios que envíe el paciente",
    ], start=1):
        d.fila_signo(n, texto, ["De acuerdo", "No"])

    d.ln(2)
    d.cita(
        "El punto 6 es el más importante de todos. El asistente jamás minimiza un "
        "síntoma, aunque el paciente insista en que le diga si es grave. Ante la duda, "
        "deriva. Prefiero que derive de más y su asistente pierda treinta segundos, "
        "antes que lo contrario.",
        color_fondo=FONDO_ALARMA, color_barra=ALARMA,
    )
    d.cita(
        "Sobre el punto 7: cuando llega una fotografía, el asistente no la abre ni la "
        "guarda. Avisa que la va a ver su equipo y deriva la conversación."
    )

    d.subtitulo("¿Algo más que quiera prohibirle expresamente?")
    d.renglones(2, sangria=4)

    # ---------- Parte E ----------
    d.titulo_seccion("Parte E · Seguimiento postoperatorio")

    d.fila_pregunta(
        "¿Quiere que el asistente escriba a sus postoperados para saber cómo siguen?",
        ["Sí", "No"],
    )
    y = d.get_y()
    d.set_font("Sans", "", 9)
    d.set_text_color(*TINTA)
    etiqueta = "Si es que sí, ¿a los cuántos días?"
    d.cell(d.get_string_width(etiqueta) + 3, 5.5, etiqueta)
    d.set_draw_color(*LINEA)
    x = 20 + d.get_string_width(etiqueta) + 5
    d.line(x, y + 5, x + 28, y + 5)
    d.set_y(y + 8)

    d.fila_pregunta(
        "¿Puede preguntar «cómo ha seguido», o prefiere que solo ofrezca la cita de control?",
        ["Cómo ha seguido", "Solo la cita de control"],
    )

    d.cita(
        "Si un paciente responde con algo clínico, el asistente no lo interpreta: "
        "deriva a su equipo. Eso no cambia según lo que responda aquí."
    )

    # ---------- Firma ----------
    # Bloque indivisible: la firma y su nota no se separan en dos páginas.
    if d.get_y() > 195:
        d.add_page()
    d.ln(4)
    d.titulo_seccion("Revisión y aprobación")
    d.parrafo(
        "Reviso y apruebo el criterio anterior para su uso en el asistente de WhatsApp "
        "del consultorio.",
        tamano=9.5, color=TINTA,
    )
    d.ln(10)

    d.set_draw_color(*TINTA_2)
    d.set_line_width(0.35)
    y = d.get_y()
    d.line(20, y, 105, y)
    d.line(120, y, 196, y)
    d.set_font("Sans", "", 8)
    d.set_text_color(*TINTA_3)
    d.set_xy(20, y + 1.5)
    d.cell(85, 4, "Dr. José Guadalupe Padilla")
    d.set_xy(120, y + 1.5)
    d.cell(76, 4, "Fecha")

    d.ln(12)
    d.set_font("Sans", "", 7.5)
    d.set_text_color(*TINTA_3)
    d.multi_cell(
        176, 3.8,
        "Las respuestas de la Parte A se implementan en el módulo de barrera clínica del "
        "sistema, y las de la Parte B en las reglas de derivación y avisos. Este "
        "documento queda como constancia del criterio clínico aplicado y de quién lo "
        "definió.",
        new_x="LMARGIN", new_y="NEXT",
    )

    return d


if __name__ == "__main__":
    SALIDA.parent.mkdir(exist_ok=True)
    documento = construir()
    documento.output(str(SALIDA))
    kb = SALIDA.stat().st_size / 1024
    print(f"\n  {SALIDA}")
    print(f"  {documento.pages_count} páginas · {kb:.0f} KB\n")
