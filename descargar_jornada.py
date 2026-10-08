#!/usr/bin/env python3
"""Descarga la Jornada 1 de la Serie A 2025-26 desde ESPN y Sofascore (APIs JSON).

Salida (carpeta datos/), por fuente:
  <fuente>_partidos_j1.csv  una fila por partido (incluye 0-0)
  <fuente>_goles_j1.csv     una fila por gol

Si una conexion falla (HTTP != 200, timeout, bloqueo) se informa host y codigo,
no se escribe nada de esa fuente y el script termina con codigo 2. No se
inventan ni completan datos.

Convenciones:
  equipo   = equipo al que se le acredita el gol (en un autogol, el beneficiario).
  minuto   = minuto base; anadido = tiempo anadido; minuto_txt = "45+2".
"""
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

SEASON_LABEL = "2025-26"
ROUND = 1
SOFA_TOURNAMENT = 23          # Serie A
SOFA_SEASON = 76457           # 25/26 (verificado contra /seasons: year == "25/26")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1"
SOFA = "https://api.sofascore.com/api/v1"
OUT = Path(__file__).parent / "datos"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
           "Accept": "application/json"}
TIMEOUT = 20

PARTIDO_COLS = ["fuente", "partido_id", "fecha_utc", "local", "visitante",
                "goles_local", "goles_visitante", "estado"]
GOL_COLS = ["fuente", "partido_id", "fecha_utc", "local", "visitante", "gol_n",
            "minuto_txt", "minuto", "anadido", "goleador", "equipo", "penal", "autogol",
            "marcador_local_tras_gol", "marcador_visitante_tras_gol", "nota"]


class FetchError(Exception):
    def __init__(self, url, code):
        self.host = urlparse(url).netloc
        self.url = url
        self.code = code
        super().__init__(f"host={self.host} codigo={code} url={url}")


