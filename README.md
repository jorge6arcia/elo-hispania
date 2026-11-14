# Elo Hispania

Ranking ELO de partidas preparadas (lobbies) de Age of Empires II entre jugadores españoles.

**Web:** https://jorge6arcia.github.io/elo-hispania/

## Cómo funciona

- `index.html` es la web. Lee los datos de la carpeta `data/` y calcula el elo en el navegador.
- La pestaña **En directo** consulta [aoe2companion](https://www.aoe2companion.com) cada minuto desde el navegador de quien la visita.
- `scripts/sync.py` busca partidas nuevas del torneo en aoe2companion. Lo ejecuta GitHub Actions cada 15 minutos (`.github/workflows/sync.yml`) y guarda los cambios en `data/`.

## Datos

| Archivo | Contenido |
|---|---|
| `data/players.json` | Jugadores: nick, ID de perfil, clan, elo inicial |
| `data/matches.json` | Partidas: equipos, ganador, mapa, sala, duración |
| `data/config.json` | Reglas: qué salas cuentan, desde qué fecha, duración mínima, K |
| `data/sync.json` | Última sincronización |

## Tareas de administración

- **Impugnar una partida:** en `data/matches.json`, añade `"disputed": true` a la partida. Para quitar la impugnación, pon `false`.
- **Ocultar una partida errónea:** añade `"hidden": true`. El rastreo no la vuelve a crear.
- **Cambiar las reglas:** edita `data/config.json`.
- **Asignar un clan a mano:** en `data/config.json`, añade el ID de perfil del jugador y su clan en `clanOverrides` (por ejemplo `"96571": "RANK1"`). Manda sobre el clan que tenga en el juego y vale también para jugadores que aún no han jugado.

## Reglas del elo

- Cada jugador empieza con su elo de 1v1 del juego justo antes de su primera partida de liga.
- Tras cada partida: `32 × (resultado − esperado)`, comparando tu elo con el elo medio del equipo rival. Ganar da siempre al menos +1.
- Solo cuentan partidas por equipos (2v2, 3v3, 4v4) de lobby, en Random Map, con configuración estándar y de al menos 5 minutos de juego.

Datos de partidas: [aoe2companion](https://www.aoe2companion.com).
