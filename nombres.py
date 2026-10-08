"""Normalizacion de nombres compartida por descargar_jornada.py y comparar.py."""
import unicodedata

# Unica normalizacion de nombres de equipo entre fuentes (alias -> clave comun).
ALIAS = {"internazionale": "inter", "inter milan": "inter", "ssc napoli": "napoli"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()
    return " ".join(s.split())


def equipo(s):
    n = norm(s)
    return ALIAS.get(n, n)
