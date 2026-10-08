"""Normalizacion de nombres compartida por descargar_jornada.py, comparar.py y resumen.py."""
import unicodedata

# Unica normalizacion de nombres de equipo entre fuentes (alias -> clave comun).
ALIAS = {"internazionale": "inter", "inter milan": "inter", "ssc napoli": "napoli"}

# Letras que NFKD no descompone en ASCII.
_TRANSLIT = str.maketrans({"ð": "d", "Ð": "d", "đ": "d", "Đ": "d", "ı": "i", "İ": "i", "ł": "l", "Ł": "l",
                           "ø": "o", "Ø": "o", "þ": "th", "æ": "ae", "œ": "oe", "ß": "ss",
                           "’": "", "'": "", "`": "", "‘": "", "-": " "})


def norm(s):
    """Minusculas, sin tildes ni apostrofos; guion = espacio."""
    s = unicodedata.normalize("NFKD", (s or "").translate(_TRANSLIT))
    s = s.encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def equipo(s):
    n = norm(s)
    return ALIAS.get(n, n)


def relacion_nombres(a, b):
    """'igual' (misma cadena normalizada, o solo cambian espacios), 'variante' (un nombre es una forma
    corta/larga del otro: cada palabra del mas corto es prefijo de una palabra del mas largo) o 'distinto'."""
    na, nb = norm(a), norm(b)
    if na == nb or na.replace(" ", "") == nb.replace(" ", ""):
        return "igual"
    ta, tb = na.split(), nb.split()
    corto, largo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if corto and all(any(w.startswith(c) for w in largo) for c in corto):
        return "variante"
    return "distinto"