def get_json(url, params=None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    except requests.Timeout:
        raise FetchError(url, "timeout")
    except requests.RequestException as e:
        raise FetchError(url, f"error-conexion:{type(e).__name__}")
    if r.status_code != 200:
        raise FetchError(r.url, r.status_code)
    try:
        return r.json()
    except ValueError:
        raise FetchError(r.url, "200-pero-no-JSON")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def minuto_txt(base, anadido):
    return f"{base}+{anadido}" if anadido else str(base)


# ---------------------------------------------------------------- Sofascore
def sofascore():
    partidos, goles = [], []
    data = get_json(f"{SOFA}/unique-tournament/{SOFA_TOURNAMENT}/seasons")
    anio = next((s["year"] for s in data["seasons"] if s["id"] == SOFA_SEASON), None)
    if anio != "25/26":
        raise RuntimeError(f"season id {SOFA_SEASON} no es 25/26 (es {anio})")
    ronda = get_json(f"{SOFA}/unique-tournament/{SOFA_TOURNAMENT}/season/{SOFA_SEASON}/events/round/{ROUND}")
    for ev in ronda["events"]:
        eid = ev["id"]
        fecha = iso(datetime.fromtimestamp(ev["startTimestamp"], timezone.utc))
        local, visit = ev["homeTeam"]["name"], ev["awayTeam"]["name"]
        gl, gv = ev["homeScore"].get("current"), ev["awayScore"].get("current")
        partidos.append(dict(fuente="sofascore", partido_id=eid, fecha_utc=fecha, local=local,
                             visitante=visit, goles_local=gl, goles_visitante=gv,
                             estado=ev["status"]["type"]))
        inc = get_json(f"{SOFA}/event/{eid}/incidents")["incidents"]
        gs = [i for i in inc if i["incidentType"] == "goal"]
        # orden cronologico fiable: por goles acumulados (la lista viene invertida)
        gs.sort(key=lambda i: (i["homeScore"] + i["awayScore"]))
        ph = pa = 0
        for n, i in enumerate(gs, 1):
            h, a = i["homeScore"], i["awayScore"]
            # el lado se deduce del marcador acumulado, no de isHome
            if (h, a) == (ph + 1, pa):
                lado = "home"
            elif (h, a) == (ph, pa + 1):
                lado = "away"
            else:
                raise RuntimeError(f"evento {eid}: marcador {ph}-{pa} -> {h}-{a} incoherente")
            nota = ""
            if (lado == "home") != bool(i.get("isHome")):
                nota = f"isHome={i.get('isHome')} contradice marcador; lado deducido={lado}"
            ph, pa = h, a
            anad = i.get("addedTime")
            goles.append(dict(fuente="sofascore", partido_id=eid, fecha_utc=fecha, local=local,
                              visitante=visit, gol_n=n, minuto_txt=minuto_txt(i["time"], anad),
                              minuto=i["time"], anadido=anad or 0, goleador=i["player"]["name"],
                              equipo=local if lado == "home" else visit,
                              penal=i["incidentClass"] == "penalty",
                              autogol=i["incidentClass"] == "ownGoal",
                              marcador_local_tras_gol=h, marcador_visitante_tras_gol=a, nota=nota))
    return partidos, goles


# --------------------------------------------------------------------- ESPN
_MIN = re.compile(r"(\d+)'(?:\s*\+\s*(\d+)')?")


def espn(dias):
    """dias: fechas YYYYMMDD en las que se juega la jornada (el scoreboard no admite rangos)."""
    partidos, goles = [], []
    descubiertos = []
    for d in dias:   # scoreboard SOLO para descubrir partidos (ids, equipos, fecha)
        sb = get_json(f"{ESPN}/scoreboard", {"dates": d})
        descubiertos += [(e["id"], e["date"]) for e in sb["events"]]
    for eid, fecha in descubiertos:
        s = get_json(f"{ESPN}/summary", {"event": eid})
        comp = s["header"]["competitions"][0]
        c = {t["homeAway"]: t for t in comp["competitors"]}
        local, visit = c["home"]["team"]["displayName"], c["away"]["team"]["displayName"]
        partidos.append(dict(fuente="espn", partido_id=eid, fecha_utc=fecha, local=local, visitante=visit,
                             goles_local=c["home"]["score"], goles_visitante=c["away"]["score"],
                             estado=comp["status"]["type"]["name"]))
        n = 0
        for k in s["keyEvents"]:
            if not k.get("scoringPlay") or k.get("shootout"):
                continue
            n += 1
            m = _MIN.search(k["clock"]["displayValue"])
            if not m:
                raise RuntimeError(f"ESPN {eid}: minuto ilegible {k['clock']['displayValue']!r}")
            base, anad = int(m.group(1)), int(m.group(2) or 0)
            tipo = k["type"]["text"]
            goles.append(dict(fuente="espn", partido_id=eid, fecha_utc=fecha, local=local, visitante=visit,
                              gol_n=n, minuto_txt=minuto_txt(base, anad), minuto=base, anadido=anad,
                              goleador=k["participants"][0]["athlete"]["displayName"],
                              equipo=k["team"]["displayName"],
                              penal="penalty" in tipo.lower(), autogol="own goal" in tipo.lower(),
                              marcador_local_tras_gol="", marcador_visitante_tras_gol="", nota=""))
    return partidos, goles


def escribir(nombre, cols, filas):
    OUT.mkdir(exist_ok=True)
    with open(OUT / nombre, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)
    print(f"escrito datos/{nombre}: {len(filas)} filas")


def main():
    fallos = []
    resultados = {}
    sofa_dias = None
    try:
        resultados["sofascore"] = sofascore()
        sofa_dias = sorted({p["fecha_utc"][:10].replace("-", "") for p in resultados["sofascore"][0]})
    except FetchError as e:
        fallos.append(e)
    except RuntimeError as e:
        print(f"ERROR sofascore: {e}")
        fallos.append(e)

    if sofa_dias is None:
        print("ESPN no se consulta: sus fechas de scoreboard se toman de las fechas de la ronda 1 de Sofascore.")
    else:
        try:
            resultados["espn"] = espn(sofa_dias)
        except FetchError as e:
            fallos.append(e)
        except RuntimeError as e:
            print(f"ERROR espn: {e}")
            fallos.append(e)

    for fuente, (partidos, goles) in resultados.items():
        escribir(f"{fuente}_partidos_j1.csv", PARTIDO_COLS, partidos)
        escribir(f"{fuente}_goles_j1.csv", GOL_COLS, goles)

    for e in fallos:
        print(f"FALLO: {e}", file=sys.stderr)
    return 2 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
