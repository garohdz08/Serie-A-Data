#!/usr/bin/env python3
"""Descarga jornadas de la Serie A 2025-26 desde ESPN y Sofascore (APIs JSON).

Uso:
  python3 descargar_jornada.py --jornada 5
  python3 descargar_jornada.py --desde 1 --hasta 38      # o --todas
  opciones: --pausa 1.0 (seg. minimos entre llamadas de red), --forzar (rehacer CSV)

Salida:
  datos/crudo/{fuente}/*.json.gz          respuesta JSON cruda de CADA llamada (cuerpo tal cual, gzip)
  datos/jornadas/{fuente}_partidos_jNN.csv  una fila por partido (incluye 0-0)
  datos/jornadas/{fuente}_goles_jNN.csv     una fila por gol
  datos/fallos.csv                        cada llamada que agoto sus reintentos (host, codigo, url)

Reanudable: una llamada cuya respuesta cruda ya existe no se repite, y una jornada cuyos
CSV existen se omite. Reintentos con espera creciente (2,4,8,16,32 s; respeta Retry-After)
ante 429/403/5xx/timeout/errores de conexion. Si una llamada falla del todo, esa fuente
no escribe CSV de esa jornada (no se inventa ni se completa nada) y se registra en fallos.csv.

Convenciones: equipo = equipo al que se acredita el gol (en un autogol, el beneficiario);
minuto = minuto base, anadido = tiempo anadido, minuto_txt = "45+2".
"""
import argparse
import csv
import gzip
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from nombres import equipo as clave_equipo

SOFA_TOURNAMENT = 23          # Serie A
SOFA_SEASON = 76457           # 25/26 (se verifica contra /seasons: year == "25/26")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1"
SOFA = "https://api.sofascore.com/api/v1"
RAIZ = Path(__file__).parent
DATOS = RAIZ / "datos"
CRUDO = DATOS / "crudo"
JORNADAS = DATOS / "jornadas"
FALLOS = DATOS / "fallos.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
           "Accept": "application/json"}
TIMEOUT = 20
ESPERAS = [2, 4, 8, 16, 32]                      # segundos antes de cada reintento
REINTENTABLES = {403, 429, 500, 502, 503, 504}

PARTIDO_COLS = ["fuente", "partido_id", "fecha_utc", "local", "visitante",
                "goles_local", "goles_visitante", "estado"]
GOL_COLS = ["fuente", "partido_id", "fecha_utc", "local", "visitante", "gol_n",
            "minuto_txt", "minuto", "anadido", "goleador", "equipo", "penal", "autogol",
            "marcador_local_tras_gol", "marcador_visitante_tras_gol", "nota"]
FALLO_COLS = ["ts_utc", "fuente", "host", "codigo", "intentos", "url", "crudo", "contexto"]


class FetchError(Exception):
    def __init__(self, fuente, nombre, url, codigo, intentos):
        self.fuente, self.nombre, self.url, self.codigo, self.intentos = fuente, nombre, url, codigo, intentos
        self.host = urlparse(url).netloc
        super().__init__(f"host={self.host} codigo={codigo} intentos={intentos} url={url}")


class DatoIncoherente(Exception):
    pass


class Cliente:
    def __init__(self, pausa):
        self.pausa = pausa
        self.ultima = 0.0
        self.sesion = requests.Session()
        self.sesion.headers.update(HEADERS)
        self.llamadas = 0          # llamadas de red hechas (no cuenta el cache)
        self.cacheadas = 0

    def _ruta(self, fuente, nombre):
        return CRUDO / fuente / f"{nombre}.json.gz"

    def get(self, fuente, nombre, url, params=None, contexto=""):
        ruta = self._ruta(fuente, nombre)
        if ruta.exists():                                    # reanudar: no repetir
            self.cacheadas += 1
            with gzip.open(ruta, "rb") as f:
                return json.loads(f.read())
        ultimo = None
        for intento in range(len(ESPERAS) + 1):
            espera_pausa = self.pausa - (time.monotonic() - self.ultima)
            if espera_pausa > 0:
                time.sleep(espera_pausa)
            self.ultima = time.monotonic()
            self.llamadas += 1
            retry_after = None
            try:
                r = self.sesion.get(url, params=params, timeout=TIMEOUT)
                if r.status_code == 200:
                    try:
                        datos = r.json()
                    except ValueError:
                        ultimo = "200-no-JSON"
                    else:
                        ruta.parent.mkdir(parents=True, exist_ok=True)
                        tmp = ruta.with_suffix(".tmp")
                        with gzip.open(tmp, "wb") as f:
                            f.write(r.content)
                        tmp.replace(ruta)
                        return datos
                else:
                    ultimo = r.status_code
                    if r.status_code not in REINTENTABLES:
                        break
                    ra = r.headers.get("Retry-After", "")
                    retry_after = int(ra) if ra.isdigit() else None
            except requests.Timeout:
                ultimo = "timeout"
            except requests.RequestException as e:
                m = re.search(r"\b(40\d|50\d)\b", str(e))
                ultimo = f"conexion:{type(e).__name__}" + (f":{m.group(1)}" if m else "")
            if intento < len(ESPERAS):
                time.sleep(max(ESPERAS[intento], retry_after or 0))
        err = FetchError(fuente, nombre, url, ultimo, intento + 1)
        self._registrar(err, contexto)
        raise err

    def _registrar(self, err, contexto):
        DATOS.mkdir(exist_ok=True)
        nuevo = not FALLOS.exists()
        with open(FALLOS, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(FALLO_COLS)
            w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), err.fuente, err.host,
                        err.codigo, err.intentos, err.url, f"{err.fuente}/{err.nombre}.json.gz", contexto])


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def minuto_txt(base, anadido):
    return f"{base}+{anadido}" if anadido else str(base)


