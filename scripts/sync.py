"""Sincroniza la liga con las partidas de aoe2companion.

Lee data/config.json, data/players.json y data/matches.json, busca partidas
nuevas del torneo en el historial de cada jugador registrado, da de alta a los
jugadores nuevos que aparecen en ellas y actualiza los clanes. Solo escribe los
archivos si algo ha cambiado. El elo no se guarda: lo calcula la web.

Uso: python scripts/sync.py
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://data.aoe2companion.com/api"
DATA = Path(__file__).resolve().parent.parent / "data"
TZ = ZoneInfo("Europe/Madrid")
UA = {"User-Agent": "elo-hispania-sync (github.com/jorge6arcia/elo-hispania)"}
DELAY = 0.8  # segundos entre peticiones (límite de la API: ~16 cada 10 s)


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def get(path, **params):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                time.sleep(DELAY)
                return json.load(r)
        except Exception as e:  # red, 429, 5xx
            print(f"  aviso: {url} -> {e}", file=sys.stderr)
            time.sleep(10)
    return None


def pyregex(rx):
    """Convierte '(?i)patrón' en una regex de Python."""
    return re.compile(rx[4:], re.I) if rx.startswith("(?i)") else re.compile(rx)


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    cfg = load("config.json", {})
    players = load("players.json", {})
    matches = load("matches.json", {})
    since = cfg.get("since", "2026-10-06")
    lobby_rx = pyregex(cfg.get("lobbyPattern", r"(?i)\bcw|clan\s*wars?"))
    map_rx = pyregex(cfg.get("mapPattern", r"(?i)^cw7"))
    vs_rx = re.compile(r"\bvs\b", re.I)
    sizes = set(cfg.get("teamSizes", [2, 3, 4]))
    min_game = cfg.get("minGameSec", 300)
    speed = cfg.get("speedFactor", 1.7)

    def is_tournament(m):
        name, mp = m.get("name") or "", m.get("mapName") or ""
        if lobby_rx.search(name):
            return True
        return bool(map_rx.search(mp)) and (not cfg.get("mapNeedsVs", True) or bool(vs_rx.search(name)))

    def valid(m):
        if not is_tournament(m) or m.get("leaderboardId") not in cfg.get("leaderboards", ["unranked"]):
            return False
        if m.get("gameMode") != "random_map" or not m.get("finished"):
            return False
        if m.get("population") not in (200, None) or m.get("allowCheats") or m.get("speedName") not in ("Normal", None):
            return False
        if parse_ts(m["started"]).astimezone(TZ).strftime("%Y-%m-%d") < since:
            return False
        teams = [[p for p in t["players"] if p.get("status", "player") == "player"] for t in m["teams"] if t["players"]]
        if len(teams) != 2 or len(teams[0]) != len(teams[1]) or len(teams[0]) not in sizes:
            return False
        w = [[p.get("won") for p in t] for t in teams]
        if not ((all(x is True for x in w[0]) and all(x is False for x in w[1])) or
                (all(x is False for x in w[0]) and all(x is True for x in w[1]))):
            return False
        dur = (parse_ts(m["finished"]) - parse_ts(m["started"])).total_seconds()
        return dur * (m.get("speedFactor") or speed) >= min_game

    known = {p["profileId"]: pid for pid, p in players.items()}
    last = load("sync.json", {}).get("lastRun")
    # Tras la primera vez, basta con mirar los últimos 2 días (el rastreo corre cada 15 min).
    window = since
    if last:
        recent = datetime.fromtimestamp(last / 1000 - 2 * 86400, tz=timezone.utc).astimezone(TZ).strftime("%Y-%m-%d")
        window = max(since, recent)
    queue = list(known)
    seen, new_matches, new_players, first_seen = set(), {}, {}, {}
    batch = 10

    def handle(m):
        mid = f"aoe-{m['matchId']}"
        if mid in matches or mid in new_matches or not valid(m):
            return
        teams = [t for t in m["teams"] if t["players"]]
        for t in teams:
            for p in t["players"]:
                pr = str(p["profileId"])
                first_seen[pr] = min(first_seen.get(pr, m["started"]), m["started"])
                if pr not in known and pr not in new_players:
                    new_players[pr] = {"nick": p["name"], "country": p.get("country") or ""}
                    queue.append(pr)
        s, f = parse_ts(m["started"]), parse_ts(m["finished"])
        new_matches[mid] = {
            "date": s.astimezone(TZ).strftime("%Y-%m-%d"), "ts": int(s.timestamp() * 1000),
            "map": m.get("mapName"), "lobby": m.get("name"), "source": "auto", "aoeMatchId": m["matchId"],
            "team1": [f"p-{p['profileId']}" for p in teams[0]["players"]],
            "team2": [f"p-{p['profileId']}" for p in teams[1]["players"]],
            "winner": 1 if teams[0]["players"][0].get("won") else 2,
            "durationSec": int((f - s).total_seconds()),
            "civs": {f"p-{p['profileId']}": p.get("civName") for t in teams for p in t["players"]},
        }

    while queue:
        group = []
        while queue and len(group) < batch:
            pr = queue.pop(0)
            if pr not in seen:
                seen.add(pr)
                group.append(pr)
        if not group:
            continue
        # Jugadores nuevos: historial completo desde 'since'; el resto, solo la ventana reciente.
        start = since if any(pr in new_players for pr in group) else window
        for page in range(1, 11):
            d = get("matches", profile_ids=",".join(group), per_page=100, page=page)
            if not d or not d.get("matches"):
                break
            for m in d["matches"]:
                handle(m)
            if min(m["started"][:10] for m in d["matches"]) < start:
                break
        print(f"revisados {len(seen)} · partidas nuevas {len(new_matches)} · jugadores nuevos {len(new_players)}")

    # Clanes de todos (y de los nuevos)
    all_ids = list(known) + list(new_players)
    clans = {}
    for i in range(0, len(all_ids), 20):
        d = get("profiles", profile_ids=",".join(all_ids[i:i + 20]), per_page=50, page=1)
        for p in (d or {}).get("profiles", []):
            clans[str(p["profileId"])] = (p.get("clan") or "").strip()

    # Elo inicial de los nuevos: su 1v1 justo antes de su primera partida de liga
    now = int(time.time() * 1000)
    for pr, info in new_players.items():
        d = get(f"profiles/{pr}/ratings") or {}
        hist = next((x["ratings"] for x in d.get("ratings", []) if x.get("leaderboardId") == "rm_1v1"), [])
        before = [h for h in hist if h["date"] < first_seen[pr]]
        pick = max(before, key=lambda h: h["date"]) if before else (min(hist, key=lambda h: h["date"]) if hist else None)
        players[f"p-{pr}"] = {
            "nick": info["nick"], "profileId": pr, "country": info["country"], "clan": clans.get(pr, ""),
            "region": "", "eloStart": pick["rating"] if pick else 1000,
            "eloStartSource": "rm_1v1" if pick else "default", "eloStartDate": pick["date"] if pick else None,
            "approved": True, "auto": True, "createdAt": now,
        }

    clan_changes = 0
    for pr, pid in known.items():
        if pr in clans and players[pid].get("clan", "") != clans[pr]:
            players[pid]["clan"] = clans[pr]
            clan_changes += 1

    matches.update(new_matches)
    changed = bool(new_matches or new_players or clan_changes)
    if changed:
        save("players.json", players)
        save("matches.json", matches)
    # sync.json solo se reescribe si hubo cambios o cada 6 h, para no llenar el historial de commits.
    if changed or not last or now - last > 6 * 3600 * 1000:
        save("sync.json", {"lastRun": now, "added": len(new_matches), "newPlayers": len(new_players),
                           "clanChanges": clan_changes, "checkedPlayers": len(seen)})
    print(f"Hecho: {len(new_matches)} partidas nuevas, {len(new_players)} jugadores nuevos, {clan_changes} cambios de clan")


if __name__ == "__main__":
    main()
