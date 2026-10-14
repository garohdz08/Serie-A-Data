"""Configuracion de temporada compartida por descargar_jornada.py, comparar.py y resumen.py.

La temporada se elige con la variable de entorno SERIE_A_TEMPORADA (por defecto 2025-26, que conserva
las rutas originales en datos/). Para otra temporada solo cambian el id de temporada de Sofascore, la
etiqueta contra la que se verifica y la carpeta de salida; la metodologia es la misma.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).parent
TEMPORADAS = {
    "2025-26": dict(sofa_season=76457, sofa_anio="25/26", datos=RAIZ / "datos"),
    "2024-25": dict(sofa_season=63515, sofa_anio="24/25", datos=RAIZ / "datos" / "2024-25"),
}
NOMBRE = os.environ.get("SERIE_A_TEMPORADA", "2025-26")
if NOMBRE not in TEMPORADAS:
    raise SystemExit(f"temporada desconocida {NOMBRE!r}; validas: {sorted(TEMPORADAS)}")
CFG = TEMPORADAS[NOMBRE]