# ---------------------------------------------------------------- Sofascore
def verificar_temporada(cli):
    data = cli.get("sofascore", "temporadas", f"{SOFA}/unique-tournament/{SOFA_TOURNAMENT}/seasons")
    anio = next((s["year"] for s in data["seasons"] if s["id"] == SOFA_SEASON), None)
    if anio != "25/26":
        raise DatoIncoherente(f"season id {SOFA_SEASON} no es 25/26 (es {anio})")


def sofascore(cli, n):
    ctx = f"jornada {n}"
    partidos, goles = [], []
    ronda = cli.get("sofascore", f"ronda_{n:02d}",
                    f"{SOFA}/unique-tournament/{SOFA_TOURNAMENT}/season/{SOFA_SEASON}/events/round/{n}", contexto=ctx)
    for ev in ronda["events"]:
        eid = ev["id"]
        fecha = iso(datetime.fromtimestamp(ev["startTimestamp"], timezone.utc))
        local, visit = ev["homeTeam"]["name"], ev["awayTeam"]["name"]
        terminado = ev["status"]["type"] == "finished"
        gl, gv = ev["homeScore"].get("current"), ev["awayScore"].get("current")
        partidos.append(dict(fuente="sofascore", partido_id=eid, fecha_utc=fecha, local=local, visitante=visit,
                             goles_local=gl, goles_visitante=gv, estado=ev["status"]["type"]))
        if not terminado:
            continue            # sin incidentes que bajar; el estado queda registrado
        inc = cli.get("sofascore", f"incidentes_{eid}", f"{SOFA}/event/{eid}/incidents",
                      contexto=f"{ctx} {local}-{visit}")["incidents"]
        gs = [i for i in inc if i["incidentType"] == "goal"]
        for i in gs:
            if i.get("homeScore") is None or i.get("awayScore") is None:
                raise DatoIncoherente(f"sofascore {eid}: gol sin marcador acumulado")
        gs.sort(key=lambda i: i["homeScore"] + i["awayScore"])   # la lista viene en orden inverso
        ph = pa = 0
        for k, i in enumerate(gs, 1):
            h, a = i["homeScore"], i["awayScore"]
            if (h, a) == (ph + 1, pa):          # el lado se deduce del marcador acumulado
                lado = "home"
            elif (h, a) == (ph, pa + 1):
                lado = "away"
            else:
                raise DatoIncoherente(f"sofascore {eid}: marcador {ph}-{pa} -> {h}-{a} incoherente")
            nota = ""
            if (lado == "home") != bool(i.get("isHome")):
                nota = f"isHome={i.get('isHome')} contradice marcador; lado deducido={lado}"
            ph, pa = h, a
            anad = i.get("addedTime")
            goles.append(dict(fuente="sofascore", partido_id=eid, fecha_utc=fecha, local=local, visitante=visit,
                              gol_n=k, minuto_txt=minuto_txt(i["time"], anad), minuto=i["time"],
                              anadido=anad or 0, goleador=i["player"]["name"],
                              equipo=local if lado == "home" else visit,
                              penal=i["incidentClass"] == "penalty", autogol=i["incidentClass"] == "ownGoal",
                              marcador_local_tras_gol=h, marcador_visitante_tras_gol=a, nota=nota))
    return partidos, goles


# --------------------------------------------------------------------- ESPN
_MIN = re.compile(r"(\d+)'(?:\s*\+\s*(\d+)')?")


