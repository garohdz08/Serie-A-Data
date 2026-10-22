#!/usr/bin/env python3
"""Auditoria de las 5 temporadas (2021-22 a 2025-26), calculada SOLO a partir de los archivos del repositorio.

Lee, por temporada (rutas en temporada.py): jornadas/{espn,sofascore}_{partidos,goles}_jNN.csv, fallos.csv,
aplazados.csv y comparacion_temporada.csv. No usa memoria ni informes anteriores.

Salida (stdout y archivos):
  datos/auditoria_5_temporadas.txt        todas las tablas tal cual
  datos/discrepancias_5_temporadas.csv    una fila por diferencia ESPN vs Sofascore (resuelta / abierta)
  datos/pares_nombres_5_temporadas.csv    pares de nombres distintos, SIN unificar
"""
import csv
import io
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from nombres import equipo, norm
from temporada import TEMPORADAS

RAIZ = Path(__file__).parent
ORDEN = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
FUENTES = ("espn", "sofascore")
FINALES = {"finished", "STATUS_FULL_TIME"}
RX_NOM = re.compile(r"^\d+(?:\+\d+)?' (.+?) \((.+?)\)(?: PEN| AUTOGOL)*$")
SALIDA = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    SALIDA.append(s)


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cargar(s):
    D = TEMPORADAS[s]["datos"]
    J = D / "jornadas"
    P = {f: [] for f in FUENTES}
    G = {f: [] for f in FUENTES}
    faltan = []
    for n in range(1, 39):
        for f in FUENTES:
            for tipo, dest in (("partidos", P), ("goles", G)):
                r = J / f"{f}_{tipo}_j{n:02d}.csv"
                if not r.exists():
                    faltan.append(r.name)
                    continue
                dest[f] += [dict(x, jornada=n) for x in leer(r)]
    return D, P, G, faltan


def fmt_gol(g):
    return (f"{g['minuto_txt']}' {g['goleador']} ({g['equipo']})"
            f"{' PEN' if g['penal'] == 'True' else ''}{' AUTOGOL' if g['autogol'] == 'True' else ''}")


def tabla(cols, filas):
    ancho = [max(len(str(c)), *(len(str(r[i])) for r in filas)) if filas else len(str(c)) for i, c in enumerate(cols)]
    p("  ".join(str(c).ljust(ancho[i]) for i, c in enumerate(cols)))
    p("  ".join("-" * a for a in ancho))
    for r in filas:
        p("  ".join(str(x).ljust(ancho[i]) for i, x in enumerate(r)))


# --------------------------------------------------------------------------------------------- 2. tablas
def tabla_resumen(datos):
    p("=" * 100)
    p("2. TABLA POR TEMPORADA Y FUENTE (partidos disputados = estado final; 'filas' incluye eventos no disputados)")
    p("=" * 100)
    filas = []
    detalle_equipos = []
    for s in ORDEN:
        D, P, G, faltan = datos[s]
        fallos = D / "fallos.csv"
        nf = leer(fallos) if fallos.exists() else []
        sin_desc = sum(1 for x in nf if not (D / "crudo" / x["crudo"]).exists())
        for f in FUENTES:
            disp = [x for x in P[f] if x["estado"] in FINALES]
            ids = {x["partido_id"] for x in P[f]}
            cnt = Counter()
            for x in disp:
                cnt[x["local"]] += 1
                cnt[x["visitante"]] += 1
            malos = {e: n for e, n in cnt.items() if n != 38}
            g = G[f]
            suma = sum(int(x["goles_local"]) + int(x["goles_visitante"]) for x in disp if x["goles_local"] != "")
            cero = sum(1 for x in disp if x["goles_local"] == "0" and x["goles_visitante"] == "0")
            filas.append([s, f, len(P[f]), len(disp), len(ids), len(cnt), len(malos), len(g),
                          sum(x["penal"] == "True" for x in g), sum(x["autogol"] == "True" for x in g),
                          suma, cero, len(nf), sin_desc])
            if malos or len(cnt) != 20:
                detalle_equipos.append((s, f, malos, dict(sorted(cnt.items()))))
            if faltan:
                detalle_equipos.append((s, f, "CSV FALTANTES", faltan))
    tabla(["temporada", "fuente", "filas", "partidos(380)", "ids_unicos", "equipos(20)", "equipos!=38", "goles",
           "penales", "autogoles", "suma_marcadores", "0-0", "llamadas_fallidas", "sin_descargar"], filas)
    p("")
    p("Equipos que no cumplen 38 partidos (o temporadas con != 20 equipos):",
      "NINGUNO" if not detalle_equipos else "")
    for d in detalle_equipos:
        p("  ", d)


