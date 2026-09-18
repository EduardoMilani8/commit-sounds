# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project at a glance

**commit-sounds** — a LAN toy: `git push` makes a friend's PC play your custom sound, and vice versa. No central server; each PC runs its own HTTP listener (port 8080) and a global git hook that alerts the other PCs.

This repo is **source only**. Real installs live in the user's home dir:

| Repo file | Installed as | Role |
|-----------|--------------|------|
| `listener.py` | `~/.commit-sounds/listener.py` | HTTP server: receives alerts, plays sounds |
| `hook/pre-push` | `~/.git-hooks/pre-push` | Git hook: notifies all `CS_TARGETS` on branch/tag push |
| `web/index.html` | `~/.commit-sounds/web/index.html` | Single-file browser panel served at `/` |
| `install-listener.sh` | — | Installs listener + systemd user service `commit-sound` |
| `install-hook.sh` | — | Installs global hook + writes `hook-config.sh` |
| `upload-som.sh` | — | Uploads a sound file to every configured target |
| `testar-som.sh` | — | Tests `/play` path or local audio (`--local`) |

## Runtime files (per-PC)

- `~/.commit-sounds/config.json` — `{host, porta, secreto}`; **source of truth** for port + secret. Auto-created with a random 32-hex secret.
- `~/.commit-sounds/sounds/<apelido>.<ext>` — one sound file per friend.
- `~/.git-hooks/hook-config.sh` — `CS_AMIGO` (your nickname) + `CS_TARGETS` array of `"URL|secreto"`. `chmod 600`.
- Logs: `~/.git-hooks/pre-push.log` (hook), `~/.git-hooks/push.log` (auto-push), listener via `journalctl --user -u commit-sound`.

## HTTP API (auth: `X-Secreto` header or JSON `secreto`, `hmac.compare_digest`)

| Route | Method | Body | Auth | Notes |
|-------|--------|------|------|-------|
| `/ping` | GET | — | no | health probe, `{"ok":true}` |
| `/` | GET | — | no | web panel |
| `/play` | POST | `{"secreto","amigo"}` | yes | plays `sounds/<amigo>.*` |
| `/upload` | POST | multipart `amigo`+`som` | yes | stores sound, validates extension |
| `/api/info` | GET | — | partial | secret only if authed |
| `/api/amigos` | GET | — | no | list stored sounds |
| `/api/destinos` | GET | — | partial | secrets masked unless authed |
| `/api/status` | GET | — | no | `/ping` probe of each target |
| `/api/config` | POST | `{"apelido","destinos":[{"url","secreto"}]}` | yes | rewrites `hook-config.sh` |
| `/api/remover` | POST | `{"apelido"}` | yes | deletes friend's sound |
| `/api/testar` | POST | `{"apelido"}` | yes | local play test |

Key rules: nickname regex `^[A-Za-z0-9_.-]{1,32}$`; extensions `mp3, wav, ogg, opus, flac, m4a, aac`; playback capped at `DURACAO_MAX = 5` seconds.

## Playback order (`play_sound`)

`timeout 5` + `pw-play` → `paplay` → `aplay` (wav only) → `ffplay -nodisp -autoexit`. mp3 needs ffmpeg on the listening PC.

## Push data flow

`git push` → `pre-push` hook (reads `hook-config.sh`, fires only on `refs/heads/*`/`refs/tags/*`) → `POST <url>/play` to each target (runs before push is accepted) → listener plays sound. The hook **always `exit 0`** so a failed alert never blocks the push — preserve this.

## Hard rules for edits

- **No code comments** unless the user explicitly asks.
- **No third-party Python deps** — stdlib only (`http.server`). Keep it that way.
- Always `exit 0` in `pre-push`; French... no, pt-BR for all user-facing text/logs/README.
- Keep `DURACAO_MAX`, `testar-som.sh`'s `timeout 5`, and README "5 segundos" in sync.
- Web panel: single self-contained `index.html`, vanilla JS, `esc()` for dynamic HTML.
- Commit style: short Portuguese messages, sometimes Conventional prefixes (`feat:`, `fix:`, `docs:`).

## Environment notes

- Commits here auto-push thanks to a machine-global `~/.git-hooks/post-commit` (logs `push.log`). It's normal for a commit to be pushed immediately. Do not be surprised, and do not try to "fix" it.
- No tests exist. Sanity-check by running `bash testar-som.sh --local` or curling the listener locally.