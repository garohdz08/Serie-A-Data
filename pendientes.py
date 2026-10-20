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
# reprogramado). Solo constan las confirmadas por prensa o aportadas por el usuario, por temporada.
NOMBRE_TEMP = CFG["datos"].name if CFG["datos"].name != "datos" else "2025-26"
def U19(repr_local):
    return ("NO ENCONTRADA. Una busqueda anterior indico 5-01-2025, pero Cowork no pudo verificarla y ninguna fuente lo dice; "
            "se descarta como dato. El calendario publicado el 1-11-2024 ya traia estos tres partidos el 14-15 enero "
            f"(Goal, Fantamaster, Calcio e Finanza), por lo que probablemente no hubo fecha original. Reprogramado: {repr_local}")


def U21(repr_local):
    return ("fin de semana del 20-21 enero 2024 (Toro News, Sportface); dia y hora originales NO ENCONTRADOS en busqueda con "
            "Cowork; probablemente nunca se fijaron (Fantacalcio, 22-12-2023, ya los listaba como aplazados). "
            f"Reprogramado (Toro News, Fantacalcio, Sportface): {repr_local}")


ORIGINALES = {
    "2024-25": {
        ("bologna", "ac milan"): "2024-10-26 (prensa: Sky Sport, calcioefinanza; partido de la 9a, aplazado por temporal)",
        ("como", "ac milan"): U19("martes 14-01-2025, 18:30"),
        ("atalanta", "juventus"): U19("martes 14-01-2025, 20:45"),
        ("inter", "bologna"): U19("miercoles 15-01-2025, 20:45"),
        ("fiorentina", "inter"): "2024-12-01 (prensa: Corriere dello Sport; suspendido en el 17' por el malestar de Bove, reanudado el 06-02-2025)",
    },
    "2023-24": {
        ("bologna", "fiorentina"): U21("miercoles 14-02-2024, 19:00"),
        ("torino", "lazio"): U21("jueves 22-02-2024, 20:45"),
        ("sassuolo", "napoli"): U21("miercoles 28-02-2024, 18:00"),
        ("inter", "atalanta"): U21("miercoles 28-02-2024, 20:45"),
        ("atalanta", "fiorentina"): "2024-03-17 18:00 local (prensa: fantacalcio.it, Lega Serie A; aplazado el mismo dia por el malestar de Joe Barone)",
        ("udinese", "as roma"): "2024-04-14 (prensa: Sky Sport; suspendido por el malestar de Ndicka con 1-1, reanudado el 25-04-2024; minuto de reanudacion no coincide entre medios: 71'-73')",
    },
}


def aplazados():
    """Lista TODOS los partidos reprogramados, en ambas fuentes, sin excluir ninguno:
      - eventos no finalizados (p.ej. 'postponed' en Sofascore): su fecha es la del evento aplazado; se
        enlaza con el gemelo disputado (mismo local-visitante) para dar la fecha real y su jornada;
      - eventos disputados cuya fecha UTC cae a mas de 5 dias de la mediana de su jornada (heuristica propia).
    Fecha original: la de ORIGINALES (prensa/usuario) o, si la otra fuente guarda el evento aplazado, la de ese evento."""
    from datetime import datetime
    todos = {}
    for f in FUENTES:
        todos[f] = []
        for ruta in sorted(JORNADAS.glob(f"{f}_partidos_j*.csv")):
            n = int(ruta.stem[-2:])
            ps = leer(ruta)
            ds = [datetime.strptime(p["fecha_utc"], "%Y-%m-%dT%H:%MZ") for p in ps]
            med = sorted(ds)[len(ds) // 2]
            for p, d in zip(ps, ds):
                todos[f].append(dict(p, jornada=n, _d=d, _med=med))
    no_final = {}
    for f in FUENTES:
        for p in todos[f]:
            if p["estado"] not in FINALES:
                no_final.setdefault(clave(p), []).append((f, p))
    filas = []
    for f in FUENTES:
        jugados = [p for p in todos[f] if p["estado"] in FINALES]
        for p in todos[f]:
            k = clave(p)
            if p["estado"] not in FINALES:
                gem = [q for q in jugados if clave(q) == k]
                filas.append(dict(fuente=f, jornada=p["jornada"], partido=f"{p['local']} - {p['visitante']}",
                                  partido_id=p["partido_id"], estado=p["estado"],
                                  fecha_real_utc=gem[0]["fecha_utc"] if gem else "",
                                  mediana_jornada=p["_med"].strftime("%Y-%m-%d"),
                                  fecha_original=f"{p['fecha_utc']} (fecha del evento '{p['estado']}' en {f}, id {p['partido_id']})",
                                  criterio="estado no finalizado; jornada del partido disputado: "
                                           + (str(gem[0]["jornada"]) if gem else "SIN GEMELO DISPUTADO"),
                                  jornada_partido_disputado=gem[0]["jornada"] if gem else ""))
            elif abs((p["_d"] - p["_med"]).days) > 5:
                orig = ORIGINALES.get(NOMBRE_TEMP, {}).get(k)
                if not orig and k in no_final:
                    orig = "; ".join(f"{q['fecha_utc']} (evento '{q['estado']}' de {fu}, id {q['partido_id']}, jornada {q['jornada']})"
                                     for fu, q in no_final[k])
                filas.append(dict(fuente=f, jornada=p["jornada"], partido=f"{p['local']} - {p['visitante']}",
                                  partido_id=p["partido_id"], estado=p["estado"],
                                  fecha_real_utc=p["fecha_utc"], mediana_jornada=p["_med"].strftime("%Y-%m-%d"),
                                  fecha_original=orig or "NO DISPONIBLE en las fuentes",
                                  criterio="fecha a mas de 5 dias de la mediana de la jornada",
                                  jornada_partido_disputado=p["jornada"]))
    escribir(DATOS / "aplazados.csv",
             ["fuente", "jornada", "partido", "partido_id", "estado", "fecha_real_utc", "mediana_jornada",
              "fecha_original", "criterio", "jornada_partido_disputado"], filas)
    return filas


if __name__ == "__main__":
    print(f"pares de nombres pendientes: {pares_nombres()}")
    ap = aplazados()
    print(f"eventos no disputados (aplazados/reprogramados): {len(ap)}")
    for a in ap:
        print("  ", a)