# --------------------------------------------------------------------------------------------- 3. validaciones
def validar(f, P, G):
    mal = []
    por = defaultdict(list)
    for g in G:
        por[g["partido_id"]].append(g)
    for x in P:
        if x["estado"] not in FINALES:
            continue
        gs = por[x["partido_id"]]
        et = f"{x['local']} - {x['visitante']}"
        if x["goles_local"] == "" or x["goles_visitante"] == "":
            mal.append((x["jornada"], et, "partido_sin_marcador", f"estado={x['estado']}"))
            continue
        gl = sum(1 for g in gs if g["equipo"] == x["local"])
        gv = sum(1 for g in gs if g["equipo"] == x["visitante"])
        ml, mv = int(x["goles_local"]), int(x["goles_visitante"])
        if (gl, gv) != (ml, mv):
            mal.append((x["jornada"], et, "suma_goles_vs_marcador",
                        f"marcador crudo {ml}-{mv}; goles listados {gl}-{gv}: "
                        + (" | ".join(fmt_gol(g) for g in gs) or "(ninguno)")))
        for g in gs:
            m = int(g["minuto"])
            if not 1 <= m <= 120:
                mal.append((x["jornada"], et, "minuto_fuera_de_1-120", fmt_gol(g)))
            if g["equipo"] not in (x["local"], x["visitante"]):
                mal.append((x["jornada"], et, "equipo_ajeno_al_partido", fmt_gol(g)))
        for k, c in Counter((g["minuto_txt"], norm(g["goleador"]), g["equipo"]) for g in gs).items():
            if c > 1:
                mal.append((x["jornada"], et, "gol_duplicado", f"{k} x{c}"))
    return mal


def seccion_validaciones(datos):
    p("")
    p("=" * 100)
    p("3. VALIDACIONES (suma de goles = marcador; minuto entre 1 y 120; sin goles duplicados; equipo del partido)")
    p("=" * 100)
    for s in ORDEN:
        _, P, G, _ = datos[s]
        for f in FUENTES:
            mal = validar(f, P[f], G[f])
            p(f"{s} {f}: " + ("OK, 0 incumplimientos" if not mal else f"{len(mal)} incumplimiento(s)"))
            for m in mal:
                p(f"   J{m[0]} | {m[1]} | {m[2]} | {m[3]}")


