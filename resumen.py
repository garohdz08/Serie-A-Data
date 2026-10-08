#!/usr/bin/env python3
"""Resumen de la temporada a partir de datos/jornadas, datos/crudo y datos/fallos.csv.

Imprime y guarda datos/resumen_temporada.txt: partidos totales y por equipo, goles, penales y autogoles
por fuente, discrepancias de la comparacion, eventos de ESPN sin jornada, y llamadas fallidas.
"""
import csv
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

from nombres import equipo

DATOS = Path(__file__).parent / "datos"
JORNADAS = DATOS / "jornadas"
FUENTES = ("espn", "sofascore")
out = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    out.append(s)


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def juntar(fuente, tipo):
    filas = []
    for n in range(1, 39):
        r = JORNADAS / f"{fuente}_{tipo}_j{n:02d}.csv"
        if r.exists():
            filas += [dict(f, jornada=n) for f in leer(r)]
    return filas


def main():
    P = {f: juntar(f, "partidos") for f in FUENTES}
    G = {f: juntar(f, "goles") for f in FUENTES}
    p("== Jornadas con CSV por fuente (de 38)")
    for f in FUENTES:
        p(f"{f}: {len({x['jornada'] for x in P[f]})} jornadas")

    p("\n== Partidos totales (esperado 380)")
    for f in FUENTES:
        ids = {x["partido_id"] for x in P[f]}
        pares = {(equipo(x["local"]), equipo(x["visitante"])) for x in P[f]}
        p(f"{f}: filas={len(P[f])} ids_unicos={len(ids)} pares_local-visitante_unicos={len(pares)}")
        por_estado = Counter(x["estado"] for x in P[f])
        p(f"   estados: {dict(por_estado)}")

    p("\n== Partidos por equipo (esperado 38 cada uno)")
    for f in FUENTES:
        c = Counter()
        for x in P[f]:
            c[equipo(x["local"])] += 1
            c[equipo(x["visitante"])] += 1
        malos = {e: n for e, n in c.items() if n != 38}
        p(f"{f}: {len(c)} equipos; con != 38: {malos if malos else 'ninguno'}")
        if malos or len(c) != 20:
            p(f"   recuento completo: {dict(sorted(c.items()))}")

    p("\n== Goles, penales y autogoles por fuente")
    p("fuente,goles,penales,autogoles,suma_marcadores")
    for f in FUENTES:
        suma = sum(int(x["goles_local"]) + int(x["goles_visitante"]) for x in P[f] if x["goles_local"] != "")
        p(f"{f},{len(G[f])},{sum(g['penal'] == 'True' for g in G[f])},"
          f"{sum(g['autogol'] == 'True' for g in G[f])},{suma}")

    comp_r = DATOS / "comparacion_temporada.csv"
    val_r = DATOS / "validaciones_temporada.csv"
    p("\n== Comparacion ESPN vs Sofascore")
    if comp_r.exists():
        comp = leer(comp_r)
        c = Counter((x["nivel"], x["estado"]) for x in comp)
        p("nivel,estado,filas")
        for (nivel, estado), n in sorted(c.items()):
            p(f"{nivel},{estado},{n}")
        p("\n-- Discrepancias (todas las filas que no COINCIDEN), CSV crudo")
        w = csv.writer(sys.stdout, lineterminator="\n")
        cols = ["jornada", "nivel", "partido", "estado", "campos_discrepantes", "espn_valor", "sofascore_valor"]
        p(",".join(cols))
        for x in comp:
            if x["estado"] != "COINCIDE":
                p(",".join('"' + (x[k] or "").replace('"', '""') + '"' for k in cols))
        c2 = Counter(x["campos_discrepantes"] for x in comp if x["estado"] != "COINCIDE")
        p(f"\nresumen por tipo: {dict(c2)}")
    else:
        p("(falta comparacion_temporada.csv: ejecutar comparar.py --todas)")

    p("\n== Validaciones (suma=marcador, minutos 1-120, sin duplicados)")
    if val_r.exists():
        v = leer(val_r)
        if len(v) == 1 and v[0]["chequeo"] == "OK":
            p("OK en todas las jornadas y fuentes")
        else:
            for x in v:
                p(",".join(f'"{x[k]}"' for k in ("jornada", "fuente", "partido", "chequeo", "detalle")))

    p("\n== Eventos de ESPN en los scoreboard descargados que no estan en ninguna jornada")
    vistos = {x["partido_id"] for x in P["espn"]}
    ajenos = []
    for r in sorted((DATOS / "crudo" / "espn").glob("scoreboard_*.json.gz")):
        for e in json.loads(gzip.open(r).read())["events"]:
            if e["id"] not in vistos:
                c = {t["homeAway"]: t["team"]["displayName"] for t in e["competitions"][0]["competitors"]}
                ajenos.append((r.name[11:19], e["id"], c["home"], c["away"], e["status"]["type"]["name"]))
    p(f"{len(ajenos)} eventos" + (":" if ajenos else ""))
    for a in ajenos:
        p("  ", a)

    p("\n== Llamadas fallidas (datos/fallos.csv)")
    fr = DATOS / "fallos.csv"
    if not fr.exists():
        p("ninguna (no existe fallos.csv)")
    else:
        f = leer(fr)
        p(f"{len(f)} registros")
        for x in f:
            resuelto = (DATOS / "crudo" / x["crudo"]).exists()
            p(f"  {x['ts_utc']} host={x['host']} codigo={x['codigo']} intentos={x['intentos']} "
              f"{x['contexto']} {x['url']} -> {'resuelta despues' if resuelto else 'SIGUE SIN DESCARGAR'}")
    (DATOS / "resumen_temporada.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
