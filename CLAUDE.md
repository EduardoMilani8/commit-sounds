# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

**commit-sounds** is a LAN toy for friends: when you run `git push`, the PC of a friend plays your custom sound. When they push, your PC plays theirs.

- **No central server.** Each PC runs a small Python HTTP listener (default port 8080) and also acts as a "notifier" via a global git hook.
- The repo holds only the **source**. Real installs are copies under `~/.commit-sounds/` (listener) and `~/.git-hooks/` (hook). Editing a repo file changes nothing on this machine until it is reinstalled (see Development).
- The user-facing manual is `README.md` (written in **pt-BR**). Code, logs and messages are also Portuguese.

## Architecture

| Role | File (in repo) | Installed at (runtime) | Purpose |
|------|----------------|------------------------|---------|
| Listener (server) | `listener.py` | `~/.commit-sounds/listener.py` | HTTP server; receives push alerts and plays the matching sound |
| Global hook | `hook/pre-push` | `~/.git-hooks/pre-push` | Runs on `git push` (branch/tag); POSTs a `/play` alert to every configured target |
| Hook installer | `install-hook.sh` | — | Copies the hook, sets `git config --global core.hooksPath ~/.git-hooks`, writes `hook-config.sh` **interactively** |
| Listener installer | `install-listener.sh` | — | Copies listener, runs `listener.py --init` if no config, writes + enables systemd **user** unit `commit-sound`; apt-installs `curl`, players and `ffmpeg` if missing |
| Uploader | `upload-som.sh <file>` | — | POSTs your sound to `/upload` on every target in `hook-config.sh` |
| Test tool | `testar-som.sh` | — | Tests the `/play` network path, or local audio with `--local` |

## Runtime state (per-PC, on disk)

- `~/.commit-sounds/config.json` — `{host, porta, secreto}`. Missing keys are filled with defaults (`0.0.0.0`, `8080`, random 32-hex secret) and the file is rewritten on **every** listener start. This is the source of truth for port/secret.
- `~/.commit-sounds/sounds/<apelido>.<ext>` — one sound per friend, keyed by nickname.
- `~/.git-hooks/hook-config.sh` — `CS_AMIGO="..."` + `CS_TARGETS=( "URL|secreto" ... )` (see `hook/hook-config.example.sh`). `chmod 600`.
- Logs: `~/.git-hooks/pre-push.log` (hook), `~/.git-hooks/push.log` (auto-push hook), listener via `journalctl --user -u commit-sound`.

## Listener API

Auth: shared secret, compared with `hmac.compare_digest` in `Handler._authed`. Wrong/missing → `403`.

| Route | Method | Body | Auth | Behavior |
|-------|--------|------|------|----------|
| `/play` | POST | JSON `{"secreto","amigo"}` | header `X-Secreto` or JSON `secreto` | `200` (with `player`), `400` bad nickname, `404` no sound, `500` no player worked |
| `/upload` | POST | `multipart/form-data`: `amigo`, `som` | header `X-Secreto` only | stores `sounds/<amigo><ext>`; `415` if not multipart, `400` bad nickname/extension |

- Nickname regex `^[A-Za-z0-9_.-]{1,32}$` (`valid_amigo`). The hook does not validate `CS_AMIGO`; it builds the JSON by string interpolation.
- Extensions (`VALID_EXTS`): `mp3, wav, ogg, opus, flac, m4a, aac`. Multipart parsing is hand-rolled (`parse_multipart`), since stdlib `cgi` is gone.
- Uploading a new extension does **not** delete the old file. `/play` picks `sorted(glob("<amigo>.*"))[0]`, so e.g. an old `Fabio.m4a` wins over a new `Fabio.wav`.

## Audio playback (`play_sound`)

Players are tried in order: `pw-play` → `paplay` → `aplay` (WAV only) → `ffplay -nodisp -autoexit`. Each runs as `timeout DURACAO_MAX <player> <file>` in its own session. The listener waits **1 s**: a player still running counts as success; one that exits non-zero within 1 s falls through to the next. So a `200` means "a player started", not "sound was heard". mp3 generally needs ffmpeg on the **listening** PC.

`DURACAO_MAX = 5` caps playback. It must stay in sync with `timeout 5` in `testar-som.sh --local` and the "5 segundos" mentions in `README.md`.

## Data flow on push

1. `git push` → global `pre-push` hook (global `core.hooksPath` means repo-local `.git/hooks` are ignored everywhere).
2. Hook sources `hook-config.sh`; if `CS_AMIGO`/`CS_TARGETS` are missing, it logs and exits.
3. It only fires if some pushed ref is `refs/heads/*` or `refs/tags/*` with a non-zero oid (not a deletion).
4. For each target: `curl --max-time 2 POST <url>/play`, logging the HTTP status to `pre-push.log`. This runs **before** the remote accepts the push, so a rejected push still plays.
5. The hook always `exit 0`. A failed alert must never block a push. Preserve this.

## Development

No build, lint or test suite exists. The only dependencies are bash, curl, python3 stdlib, and a player.

```bash
# run the listener from the repo (uses ~/.commit-sounds/ paths; no flag to change them)
systemctl --user stop commit-sound          # free the port first
python3 listener.py                          # prints host:port and secret
python3 listener.py --init                   # create/fill config.json and exit

# exercise the API locally
S=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.commit-sounds/config.json")))["secreto"])')
curl -s -X POST localhost:8080/play -H 'Content-Type: application/json' -d "{\"secreto\":\"$S\",\"amigo\":\"Teste\"}"
curl -s -X POST localhost:8080/upload -H "X-Secreto: $S" -F amigo=Teste -F som=@som.wav

bash testar-som.sh --local                   # local audio only
bash testar-som.sh URL SECRETO APELIDO       # one target by hand (default: all targets in hook-config.sh)

# deploy edits to this machine
install -m 755 listener.py ~/.commit-sounds/listener.py && systemctl --user restart commit-sound
install -m 755 hook/pre-push ~/.git-hooks/pre-push   # NOT install-hook.sh: that re-prompts and overwrites hook-config.sh
```

## Conventions & gotchas

- **Do not add code comments** unless the user explicitly asks.
- Keep the **pt-BR** voice (runtime messages/logs are unaccented ASCII, e.g. `nao`, `invalido`; README is accented) for user-facing messages, logs and README.
- Listener is **stdlib only** (`http.server`, `ThreadingHTTPServer`). No third-party deps.
- Shell scripts target bash on Debian/Ubuntu (`apt-get` in the installer). Hook and scripts avoid `set -e` where a failure must not abort.
- **Commit style**: short Portuguese messages, often with Conventional prefixes (`feat:`, `fix:`, `docs:`).
- **Committing here pushes immediately.** A user-global `~/.git-hooks/post-commit` runs `git push` when the branch has an upstream (logs to `push.log`). That push fires `pre-push`, which **plays your sound on your friends' PCs**. Only commit when the user asks.
