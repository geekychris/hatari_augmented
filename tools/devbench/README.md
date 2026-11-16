# ST DevBench

A web workbench for Hatari's agent API, in the style of the 3DO, Atari
8-bit, Lynx and Amiga devbenches. It also builds and runs the game ports
in [atari_st_games](https://github.com/geekychris/atari_st_games), from a
checkout next to this repository.

```sh
tools/devbench/run.sh --open        # http://127.0.0.1:3520/arcade and http://127.0.0.1:3520/
```

It only needs the Python standard library, and Hatari built (see the main
README). The games come from an [atari_st_games](https://github.com/geekychris/atari_st_games)
checkout: `../atari_st_games` next to this repository by default, or
`--games DIR` / `$ATARI_GAMES_DIR`.

## The arcade (`/arcade`)

Every game in `games.ini`, each with its picture (the `screenshot` from
games.ini, else `docs/title.png` or another PNG in the game's `docs/`), its
description and controls, a link to its README, and **Build** and
**Play**. Play builds it if needed and starts Hatari on the game's machine;
the running game then shows at the top of the page, live. Click the screen
and your keyboard goes to the ST: keys are held down for as long as you
hold them. With *cursor keys + Space = joystick* ticked (the default for
games whose controls name only the joystick) the cursor keys, Space and
Ctrl drive the joystick in port 1 instead. Pause, Resume, Reset and Stop
are next to it, and *Open in the DevBench* goes to the dev page for the
same game.

*Demos and shared code too* also lists the other directories: the demos
(gemdemo, interact, st_launcher, which can be built and run too; the
launcher runs from the C: drive that `make drive` assembles) and the
shared port layers (st_port, falcon_port, falcon_3do, a3d_falcon), which
can't run on their own. A game that can't build or run says why on its
card (no Hatari build, missing TOS image, no cross compiler for an
unbuilt game) instead of being left out.

## The dev page (`/`)

- **Header:** pick a game from `games.ini` (or a demo; `/?game=<id>`
  preselects one). **Build** runs `make` in its
  directory; **Run game** builds it if needed, then starts Hatari on the
  game's machine with its `build/` directory as C: and the program
  autostarted (the same as `tools/games/launcher.py --play`). **Start
  desktop** boots a machine (ST, STE, Mega STE, TT, Falcon) to the EmuTOS
  desktop, and **Stop Hatari** quits it.
- **Screen:** the emulated display at native resolution, refreshed live.
  Clicking it clicks there in the emulator. Below it: run 1 frame, 1 s or
  5 s, pause, resume, fast forward, warm and cold reset, keys and key
  combos, typed text, joystick (port 1) and snapshot save/load. While
  the screen has focus, the keyboard goes to the ST as on the arcade page.
- **Console:** TOS console output and NatFeats `NF_STDERR` lines (the game
  ports log through NatFeats).
- **Debugger:** break, continue, step, step over; breakpoints by address,
  symbol or condition (`pc=TEXT`, `d0=$20`); registers and disassembly at
  the PC; any Hatari debugger command.
- **Memory:** a hex dump at an address or expression.
- **Agent API:** any endpoint, for what the page has no button for.

## REST

| | |
|---|---|
| `GET /api/health` | whether Hatari answers, its port, the games.ini used, the game started from here (`playing`), the toolchain found |
| `GET /api/projects` | every project: the games.ini games (`kind: game`), then the other directories (`demo`, `library`); each with machine, program, `built`, `playable` and `reason`, `picture` and `readme` URLs |
| `GET /api/projects/{id}/picture` | its picture (PNG) |
| `GET /api/projects/{id}/readme` | its README.md |
| `POST /api/projects/{id}/build` | `make` (cross compiler from games.ini; `make drive` for st_launcher) |
| `POST /api/projects/{id}/run` | build if needed, then run; `{"build": false}` skips the build |
| `GET /api/arcade` | `{"games": [...], "playing", "hatari"}`: the projects that are games |
| `POST /api/arcade/play` | `{"game": id, "build": true}`: the same as `.../run` |
| `POST /api/hatari/start` | `{"machine": "ste"}`: Hatari at the EmuTOS desktop |
| `POST /api/hatari/stop` | quit Hatari |
| `/api/hatari/<path>` | passed through to the agent API ([doc/agent-api.md](../../doc/agent-api.md)) |

Options: `--port` (3520), `--hatari-port` (7777, or `$AGENT_PORT`),
`--games` (the atari_st_games checkout; default `$ATARI_GAMES_DIR`, else
`../atari_st_games`), `--ini` (a games.ini elsewhere), `--host`, `--open`.
Two DevBenches can run side by side on different `--port` and
`--hatari-port`.

There's no MCP endpoint, unlike the other devbenches: Claude drives Hatari
through the agent API directly (the `hatari-agent` skill).

A Hatari the DevBench starts runs in its process group, so stopping the
DevBench with its group (as Switchboard does) stops Hatari too.

## Tests

```sh
python3 tools/devbench/test_devbench.py
```
