#!/usr/bin/env python3
"""Listados aparte para decision humana, a partir de datos/jornadas y datos/comparacion_temporada.csv.

Escribe en la carpeta de la temporada (SERIE_A_TEMPORADA, ver temporada.py):
  pares_nombres_pendientes.csv  goles pareados cuyo goleador difiere solo por forma corta/larga
                                (goleador_variante) o es otra persona (goleador_distinto). Ninguno se
                                declara coincidencia automatica.
  aplazados.csv                 partidos reprogramados (fecha lejos de su jornada o no finalizados), con jornada,
                                fecha real de cada fuente y fecha original solo si la prensa la confirmo.
                                No se excluye ninguno en silencio.
"""
import csv
from pathlib import Path

from comparar import FINALES, clave
from temporada import CFG

DATOS = CFG["datos"]
JORNADAS = DATOS / "jornadas"
FUENTES = ("espn", "sofascore")


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def escribir(ruta, cols, filas):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)


def pares_nombres():
    ruta = DATOS / "pares_nombres_pendientes.csv"
    previo = {}
    if ruta.exists():           # no pisar decisiones ya tomadas por el usuario
        previo = {(r["jornada"], r["partido"], r["espn_valor"]): r for r in leer(ruta) if r["decision_usuario"]}
    filas = []
    for x in leer(DATOS / "comparacion_temporada.csv"):
        c = x["campos_discrepantes"]
        if x["nivel"] == "GOL" and ("goleador_variante" in c or "goleador_distinto" in c):
            filas.append(dict(jornada=x["jornada"], partido=x["partido"], campos=c,
                              espn_valor=x["espn_valor"], sofascore_valor=x["sofascore_valor"],
                              espn_id=x["espn_id"], sofascore_id=x["sofascore_id"], decision_usuario=""))
    for f in filas:
        f.update(previo.get((f["jornada"], f["partido"], f["espn_valor"]), {}))
    escribir(ruta, ["jornada", "partido", "campos", "espn_valor", "sofascore_valor", "espn_id", "sofascore_id",
                    "decision_usuario", "nombre_elegido"], filas)
    return len(filas)


# Fechas originales: NO vienen de ESPN ni de Sofascore (ninguna conserva la fecha original del evento
# reprogramado; ni el scoreboard de ESPN de esos dias los lista). Solo constan las que la prensa confirmo.
U19 = ("2025-01-05 (domingo). Aportado por el usuario tras su busqueda; "
       "no verificado por Claude (legaseriea.it inaccesible); coherente con la prensa: resto de la 19a el 4-5 enero")
ORIGINAL_PRENSA = {
    ("bologna", "ac milan"): ("2024-10-26 (prensa: Sky Sport, calcioefinanza; partido de la 9a, aplazado por temporal)", ),
    ("como", "ac milan"): (U19, ),
    ("atalanta", "juventus"): (U19, ),
    ("inter", "bologna"): (U19, ),
    ("fiorentina", "inter"): ("2024-12-01 (prensa: Corriere dello Sport; suspendido en el 17' por el malestar de Bove, reanudado el 06-02-2025)", ),
}
NO_CONFIRMADA = ("NO CONFIRMADA (prensa: solo da la fecha del recupero; el resto de la 19a se jugo el 4-5 enero; "
                 "legaseriea.it bloqueado por la red del entorno)")


def aplazados():
    """Un partido es reprogramado si su fecha UTC cae a mas de 5 dias de la mediana de su jornada
    (heuristica propia) o si su estado no es finalizado. Se listan todos, en ambas fuentes."""
    from datetime import datetime
    filas = []
    for f in FUENTES:
        for ruta in sorted(JORNADAS.glob(f"{f}_partidos_j*.csv")):
            n = int(ruta.stem[-2:])
            ps = leer(ruta)
            ds = [datetime.strptime(p["fecha_utc"], "%Y-%m-%dT%H:%MZ") for p in ps]
            med = sorted(ds)[len(ds) // 2]
            for p, d in zip(ps, ds):
                if p["estado"] in FINALES and abs((d - med).days) <= 5:
                    continue
                k = clave(p)
                orig = ORIGINAL_PRENSA.get(k, (NO_CONFIRMADA if n == 19 else "NO DISPONIBLE en las fuentes",))[0]
                filas.append(dict(fuente=f, jornada=n, partido=f"{p['local']} - {p['visitante']}",
                                  partido_id=p["partido_id"], estado=p["estado"],
                                  fecha_real_utc=p["fecha_utc"], mediana_jornada=med.strftime("%Y-%m-%d"),
                                  fecha_original=orig,
                                  criterio="estado no finalizado" if p["estado"] not in FINALES
                                  else "fecha a mas de 5 dias de la mediana de la jornada"))
    escribir(DATOS / "aplazados.csv",
             ["fuente", "jornada", "partido", "partido_id", "estado", "fecha_real_utc", "mediana_jornada",
              "fecha_original", "criterio"], filas)
    return filas


if __name__ == "__main__":
    print(f"pares de nombres pendientes: {pares_nombres()}")
    ap = aplazados()
    print(f"eventos no disputados (aplazados/reprogramados): {len(ap)}")
    for a in ap:
        print("  ", a)
