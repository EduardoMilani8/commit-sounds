# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

**commit-sounds** is a LAN toy for friends: when you run `git push`, your friends' PCs play your custom sound. When they push, your PC plays theirs.

- **No central server.** Friends join a **room** ("sala") by sharing one code (e.g. `sapo-azul-7k2mpq`). Peers find each other by UDP broadcast; no IPs or per-PC secrets are exchanged.
- The repo holds only the **source**. Real installs are copies under `~/.commit-sounds/` (program + state) and the global hooks dir (hook). Editing a repo file changes nothing on this machine until it is reinstalled (see Development).
- The user-facing manual is `README.md` (written in **pt-BR**). Code, logs and messages are also Portuguese.
- Linux only. The previous design (`listener.py` + per-PC secrets + `upload-som.sh`) was discontinued; no backward compatibility.

## Files

| File (in repo) | Installed at | Purpose |
|----------------|--------------|---------|
| `commit_sounds.py` | `~/.commit-sounds/commit_sounds.py`, symlinked as `~/.local/bin/commit-sounds` | Everything: daemon (`servir`), hook sender (`avisar`), and user CLI |
| `hook/pre-push` | `<core.hooksPath>/pre-push` (default `~/.git-hooks`) | On push of `refs/heads/*`/`refs/tags/*` (by **remote** ref, non-deletion) runs `commit_sounds.py avisar` detached via `setsid nohup ... &`, then `exit 0` |
| `instalar.sh` | — | Installs deps via apt, removes the old `commit-sound` unit/`listener.py`, copies program, installs hook (backs up a foreign `pre-push`), runs `configurar` interactively, writes + enables systemd user unit `commit-sounds`, opens ufw ports if ufw is enabled, prints `status` |

## CLI (`commit-sounds <cmd>`)

`status` (default), `testar [--aqui]`, `som <arquivo>`, `sala`, `adicionar <ip[:porta]>`, `remover <apelido>`, `mudo [min|off]`, `configurar [--apelido --sala --som]` (interactive only when stdin is a TTY and no flags), plus internal `servir` and `avisar`.

## Runtime state (`~/.commit-sounds/`, overridable with env `COMMIT_SOUNDS_DIR`)

- `config.json` — `{id, apelido, sala, som, porta, porta_sala, mudo_ate?}`. `id` (16 hex) is the stable peer identity; `apelido` is only a label. Missing `id/porta/porta_sala` are filled on load.
- `meu-som.<ext>` — copy of the user's sound (`config.som` holds the filename).
- `amigos.json` — `{id: {apelido, ip, porta, visto, manual?}}`, written under `flock(.amigos.lock)`. Auto-discovered peers unseen for 7 days are pruned at daemon start; `manual` ones are kept.
- `cache/<peer_id>-<hash16>.<ext>` — friends' sounds; older versions of the same peer are deleted on download.
- `avisos.log` — results of each push alert. Daemon logs go to `journalctl --user -u commit-sounds`.

## Protocol

- **Auth**: key = `pbkdf2_hmac(sha256, normalized sala, "commit-sounds", 200k)` (cached). Every message is an envelope `{"d": <json string>, "h": hmac_sha256(key, d)}`; `d` always carries `id, apelido, porta, ts, nonce`. `abrir` rejects bad HMAC (403 `sala diferente`), `|now-ts| > 600s` (403 `relogio fora de sincronia`), and reused nonces (409 `mensagem repetida`). Any authenticated contact registers the sender (IP from the socket) in `amigos.json`.
- **Discovery (UDP `porta_sala`, default 8008)**: every 30 s a signed `tipo=oi` is sent to `255.255.255.255` and unicast to every known peer. A receiver that sees a new/stale peer replies once with `resposta=true`.
- **HTTP (TCP `porta`, default 8008)**:
  - `GET /quem` (header `X-Sala: <envelope>`) → signed envelope about this peer. Used by `status` and `adicionar`.
  - `GET /som` (header `X-Sala`) → raw bytes of `meu-som.*`.
  - `POST /aviso` (body = envelope with `som_hash`, `som_ext`) → if muted `200 {mudo}`; if the sound isn't cached, fetches `/som` from the sender and verifies the hash (`502` on failure); plays it: `200 {player}` or `500`.
