#!/usr/bin/env python3
"""Compara ESPN vs Sofascore (Jornada 1) partido por partido y gol por gol, y valida cada fuente.

Lee datos/*_partidos_j1.csv y datos/*_goles_j1.csv (generados por descargar_jornada.py).
Escribe y imprime en crudo (CSV):
  datos/comparacion_j1.csv   nivel=PARTIDO|GOL, estado=COINCIDE|DISCREPA|SOLO_ESPN|SOLO_SOFASCORE
  datos/validaciones_j1.csv  una fila por chequeo fallido (o OK si todo pasa)
"""
import csv
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

D = Path(__file__).parent / "datos"
FUENTES = ("espn", "sofascore")

# Unica normalizacion de nombres de equipo entre fuentes (alias -> clave comun).
ALIAS = {"internazionale": "inter", "ssc napoli": "napoli"}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return " ".join(s.split())


def equipo(s):
    n = norm(s)
    return ALIAS.get(n, n)


def leer(nombre):
    with open(D / nombre, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clave(p):
    return (equipo(p["local"]), equipo(p["visitante"]))


def validar(fuente, partidos, goles):
    """Devuelve filas (fuente, partido, chequeo, detalle) por cada incumplimiento."""
    bad = []
    por_partido = defaultdict(list)
    for g in goles:
        por_partido[g["partido_id"]].append(g)
    for p in partidos:
        etiqueta = f"{p['local']} - {p['visitante']}"
        gs = por_partido[p["partido_id"]]
        gl = sum(1 for g in gs if g["equipo"] == p["local"])
        gv = sum(1 for g in gs if g["equipo"] == p["visitante"])
        if (gl, gv) != (int(p["goles_local"]), int(p["goles_visitante"])):
            bad.append((fuente, etiqueta, "suma_goles_vs_marcador",
                        f"marcador {p['goles_local']}-{p['goles_visitante']} pero goles listados {gl}-{gv}"))
        vistos = Counter((g["minuto_txt"], norm(g["goleador"]), g["equipo"]) for g in gs)
        for k, n in vistos.items():
            if n > 1:
                bad.append((fuente, etiqueta, "gol_duplicado", f"{k} x{n}"))
        for g in gs:
            m, a = int(g["minuto"]), int(g["anadido"])
            if not 1 <= m <= 120 or not 0 <= a <= 30:
                bad.append((fuente, etiqueta, "minuto_fuera_de_rango", f"{g['minuto_txt']} {g['goleador']}"))
            if g["equipo"] not in (p["local"], p["visitante"]):
                bad.append((fuente, etiqueta, "equipo_ajeno_al_partido", g["equipo"]))
    return bad


def emparejar(ge, gs):
    """Empareja goles de un mismo partido: exacto -> (equipo,minuto) -> (equipo,goleador) -> resto."""
    def k_ex(g): return (equipo(g["equipo"]), g["minuto_txt"], norm(g["goleador"]))
    def k_min(g): return (equipo(g["equipo"]), g["minuto_txt"])
    def k_nom(g): return (equipo(g["equipo"]), norm(g["goleador"]))
    pares, ge, gs = [], list(ge), list(gs)
    for kf in (k_ex, k_min, k_nom):
        for a in list(ge):
            b = next((x for x in gs if kf(x) == kf(a)), None)
            if b:
                pares.append((a, b)); ge.remove(a); gs.remove(b)
    pares += [(a, None) for a in ge] + [(None, b) for b in gs]
    return pares


def main():
    P = {f: leer(f"{f}_partidos_j1.csv") for f in FUENTES}
    G = {f: leer(f"{f}_goles_j1.csv") for f in FUENTES}

    # ---- validaciones por fuente
    val = []
    for f in FUENTES:
        val += validar(f, P[f], G[f])

    # ---- comparacion
    pe = {clave(p): p for p in P["espn"]}
    ps = {clave(p): p for p in P["sofascore"]}
    cols = ["nivel", "partido", "estado", "campos_discrepantes",
            "espn_valor", "sofascore_valor", "espn_id", "sofascore_id"]
    filas = []
    for k in sorted(set(pe) | set(ps), key=lambda k: (pe.get(k) or ps[k])["fecha_utc"] + str(k)):
        a, b = pe.get(k), ps.get(k)
        nombre = " - ".join((a or b)[x] for x in ("local", "visitante"))
        if not (a and b):
            filas.append(dict(nivel="PARTIDO", partido=nombre, estado="SOLO_ESPN" if a else "SOLO_SOFASCORE",
                              campos_discrepantes="partido", espn_id=a and a["partido_id"],
                              sofascore_id=b and b["partido_id"]))
            continue
        difs = []
        if a["fecha_utc"] != b["fecha_utc"]: difs.append(("fecha_utc", a["fecha_utc"], b["fecha_utc"]))
        ma, mb = f"{a['goles_local']}-{a['goles_visitante']}", f"{b['goles_local']}-{b['goles_visitante']}"
        if ma != mb: difs.append(("marcador", ma, mb))
        ge = [g for g in G["espn"] if g["partido_id"] == a["partido_id"]]
        gs = [g for g in G["sofascore"] if g["partido_id"] == b["partido_id"]]
        if len(ge) != len(gs): difs.append(("n_goles", len(ge), len(gs)))
        filas.append(dict(nivel="PARTIDO", partido=nombre, estado="DISCREPA" if difs else "COINCIDE",
                          campos_discrepantes="|".join(d[0] for d in difs),
                          espn_valor=f"{ma} ({len(ge)} goles)", sofascore_valor=f"{mb} ({len(gs)} goles)",
                          espn_id=a["partido_id"], sofascore_id=b["partido_id"]))
        for ga, gb in emparejar(ge, gs):
            if not (ga and gb):
                g = ga or gb
                filas.append(dict(nivel="GOL", partido=nombre,
                                  estado="SOLO_ESPN" if ga else "SOLO_SOFASCORE", campos_discrepantes="gol",
                                  **{("espn_valor" if ga else "sofascore_valor"):
                                     f"{g['minuto_txt']}' {g['goleador']} ({g['equipo']})"},
                                  espn_id=a["partido_id"], sofascore_id=b["partido_id"]))
                continue
            d = []
            if equipo(ga["equipo"]) != equipo(gb["equipo"]): d.append("equipo")
            if ga["minuto_txt"] != gb["minuto_txt"]: d.append("minuto")
            if norm(ga["goleador"]) != norm(gb["goleador"]): d.append("goleador")
            if ga["penal"] != gb["penal"]: d.append("penal")
            if ga["autogol"] != gb["autogol"]: d.append("autogol")
            fmt = lambda g: (f"{g['minuto_txt']}' {g['goleador']} ({g['equipo']})"
                             f"{' PEN' if g['penal'] == 'True' else ''}{' AUTOGOL' if g['autogol'] == 'True' else ''}")
            filas.append(dict(nivel="GOL", partido=nombre, estado="DISCREPA" if d else "COINCIDE",
                              campos_discrepantes="|".join(d), espn_valor=fmt(ga), sofascore_valor=fmt(gb),
                              espn_id=a["partido_id"], sofascore_id=b["partido_id"]))

    with open(D / "comparacion_j1.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(filas)
    with open(D / "validaciones_j1.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["fuente", "partido", "chequeo", "detalle"])
        w.writerows(val or [("todas", "", "OK", "suma=marcador, minutos 1-120, sin duplicados")])

    for nombre in ("comparacion_j1.csv", "validaciones_j1.csv"):
        print(f"### datos/{nombre}")
        print((D / nombre).read_text(encoding="utf-8"), end="")
    return 1 if val or any(r["estado"] != "COINCIDE" for r in filas) else 0


if __name__ == "__main__":
    sys.exit(main())
