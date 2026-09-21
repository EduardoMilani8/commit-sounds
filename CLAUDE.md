# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) and other AI coding agents working in this repository.

## What this project is

**commit-sounds** is a LAN toy for friends: when you run `git push`, the PC of a friend plays your custom sound. When they push, your PC plays theirs.

- **No central server.** Each PC runs a small Python HTTP listener on port 8080 and also acts as a "notifier" via a global git hook.
- Everything is installed per-user under `~/.commit-sounds/` (listener) and `~/.git-hooks/` (hook) — the repo only contains the *source* of those components.
- The user-facing manual is `README.md` (written in **pt-BR**). Code comments, logs and messages are also mostly Portuguese.

## Architecture

| Role | File (in repo) | Installed at (runtime) | Purpose |
|------|----------------|------------------------|---------|
| Listener (server) | `listener.py` | `~/.commit-sounds/listener.py` | HTTP server on port 8080; receives push alerts and plays the matching sound |
| Global hook | `hook/pre-push` | `~/.git-hooks/pre-push` | Runs on `git push` (branch/tag); POSTs a `/play` alert to every configured target |
| Hook installer | `install-hook.sh` | — | Installs the global hook + writes `hook-config.sh` interactively |
| Listener installer | `install-listener.sh` | — | Installs listener, systemd user unit `commit-sound`, generates `config.json` |
| Uploader | `upload-som.sh` | — | Uploads your sound to all configured target PCs |
| Test tool | `testar-som.sh` | — | Tests network path (`/play`) or local audio (`--local`) |

Install flow:

- `install-listener.sh` → creates `~/.commit-sounds/{listener.py, config.json, sounds/}` and a systemd **user** service `commit-sound.service` (enabled, auto-start at login).
- `install-hook.sh` → calls `git config --global core.hooksPath ~/.git-hooks` and writes `~/.git-hooks/hook-config.sh`.

## Runtime state (per-PC, on disk)

- `~/.commit-sounds/config.json` — `{host, porta, secreto}`. Created with defaults (`0.0.0.0:8080`, random 32-hex secret) if missing. This **is the source of truth** for the listener port/secret.
- `~/.commit-sounds/sounds/<apelido>.<ext>` — one sound file per friend, keyed by nickname.
- `~/.git-hooks/hook-config.sh` — `CS_AMIGO="..."` + `CS_TARGETS=( "URL|secreto" ... )`, one per target PC. `chmod 600`.
- Logs: `~/.git-hooks/pre-push.log` (hook), `~/.git-hooks/push.log` (auto-push hook, see Conventions), listener logs via `journalctl --user -u commit-sound`.

## Listener API (port from `config.json`, default 8080)

Auth: a shared secret. Sent either as header `X-Secreto` or in the JSON body as `secreto`. Compared with `hmac.compare_digest` in `Handler._authed`. Missing/wrong secret → `403`.

| Route | Method | Body | Auth | Behavior |
|-------|--------|------|------|----------|
| `/play` | POST | `{"secreto","amigo"}` | yes | plays `sounds/<amigo>.*` → `200` with player, `404` no sound, `500` no player |
| `/upload` | POST | `multipart/form-data`: `amigo`, `som` | yes (header) | stores sound file → `200`; validates extension |

Validation rules:

- `valid_amigo`: regex `^[A-Za-z0-9_.-]{1,32}$`.
- Accepted sound extensions (`VALID_EXTS`): `mp3, wav, ogg, opus, flac, m4a, aac`.
- `DURACAO_MAX = 5` — sound playback is hard-capped at 5 seconds using the `timeout` CLI wrapper. **Do not change without updating `testar-som.sh` (local `timeout 5`) and README references to "5 segundos".**

## Audio playback (`play_sound` in `listener.py`)

Tries players in order, first success wins:

1. `pw-play <file>`
2. `paplay <file>`
3. `aplay <file>` — **WAV only** (skipped otherwise)
4. `ffplay -nodisp -autoexit <file>`

Each is wrapped as `timeout 5 <player> ...`. Note: mp3 needs ffmpeg on the *listening* PC or `pw-play`/`paplay` may fail silently — documented in README.

## Data flow on push

1. `git push` triggers the global `pre-push` hook.
2. Hook reads `hook-config.sh`; exits silently if unset.
3. It only fires on `refs/heads/*` or `refs/tags/*` pushes (ignores deletions/zero oids).
4. For each target: `POST <url>/play` with `{"secreto":token,"amigo":CS_AMIGO}`, log status line to `pre-push.log`. Runs **before** the push is accepted (by design; a rejected push still plays).
5. Listener validates auth + nickname, finds the sound file, plays it (capped 5s), returns `200`.

## Conventions & gotchas for AI agents

- **Do not add code comments** unless the user explicitly asks.
- Keep the **pt-BR** voice for user-facing messages and logs; README docs are pt-BR.
- The pre-push hook deliberately uses `exit 0` always — a failed alert must **not** block the push. Preserve that.
- The listener is plain Python stdlib (`http.server`). No third-party deps. Keep it that way.
- `testar-som.sh --local` uses `timeout 5`; keep in sync with `DURACAO_MAX`.
- **Commit style** (repo history): short Portuguese messages, often Conventional-commit prefixes (`feat:`, `fix:`, `docs:`). Follow suit.
- This machine auto-pushes on commit via a user-global `post-commit` hook (`~/.git-hooks/post-commit`, logs to `push.log`). A commit here is pushed immediately; do not be surprised.
- Tests: none exist. Sanity-check changes by running `bash testar-som.sh --local` (audio) or a local curl against the listener.