- The sender builds **one** aviso envelope and posts it to every peer in parallel, so a peer reachable at two stale addresses plays once (the second gets 409).

## Audio playback (`play_sound`)

Players are tried in order: `pw-play` → `paplay` → `aplay` (WAV only) → `ffplay -nodisp -autoexit`. Each runs as `timeout DURACAO_MAX <player> <file>` in its own session. The daemon waits **1 s**: a player still running counts as success; one that exits non-zero within 1 s falls through to the next. So a `200` means "a player started", not "sound was heard". mp3 generally needs ffmpeg on the **listening** PC.

`DURACAO_MAX = 5` caps playback and must stay in sync with the "5 segundos" in `README.md`. `TAMANHO_MAX` (5 MB) likewise.

## Invariants

- The hook must never block or slow a push: it only backgrounds `avisar` and always `exit 0`. It runs **before** the remote accepts the push, so a rejected push still plays.
- A PC never plays its own push (`/aviso` from its own `id` is ignored; `avisar` skips its own `id`).
- Changing `sala` via `configurar` clears `amigos.json`.

## Development

No build, lint or test suite. Dependencies: bash, python3 stdlib, a player (+ ffmpeg for mp3), `setsid` (util-linux).

Test two peers on one machine without touching the real install (both share `porta_sala`, which works because the UDP socket uses `SO_REUSEADDR`; put a fake `pw-play` first in `PATH` to avoid real audio):

```bash
mkdir -p /tmp/cs/A /tmp/cs/B
echo '{"porta":18081,"porta_sala":18008}' > /tmp/cs/A/config.json
echo '{"porta":18082,"porta_sala":18008}' > /tmp/cs/B/config.json
COMMIT_SOUNDS_DIR=/tmp/cs/A python3 commit_sounds.py configurar --apelido Ana --som a.wav
COMMIT_SOUNDS_DIR=/tmp/cs/B python3 commit_sounds.py configurar --apelido Beto --som b.wav \
  --sala "$(COMMIT_SOUNDS_DIR=/tmp/cs/A python3 commit_sounds.py sala)"
COMMIT_SOUNDS_DIR=/tmp/cs/A python3 commit_sounds.py servir &
COMMIT_SOUNDS_DIR=/tmp/cs/B python3 commit_sounds.py servir &
COMMIT_SOUNDS_DIR=/tmp/cs/A python3 commit_sounds.py status
COMMIT_SOUNDS_DIR=/tmp/cs/A python3 commit_sounds.py testar
```

Deploy edits to this machine:

```bash
install -m 755 commit_sounds.py ~/.commit-sounds/commit_sounds.py && systemctl --user restart commit-sounds
install -m 755 hook/pre-push "$(git config --global core.hooksPath)/pre-push"
```

(`bash instalar.sh` also works and is idempotent, but re-asks the three questions; Enter keeps current values.)

## Conventions & gotchas

- **Do not add code comments** unless the user explicitly asks.
- Keep the **pt-BR** voice (runtime messages/logs are unaccented ASCII, e.g. `nao`, `invalido`; README is accented).
- **stdlib only** (`http.server`, `urllib` with proxies disabled, `socket`). No third-party deps.
- Shell scripts target bash on Debian/Ubuntu (`apt-get` in the installer).
- **Commit style**: short Portuguese messages, often with Conventional prefixes (`feat:`, `fix:`, `docs:`).
- **Committing here pushes immediately.** A user-global `~/.git-hooks/post-commit` runs `git push` when the branch has an upstream (logs to `push.log`). That push fires `pre-push`, which **plays your sound on your friends' PCs**. Only commit when the user asks.
