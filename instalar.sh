#!/usr/bin/env bash
set -euo pipefail

ORIGEM="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HOME/.commit-sounds"
BIN="$HOME/.local/bin"
UNIDADES="$HOME/.config/systemd/user"

echo "== commit-sounds: instalacao =="

if ! command -v python3 >/dev/null 2>&1; then
    echo "precisa do python3 instalado" >&2
    exit 1
fi

pacotes=()
if ! command -v pw-play >/dev/null 2>&1 && ! command -v paplay >/dev/null 2>&1 && ! command -v aplay >/dev/null 2>&1; then
    pacotes+=(pulseaudio-utils alsa-utils)
fi
command -v ffplay >/dev/null 2>&1 || pacotes+=(ffmpeg)
command -v setsid >/dev/null 2>&1 || pacotes+=(util-linux)
if [[ ${#pacotes[@]} -gt 0 ]]; then
    if command -v apt-get >/dev/null 2>&1; then
        echo "instalando dependencias: ${pacotes[*]} (pode pedir a senha do sudo)"
        sudo apt-get update -qq || true
        sudo apt-get install -y "${pacotes[@]}" || true
    else
        echo "aviso: instale manualmente: ${pacotes[*]}"
    fi
fi

if [[ -f "$UNIDADES/commit-sound.service" ]]; then
    echo "removendo a versao antiga..."
    systemctl --user disable --now commit-sound.service >/dev/null 2>&1 || true
    rm -f "$UNIDADES/commit-sound.service"
fi
rm -f "$DIR/listener.py"
if [[ -f "$DIR/config.json" ]] && grep -q '"secreto"' "$DIR/config.json"; then
    mv "$DIR/config.json" "$DIR/config.antigo.json"
fi

mkdir -p "$DIR" "$BIN"
install -m 755 "$ORIGEM/commit_sounds.py" "$DIR/commit_sounds.py"
ln -sf "$DIR/commit_sounds.py" "$BIN/commit-sounds"

HOOKS="$(git config --global core.hooksPath || true)"
HOOKS="${HOOKS/#\~/$HOME}"
if [[ -z "$HOOKS" ]]; then
    HOOKS="$HOME/.git-hooks"
    git config --global core.hooksPath "$HOOKS"
fi
mkdir -p "$HOOKS"
if [[ -f "$HOOKS/pre-push" ]] && ! grep -qE 'commit_sounds\.py|CS_TARGETS' "$HOOKS/pre-push"; then
    mv "$HOOKS/pre-push" "$HOOKS/pre-push.antes-commit-sounds"
    echo "aviso: ja existia um pre-push seu; guardei em $HOOKS/pre-push.antes-commit-sounds"
fi
install -m 755 "$ORIGEM/hook/pre-push" "$HOOKS/pre-push"

echo ""
python3 "$DIR/commit_sounds.py" configurar

mkdir -p "$UNIDADES"
cat > "$UNIDADES/commit-sounds.service" <<UNIT
[Unit]
Description=commit-sounds
After=network-online.target

[Service]
ExecStart=/usr/bin/env python3 $DIR/commit_sounds.py servir
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
UNIT

if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable commit-sounds.service >/dev/null 2>&1
    systemctl --user restart commit-sounds.service
else
    echo "aviso: sem systemd de usuario; suba na mao: nohup commit-sounds servir &"
fi

PORTAS="$(python3 -c 'import json,sys;c=json.load(open(sys.argv[1]));print(c["porta"],c["porta_sala"])' "$DIR/config.json")"
read -r PORTA PORTA_SALA <<<"$PORTAS"
if command -v ufw >/dev/null 2>&1 && grep -qs '^ENABLED=yes' /etc/ufw/ufw.conf; then
    echo "liberando as portas $PORTA/tcp e $PORTA_SALA/udp no firewall (ufw)..."
    sudo ufw allow "$PORTA/tcp" >/dev/null || echo "aviso: nao consegui liberar $PORTA/tcp"
    sudo ufw allow "$PORTA_SALA/udp" >/dev/null || echo "aviso: nao consegui liberar $PORTA_SALA/udp"
fi

echo ""
echo "procurando amigos na rede..."
sleep 3
echo ""
python3 "$DIR/commit_sounds.py" status || true

echo ""
case ":$PATH:" in
    *":$BIN:"*) echo "Pronto! Use 'commit-sounds' para ver os comandos." ;;
    *) echo "Pronto! Abra um terminal novo para o comando 'commit-sounds' funcionar." ;;
esac