# --------------------------------------------------------------------------------------------- 4. aplazados
def seccion_aplazados(datos):
    p("")
    p("=" * 100)
    p("4. PARTIDOS APLAZADOS / REPROGRAMADOS (no finalizados, o fecha a mas de 5 dias de la mediana de su jornada)")
    p("=" * 100)
    for s in ORDEN:
        D, P, _, _ = datos[s]
        enlazar = {}
        por_clave = defaultdict(lambda: {"ev": [], "disp": {}})
        total_calc = Counter()
        for f in FUENTES:
            rondas = defaultdict(list)
            for x in P[f]:
                rondas[x["jornada"]].append(x)
            for n, ps in rondas.items():
                ds = sorted(datetime.strptime(x["fecha_utc"], "%Y-%m-%dT%H:%MZ") for x in ps)
                med = ds[len(ds) // 2]
                for x in ps:
                    d = datetime.strptime(x["fecha_utc"], "%Y-%m-%dT%H:%MZ")
                    k = (equipo(x["local"]), equipo(x["visitante"]))
                    if x["estado"] not in FINALES:
                        por_clave[k]["ev"].append((f, x))
                        total_calc[f] += 1
                    elif abs((d - med).days) > 5:
                        por_clave[k]["disp"][f] = x
                        total_calc[f] += 1
        # gemelo disputado de cada evento no finalizado
        for k, v in por_clave.items():
            for f in FUENTES:
                if f not in v["disp"] and v["ev"]:
                    for x in P[f]:
                        if x["estado"] in FINALES and (equipo(x["local"]), equipo(x["visitante"])) == k:
                            v["disp"].setdefault(f, x)
        arch = D / "aplazados.csv"
        filas_arch = leer(arch) if arch.exists() else []
        cnt_arch = Counter(r["fuente"] for r in filas_arch)
        p(f"--- {s}: {sum(total_calc.values())} filas calculadas ({dict(total_calc)}); "
          f"aplazados.csv: {len(filas_arch)} filas ({dict(cnt_arch)}) -> "
          + ("COINCIDE" if dict(total_calc) == dict(cnt_arch) else "NO COINCIDE"))
        if not por_clave:
            p("   (ninguno)")
            continue
        filas = []
        for k, v in sorted(por_clave.items(), key=lambda kv: min(x["fecha_utc"] for x in
                                                                 [y for _, y in kv[1]["ev"]] + list(kv[1]["disp"].values()))):
            nom = None
            for f in FUENTES:
                if f in v["disp"]:
                    nom = f"{v['disp'][f]['local']} - {v['disp'][f]['visitante']}"
                    break
            nom = nom or f"{v['ev'][0][1]['local']} - {v['ev'][0][1]['visitante']}"
            real = "; ".join(f"{f}: {v['disp'][f]['fecha_utc']} (J{v['disp'][f]['jornada']}, id {v['disp'][f]['partido_id']})"
                             for f in FUENTES if f in v["disp"]) or "SIN PARTIDO DISPUTADO"
            evs = "; ".join(f"{f}: {x['fecha_utc']} estado={x['estado']} (J{x['jornada']}, id {x['partido_id']})"
                            for f, x in v["ev"]) or "-"
            filas.append([nom, real, evs])
        tabla(["partido", "fecha real jugada (UTC) y jornada asignada", "eventos no disputados en las fuentes (fecha del evento)"], filas)
        for r in sorted({(x["partido"], x["fecha_original"]) for x in filas_arch if x["fuente"] == "espn"}):
            p(f"   fecha_original registrada [{r[0]}]: {r[1]}")
        sin_espn = sorted({(x["partido"], x["fecha_original"]) for x in filas_arch if x["fuente"] == "sofascore"}
                          - set())
        if not any(x["fuente"] == "espn" for x in filas_arch):
            for r in sin_espn:
                p(f"   fecha_original registrada (solo en Sofascore) [{r[0]}]: {r[1]}")


# --------------------------------------------------------------------------------------------- 5. discrepancias
def seccion_discrepancias(datos):
    p("")
    p("=" * 100)
    p("5. DISCREPANCIAS ESPN vs SOFASCORE -> datos/discrepancias_5_temporadas.csv")
    p("=" * 100)
    filas = []
    incoherentes = []
    for s in ORDEN:
        D, P, G, _ = datos[s]
        comp = leer(D / "comparacion_temporada.csv")
        # comprobacion de completitud: cada gol de cada fuente aparece en la comparacion
        for f in FUENTES:
            n_comp = sum(1 for r in comp if r["nivel"] == "GOL" and r[f"{f}_valor"] != "")
            p(f"{s}: goles {f} en CSV de jornadas={len(G[f])}; en comparacion_temporada.csv={n_comp}"
              + ("" if n_comp == len(G[f]) else "   <-- NO CUADRA"))
        # recomputo independiente: partidos cuyos goles difieren en (equipo, minuto, penal, autogol)
        def firma(f):
            d = defaultdict(list)
            pid2k = {x["partido_id"]: (equipo(x["local"]), equipo(x["visitante"])) for x in P[f] if x["estado"] in FINALES}
            for g in G[f]:
                if g["partido_id"] in pid2k:
                    d[pid2k[g["partido_id"]]].append((equipo(g["equipo"]), g["minuto_txt"], g["penal"], g["autogol"]))
            return {k: sorted(v) for k, v in d.items()}, set(pid2k.values())
        fe, ke = firma("espn")
        fs, ks = firma("sofascore")
        difieren = {k for k in ke & ks if fe.get(k, []) != fs.get(k, [])}
        en_comp = {r["partido"] for r in comp if r["estado"] != "COINCIDE"
                   and any(c in r["campos_discrepantes"].split("|")
                           for c in ("minuto", "penal", "autogol", "equipo", "gol", "n_goles"))}
        p(f"{s}: partidos con goles distintos en (equipo, minuto, tipo) recomputados={len(difieren)}; "
          f"partidos distintos con esas diferencias en la comparacion={len(en_comp)}"
          + ("" if len(difieren) == len(en_comp) else "   <-- NO CUADRA"))
        for r in comp:
            if r["estado"] == "COINCIDE":
                continue
            resuelta = r["estado"] == "RESUELTO_POR_USUARIO"
            if resuelta and r.get("nombre_elegido"):          # el nombre elegido debe ser uno de los dos nombres crudos
                e, s2 = RX_NOM.match(r["espn_valor"]), RX_NOM.match(r["sofascore_valor"])
                if not e or not s2 or r["nombre_elegido"] not in (e.group(1), s2.group(1)):
                    incoherentes.append((s, r["jornada"], r["partido"], r["espn_valor"], r["sofascore_valor"], r["nombre_elegido"]))
            filas.append(dict(temporada=s, jornada=r["jornada"], nivel=r["nivel"], partido=r["partido"],
                              tipo=r["campos_discrepantes"], valor_espn=r["espn_valor"],
                              valor_sofascore=r["sofascore_valor"],
                              estado="resuelta" if resuelta else "abierta", estado_en_comparacion=r["estado"],
                              resolucion=r.get("decision_usuario", ""), espn_id=r["espn_id"], sofascore_id=r["sofascore_id"]))
    p("")
    p(f"Comprobacion: nombre_elegido registrado distinto de los dos nombres crudos: {len(incoherentes)} caso(s)")
    for x in incoherentes:
        p("   ", x)
    cols = ["temporada", "jornada", "nivel", "partido", "tipo", "valor_espn", "valor_sofascore", "estado",
            "estado_en_comparacion", "resolucion", "espn_id", "sofascore_id"]
    with open(RAIZ / "datos" / "discrepancias_5_temporadas.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)
    p("")
    p("Filas por temporada / nivel / estado:")
    for k, v in sorted(Counter((x["temporada"], x["nivel"], x["estado"]) for x in filas).items()):
        p("  ", k, v)
    p("Filas por tipo:", dict(sorted(Counter(x["tipo"] for x in filas).items())))
    p("")
    p("--- CONTENIDO COMPLETO de datos/discrepancias_5_temporadas.csv (campos: temporada, jornada, nivel, partido, tipo, "
      "valor_espn, valor_sofascore, estado, estado_en_comparacion) ---")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["temporada", "jornada", "nivel", "partido", "tipo", "valor_espn", "valor_sofascore", "estado",
                "estado_en_comparacion"])
    for x in filas:
        w.writerow([x[c] for c in ("temporada", "jornada", "nivel", "partido", "tipo", "valor_espn", "valor_sofascore",
                                   "estado", "estado_en_comparacion")])
    p(buf.getvalue().rstrip("\n"))
    return filas


# --------------------------------------------------------------------------------------------- 6. nombres
def seccion_nombres(filas):
    p("")
    p("=" * 100)
    p("6. PARES DE NOMBRES DISTINTOS (sin unificar; tipo = el que marca la comparacion) -> datos/pares_nombres_5_temporadas.csv")
    p("=" * 100)
    rx = re.compile(r"^\d+(?:\+\d+)?' (.+?) \((.+?)\)(?: PEN| AUTOGOL)*$")
    pares = defaultdict(lambda: {"n": 0, "temps": set(), "tipos": set()})
    for x in filas:
        if x["nivel"] != "GOL" or "goleador_" not in x["tipo"]:
            continue
        e, s = rx.match(x["valor_espn"]), rx.match(x["valor_sofascore"])
        k = (e.group(1), s.group(1))
        pares[k]["n"] += 1
        pares[k]["temps"].add(x["temporada"])
        pares[k]["tipos"].update(c for c in x["tipo"].split("|") if c.startswith("goleador_"))
    out = [[a, b, "/".join(sorted(v["tipos"])), v["n"], ", ".join(sorted(v["temps"]))]
           for (a, b), v in sorted(pares.items(), key=lambda kv: norm(kv[0][1]))]
    tabla(["nombre ESPN", "nombre Sofascore", "tipo", "casos", "temporadas"], out)
    p(f"Total: {len(out)} pares distintos, {sum(v['n'] for v in pares.values())} casos.")
    with open(RAIZ / "datos" / "pares_nombres_5_temporadas.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["nombre_espn", "nombre_sofascore", "tipo", "casos", "temporadas"])
        w.writerows(out)


def main():
    datos = {s: cargar(s) for s in ORDEN}
    p("AUDITORIA 5 TEMPORADAS (calculada de los CSV del repositorio)")
    tabla_resumen(datos)
    seccion_validaciones(datos)
    seccion_aplazados(datos)
    filas = seccion_discrepancias(datos)
    seccion_nombres(filas)
    (RAIZ / "datos" / "auditoria_5_temporadas.txt").write_text("\n".join(SALIDA) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
