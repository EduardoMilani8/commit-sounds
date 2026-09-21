#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HOME/.commit-sounds"

mkdir -p "$DIR/sounds"
install -m 755 "$SCRIPTS_DIR/listener.py" "$DIR/listener.py"

falta=()
command -v curl >/dev/null 2>&1 || falta+=("curl")
if ! command -v pw-play >/dev/null 2>&1 && ! command -v paplay >/dev/null 2>&1 && ! command -v aplay >/dev/null 2>&1; then
    falta+=("player")
fi
command -v ffplay >/dev/null 2>&1 || falta+=("ffmpeg")

if [[ ${#falta[@]} -gt 0 ]]; then
    echo "faltam dependencias: ${falta[*]}"
    if command -v apt-get >/dev/null 2>&1; then
        echo "instalando via apt (pode pedir a senha do sudo)..."
        sudo apt-get update -qq || true
        sudo apt-get install -y curl pipewire-pulse pulseaudio-utils alsa-utils ffmpeg || true
    else
        echo "  sem apt-get; instale manualmente: curl, um player de audio (pipewire-pulse/pulseaudio-utils/alsa-utils) e ffmpeg"
    fi
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "  aviso: curl nao instalado; o hook nao conseguira avisar os amigos"
fi
if ! command -v pw-play >/dev/null 2>&1 && ! command -v paplay >/dev/null 2>&1 && ! command -v aplay >/dev/null 2>&1; then
    echo "  aviso: nenhum player de audio; os sons nao vao tocar"
fi
if ! command -v ffplay >/dev/null 2>&1; then
    echo "  aviso: ffmpeg nao instalado; mp3 nao vai tocar"
fi

if [[ ! -f "$DIR/config.json" ]]; then
    python3 "$DIR/listener.py" --init
fi

PYREAD='import json,os;p=os.path.expanduser("~/.commit-sounds/config.json");print(json.load(open(p))["secreto"])'
SECRETO="$(python3 -c "$PYREAD")"
PORTA="$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.commit-sounds/config.json")))["porta"])')"

UNIDADE="$HOME/.config/systemd/user/commit-sound.service"
mkdir -p "$HOME/.config/systemd/user"

cat > "$UNIDADE" <<EOF
[Unit]
Description=commit-sounds listener
After=network.target

[Service]
WorkingDirectory=$DIR
ExecStart=/usr/bin/env python3 $DIR/listener.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1; then
    systemctl --user enable --now commit-sound.service
    RODANDO="via systemd (ativa no login)"
else
    RODANDO="sem systemd acessivel; suba manual: nohup python3 $DIR/listener.py &"
fi

IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')" || IP=""

echo ""
echo "=============================================="
echo "commit-sounds listener OK"
echo "  rodando:  $RODANDO"
echo "  config:   $DIR/config.json"
echo "  sons:     $DIR/sounds/"
echo "=============================================="
echo "Compartilhe com seus amigos:"
if [[ -n "$IP" ]]; then
    echo "  1) URL:   http://$IP:$PORTA"
else
    echo "  1) URL:   rode 'ip route get 1.1.1.1' e ache seu IP, use http://SEU_IP:$PORTA"
fi
echo "  2) SECRETO: $SECRETO"
echo ""
echo "No PC do amigo:"
echo "  bash $SCRIPTS_DIR/install-hook.sh"
echo "  bash $SCRIPTS_DIR/upload-som.sh /caminho/som.mp3"