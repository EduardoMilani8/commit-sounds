#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HOME/.commit-sounds"

mkdir -p "$DIR/sounds"
install -m 755 "$SCRIPTS_DIR/listener.py" "$DIR/listener.py"

if ! command -v ffplay >/dev/null 2>&1; then
    echo "ffmpeg nao encontrado (necessario p/ tocar mp3); tentando instalar..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq && sudo apt-get install -y ffmpeg || true
    fi
    if ! command -v ffplay >/dev/null 2>&1; then
        echo "  aviso: nao consegui instalar ffmpeg; mp3 pode nao tocar (instale com o gerenciador de pacotes do seu sistema)"
    fi
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