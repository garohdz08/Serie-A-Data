#!/usr/bin/env python3
"""Compara ESPN vs Sofascore partido por partido y gol por gol, y valida cada fuente.

Uso:
  python3 comparar.py --jornada 5      # lee datos/jornadas/*_jNN.csv, escribe comparacion_jNN.csv y validaciones_jNN.csv
  python3 comparar.py --todas          # junta las jornadas disponibles en datos/comparacion_temporada.csv y
                                       # datos/validaciones_temporada.csv

comparacion: nivel=PARTIDO|GOL, estado=COINCIDE|DISCREPA|SOLO_ESPN|SOLO_SOFASCORE.
validaciones (una fila por incumplimiento, o OK): suma de goles = marcador, minutos 1-120, sin duplicados.
La comparacion ignora tildes/mayusculas y alias de equipo (nombres.py); los valores crudos van en el CSV.
"""
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

from nombres import equipo, norm

DATOS = Path(__file__).parent / "datos"
JORNADAS = DATOS / "jornadas"
FUENTES = ("espn", "sofascore")
COMP_COLS = ["jornada", "nivel", "partido", "estado", "campos_discrepantes",
             "espn_valor", "sofascore_valor", "espn_id", "sofascore_id"]
VAL_COLS = ["jornada", "fuente", "partido", "chequeo", "detalle"]


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clave(p):
    return (equipo(p["local"]), equipo(p["visitante"]))


def validar(fuente, partidos, goles):
    """Devuelve (chequeo, partido, detalle) por cada incumplimiento."""
    bad = []
    por_partido = defaultdict(list)
    for g in goles:
        por_partido[g["partido_id"]].append(g)
    for p in partidos:
        etiqueta = f"{p['local']} - {p['visitante']}"
        gs = por_partido[p["partido_id"]]
        if p["goles_local"] == "" or p["goles_visitante"] == "":
            bad.append((etiqueta, "partido_sin_marcador", f"estado={p['estado']}"))
            continue
        gl = sum(1 for g in gs if g["equipo"] == p["local"])
        gv = sum(1 for g in gs if g["equipo"] == p["visitante"])
        if (gl, gv) != (int(p["goles_local"]), int(p["goles_visitante"])):
            bad.append((etiqueta, "suma_goles_vs_marcador",
                        f"marcador {p['goles_local']}-{p['goles_visitante']} pero goles listados {gl}-{gv}"))
        for k, c in Counter((g["minuto_txt"], norm(g["goleador"]), g["equipo"]) for g in gs).items():
            if c > 1:
                bad.append((etiqueta, "gol_duplicado", f"{k} x{c}"))
        for g in gs:
            m, a = int(g["minuto"]), int(g["anadido"])
            if not 1 <= m <= 120 or not 0 <= a <= 30:
                bad.append((etiqueta, "minuto_fuera_de_rango", f"{g['minuto_txt']} {g['goleador']}"))
            if g["equipo"] not in (p["local"], p["visitante"]):
                bad.append((etiqueta, "equipo_ajeno_al_partido", g["equipo"]))
    return bad


def emparejar(ge, gs):
    """Empareja goles de un partido: exacto -> (equipo,minuto) -> (equipo,goleador) -> resto sin pareja."""
    def k_ex(g): return (equipo(g["equipo"]), g["minuto_txt"], norm(g["goleador"]))
    def k_min(g): return (equipo(g["equipo"]), g["minuto_txt"])
    def k_nom(g): return (equipo(g["equipo"]), norm(g["goleador"]))
    pares, ge, gs = [], list(ge), list(gs)
    for kf in (k_ex, k_min, k_nom):
        for a in list(ge):
            b = next((x for x in gs if kf(x) == kf(a)), None)
            if b:
                pares.append((a, b)); ge.remove(a); gs.remove(b)
    return pares + [(a, None) for a in ge] + [(None, b) for b in gs]


def fmt(g):
    return (f"{g['minuto_txt']}' {g['goleador']} ({g['equipo']})"
            f"{' PEN' if g['penal'] == 'True' else ''}{' AUTOGOL' if g['autogol'] == 'True' else ''}")