def espn(cli, n, fixtures):
    """fixtures: [(local, visitante, fecha_utc)] de la jornada segun Sofascore; solo se usan sus DIAS
    para pedir el scoreboard (que no admite rangos). ESPN decide que partidos existen ese dia; solo
    se conservan los que cruzan con un fixture de la jornada (los demas se avisan)."""
    ctx = f"jornada {n}"
    pares = {(clave_equipo(l), clave_equipo(v)) for l, v, _ in fixtures}
    descubiertos, ajenos = [], []
    for dia in sorted({f[:10].replace("-", "") for _, _, f in fixtures}):
        sb = cli.get("espn", f"scoreboard_{dia}", f"{ESPN}/scoreboard", {"dates": dia}, contexto=ctx)
        for e in sb["events"]:
            c = {t["homeAway"]: t["team"]["displayName"] for t in e["competitions"][0]["competitors"]}
            (descubiertos if (clave_equipo(c["home"]), clave_equipo(c["away"])) in pares else ajenos).append((e["id"], e["date"]))
    ids_vistos = set()
    partidos, goles = [], []
    for eid, fecha in descubiertos:
        if eid in ids_vistos:
            continue
        ids_vistos.add(eid)
        s = cli.get("espn", f"summary_{eid}", f"{ESPN}/summary", {"event": eid}, contexto=ctx)
        comp = s["header"]["competitions"][0]
        c = {t["homeAway"]: t for t in comp["competitors"]}
        local, visit = c["home"]["team"]["displayName"], c["away"]["team"]["displayName"]
        partidos.append(dict(fuente="espn", partido_id=eid, fecha_utc=fecha, local=local, visitante=visit,
                             goles_local=c["home"]["score"], goles_visitante=c["away"]["score"],
                             estado=comp["status"]["type"]["name"]))
        k = 0
        for ev in s["keyEvents"]:
            if not ev.get("scoringPlay") or ev.get("shootout"):
                continue
            k += 1
            m = _MIN.search(ev["clock"]["displayValue"])
            if not m:
                raise DatoIncoherente(f"espn {eid}: minuto ilegible {ev['clock']['displayValue']!r}")
            base, anad = int(m.group(1)), int(m.group(2) or 0)
            tipo = ev["type"]["text"].lower()
            part = ev.get("participants") or []
            goles.append(dict(fuente="espn", partido_id=eid, fecha_utc=fecha, local=local, visitante=visit,
                              gol_n=k, minuto_txt=minuto_txt(base, anad), minuto=base, anadido=anad,
                              goleador=part[0]["athlete"]["displayName"] if part else "",
                              equipo=ev["team"]["displayName"], penal="penalty" in tipo,
                              autogol="own goal" in tipo, marcador_local_tras_gol="",
                              marcador_visitante_tras_gol="",
                              nota="" if part else "ESPN sin participantes en el evento"))
    if ajenos:
        print(f"  aviso espn J{n}: {len(ajenos)} eventos de esos dias no son de esta jornada (se ignoran aqui): "
              f"{[a[0] for a in ajenos]}")
    return partidos, goles


def escribir(ruta, cols, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)


def archivos(fuente, n):
    return (JORNADAS / f"{fuente}_partidos_j{n:02d}.csv", JORNADAS / f"{fuente}_goles_j{n:02d}.csv")


def procesar(cli, n, forzar):
    """Devuelve lista de fallos (str) de la jornada."""
    fallos = []
    if not forzar and all(p.exists() for f in ("sofascore", "espn") for p in archivos(f, n)):
        print(f"J{n:02d}: CSV ya existen, se omite (usa --forzar para rehacer)")
        return fallos
    res = {}
    for fuente in ("sofascore", "espn"):
        try:
            if fuente == "sofascore":
                res[fuente] = sofascore(cli, n)
            else:
                if "sofascore" not in res:
                    # sin la ronda de Sofascore no hay dias que pedir a ESPN: se informa, no se improvisa
                    raise DatoIncoherente("sin fixtures de Sofascore para derivar los dias del scoreboard")
                fx = [(p["local"], p["visitante"], p["fecha_utc"]) for p in res["sofascore"][0]]
                res[fuente] = espn(cli, n, fx)
        except (FetchError, DatoIncoherente) as e:
            fallos.append(f"J{n:02d} {fuente}: {e}")
            print(f"  FALLO J{n:02d} {fuente}: {e}", file=sys.stderr)
    for fuente, (partidos, goles) in res.items():
        pp, pg = archivos(fuente, n)
        escribir(pp, PARTIDO_COLS, partidos)
        escribir(pg, GOL_COLS, goles)
        print(f"J{n:02d} {fuente}: {len(partidos)} partidos, {len(goles)} goles")
    return fallos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jornada", type=int)
    ap.add_argument("--desde", type=int)
    ap.add_argument("--hasta", type=int)
    ap.add_argument("--todas", action="store_true")
    ap.add_argument("--pausa", type=float, default=1.0)
    ap.add_argument("--forzar", action="store_true")
    a = ap.parse_args()
    if a.todas:
        jornadas = range(1, 39)
    elif a.desde or a.hasta:
        jornadas = range(a.desde or 1, (a.hasta or 38) + 1)
    else:
        jornadas = [a.jornada or 1]
    cli = Cliente(a.pausa)
    todos = []
    try:
        verificar_temporada(cli)
    except (FetchError, DatoIncoherente) as e:
        print(f"FALLO: {e}", file=sys.stderr)
        return 2
    for n in jornadas:
        todos += procesar(cli, n, a.forzar)
    print(f"llamadas de red: {cli.llamadas}, respuestas reutilizadas del crudo: {cli.cacheadas}")
    for f in todos:
        print(f"FALLO: {f}", file=sys.stderr)
    return 2 if todos else 0


if __name__ == "__main__":
    sys.exit(main())
