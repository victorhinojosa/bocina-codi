"""Texto hablado: "Recibiste 100 pesos" y montos en letra para el comprobante."""

import re

from num2words import num2words


def _qty(n: int) -> str:
    """Número antes de 'peso(s)'/'centavo(s)'. La voz lee '1' como 'uno', pero en español se dice
    'un peso', 'veintiún pesos', 'ciento un pesos'. Para esos casos usamos la palabra; el resto en dígitos."""
    if n % 10 == 1 and n % 100 != 11:
        w = num2words(n, lang="es")
        if w.endswith("veintiuno"):
            return w[: -len("veintiuno")] + "veintiún"
        if w.endswith("uno"):
            return w[:-3] + "un"
        return w
    return f"{n:,}"


def money_words(amount: float) -> str:
    cents = round(float(amount) * 100)
    pesos, cent = divmod(cents, 100)
    parts = []
    if pesos:
        parts.append(f"{_qty(pesos)} {'peso' if pesos == 1 else 'pesos'}")
    if cent:
        parts.append(f"{_qty(cent)} {'centavo' if cent == 1 else 'centavos'}")
    return " con ".join(parts) if parts else "0 pesos"


def _words_apocope(n: int) -> str:
    """Número en letra listo para ir antes de un sustantivo: 'un', 'veintiún', 'treinta y un'.
    También antes de 'mil': num2words dice 'veintiuno mil', lo correcto es 'veintiún mil'."""
    words = num2words(n, lang="es")
    words = re.sub(r"\bveintiuno mil\b", "veintiún mil", words)
    words = re.sub(r"\buno mil\b", "un mil", words)
    if words.endswith("veintiuno"):
        return words[:-len("veintiuno")] + "veintiún"
    if words == "uno" or words.endswith(" uno"):
        return words[:-3] + "un"
    return words


def amount_letters(amount: float) -> str:
    """Monto en letra para el comprobante: 'Ciento cincuenta pesos con cincuenta centavos'."""
    cents = round(float(amount) * 100)
    pesos, cent = divmod(cents, 100)
    words = _words_apocope(pesos)
    if words.endswith(("millón", "millones")):
        words += " de"
    cents_text = f"{_words_apocope(cent)} {'centavo' if cent == 1 else 'centavos'}"
    if pesos == 0 and cent:
        text = cents_text
    else:
        text = f"{words} {'peso' if pesos == 1 else 'pesos'}"
        if cent:
            text += f" con {cents_text}"
    return text[:1].upper() + text[1:]


def speech_for_amount(amount: float, simulated: bool = False) -> str:
    text = f"Recibiste {money_words(amount)}"
    return f"Simulación. {text}" if simulated else text