def comparar_jornada(n):
    """Devuelve (filas_comparacion, filas_validacion) o None si faltan CSV."""
    rutas = {(f, t): JORNADAS / f"{f}_{t}_j{n:02d}.csv" for f in FUENTES for t in ("partidos", "goles")}
    faltan = [r.name for r in rutas.values() if not r.exists()]
    if faltan:
        print(f"J{n:02d}: faltan {faltan}; se omite", file=sys.stderr)
        return None
    P = {f: leer(rutas[f, "partidos"]) for f in FUENTES}
    G = {f: leer(rutas[f, "goles"]) for f in FUENTES}
    val = [dict(jornada=n, fuente=f, partido=pt, chequeo=ch, detalle=d)
           for f in FUENTES for pt, ch, d in validar(f, P[f], G[f])]
    pe, ps = {clave(p): p for p in P["espn"]}, {clave(p): p for p in P["sofascore"]}
    filas = []
    for k in sorted(set(pe) | set(ps), key=lambda k: (pe.get(k) or ps[k])["fecha_utc"] + str(k)):
        a, b = pe.get(k), ps.get(k)
        nombre = " - ".join((a or b)[x] for x in ("local", "visitante"))
        if not (a and b):
            filas.append(dict(jornada=n, nivel="PARTIDO", partido=nombre,
                              estado="SOLO_ESPN" if a else "SOLO_SOFASCORE", campos_discrepantes="partido",
                              espn_id=a and a["partido_id"], sofascore_id=b and b["partido_id"]))
            continue
        ge = [g for g in G["espn"] if g["partido_id"] == a["partido_id"]]
        gs = [g for g in G["sofascore"] if g["partido_id"] == b["partido_id"]]
        ma, mb = f"{a['goles_local']}-{a['goles_visitante']}", f"{b['goles_local']}-{b['goles_visitante']}"
        difs = []
        if a["fecha_utc"] != b["fecha_utc"]: difs.append("fecha_utc")
        if ma != mb: difs.append("marcador")
        if len(ge) != len(gs): difs.append("n_goles")
        filas.append(dict(jornada=n, nivel="PARTIDO", partido=nombre, estado="DISCREPA" if difs else "COINCIDE",
                          campos_discrepantes="|".join(difs),
                          espn_valor=f"{a['fecha_utc']} {ma} ({len(ge)} goles)",
                          sofascore_valor=f"{b['fecha_utc']} {mb} ({len(gs)} goles)",
                          espn_id=a["partido_id"], sofascore_id=b["partido_id"]))
        for ga, gb in emparejar(ge, gs):
            if not (ga and gb):
                g = ga or gb
                filas.append(dict(jornada=n, nivel="GOL", partido=nombre,
                                  estado="SOLO_ESPN" if ga else "SOLO_SOFASCORE", campos_discrepantes="gol",
                                  **{"espn_valor" if ga else "sofascore_valor": fmt(g)},
                                  espn_id=a["partido_id"], sofascore_id=b["partido_id"]))
                continue
            d = [c for c, bad in (("equipo", equipo(ga["equipo"]) != equipo(gb["equipo"])),
                                  ("minuto", ga["minuto_txt"] != gb["minuto_txt"]),
                                  ("goleador", norm(ga["goleador"]) != norm(gb["goleador"])),
                                  ("penal", ga["penal"] != gb["penal"]),
                                  ("autogol", ga["autogol"] != gb["autogol"])) if bad]
            filas.append(dict(jornada=n, nivel="GOL", partido=nombre, estado="DISCREPA" if d else "COINCIDE",
                              campos_discrepantes="|".join(d), espn_valor=fmt(ga), sofascore_valor=fmt(gb),
                              espn_id=a["partido_id"], sofascore_id=b["partido_id"]))
    return filas, val


def escribir(ruta, cols, filas):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        if not filas and cols is VAL_COLS:
            filas = [dict(jornada="todas", chequeo="OK", detalle="suma=marcador, minutos 1-120, sin duplicados")]
        w.writerows(filas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jornada", type=int)
    ap.add_argument("--todas", action="store_true")
    a = ap.parse_args()
    jornadas = range(1, 39) if a.todas else [a.jornada or 1]
    comp, val = [], []
    for n in jornadas:
        r = comparar_jornada(n)
        if r is None:
            continue
        comp += r[0]; val += r[1]
        if not a.todas:
            escribir(JORNADAS / f"comparacion_j{n:02d}.csv", COMP_COLS, r[0])
            escribir(JORNADAS / f"validaciones_j{n:02d}.csv", VAL_COLS, r[1])
    if a.todas:
        escribir(DATOS / "comparacion_temporada.csv", COMP_COLS, comp)
        escribir(DATOS / "validaciones_temporada.csv", VAL_COLS, val)
    malos = [r for r in comp if r["estado"] != "COINCIDE"]
    print(f"comparacion: {len(comp)} filas, {len(malos)} no coinciden; validaciones: {len(val)} incumplimientos")
    return 1 if malos or val else 0


if __name__ == "__main__":
    sys.exit(main())
