# ST DevBench

A web workbench for Hatari's agent API, in the style of the 3DO, Atari
8-bit, Lynx and Amiga devbenches. It also builds and runs the game ports
in [atari_st_games](https://github.com/geekychris/atari_st_games), from a
checkout next to this repository.

```sh
python3 tools/devbench/devbench.py --open        # http://127.0.0.1:3520/
```

It only needs the Python standard library, and Hatari built (see the main
README).

## In the browser

- **Header:** pick a game from `games.ini`. **Build** runs `make` in its
  directory; **Run game** builds it if needed, then starts Hatari on the
  game's machine with its `build/` directory as C: and the program
  autostarted (the same as `tools/games/launcher.py --play`). **Start
  desktop** boots a machine (ST, STE, Mega STE, TT, Falcon) to the EmuTOS
  desktop, and **Stop Hatari** quits it.
- **Screen:** the emulated display at native resolution, refreshed live.
  Clicking it clicks there in the emulator. Below it: run 1 frame, 1 s or
  5 s, pause, resume, fast forward, warm and cold reset, keys and key
  combos, typed text, joystick (port 1) and snapshot save/load.
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
| `GET /api/health` | whether Hatari answers, its port, the games.ini used |
| `GET /api/projects` | the games, with machine, program and whether it's built |
| `POST /api/projects/{id}/build` | `make` (cross compiler from games.ini) |
| `POST /api/projects/{id}/run` | build if needed, then run; `{"build": false}` skips the build |
| `POST /api/hatari/start` | `{"machine": "ste"}`: Hatari at the EmuTOS desktop |
| `POST /api/hatari/stop` | quit Hatari |
| `/api/hatari/<path>` | passed through to the agent API ([doc/agent-api.md](../../doc/agent-api.md)) |

Options: `--port` (3520), `--hatari-port` (7777, or `$AGENT_PORT`),
`--ini` (games.ini; default `../atari_st_games/games.ini`, or
`$ATARI_GAMES_DIR/games.ini`), `--host`, `--open`.

There's no MCP endpoint, unlike the other devbenches: Claude drives Hatari
through the agent API directly (the `hatari-agent` skill).

A Hatari the DevBench starts runs in its process group, so stopping the
DevBench with its group (as Switchboard does) stops Hatari too.

## Tests

```sh
python3 tools/devbench/test_devbench.py
```
