#!/usr/bin/env python3
import argparse
import hmac
import json
import re
import secrets
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_DIR = Path.home() / ".commit-sounds"
SOUNDS_DIR = APP_DIR / "sounds"
CONFIG_PATH = APP_DIR / "config.json"

AMIGO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
VALID_EXTS = {".mp3", ".wav", ".ogg", ".opus", ".flac", ".m4a", ".aac"}

DURACAO_MAX = 4

PLAYERS = (
    ("pw-play", ("%f",)),
    ("paplay", ("%f",)),
    ("aplay", ("%f",)),
    ("ffplay", ("-nodisp", "-autoexit", "%f")),
)


def load_config():
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
        except ValueError:
            cfg = {}
    else:
        cfg = {}
    cfg.setdefault("host", "0.0.0.0")
    cfg.setdefault("porta", 8080)
    cfg.setdefault("secreto", secrets.token_hex(16))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    return cfg


def valid_amigo(nome):
    return bool(nome) and bool(AMIGO_RE.fullmatch(nome))


def play_sound(path):
    timeout = shutil.which("timeout")
    for nome, args in PLAYERS:
        exe = shutil.which(nome)
        if not exe:
            continue
        cmd = [exe] + [a.replace("%f", str(path)) for a in args]
        if timeout and DURACAO_MAX > 0:
            cmd = [timeout, str(DURACAO_MAX)] + cmd
        try:
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            continue
    return False


def parse_multipart(content_type, body):
    boundary = None
    for token in content_type.split(";"):
        token = token.strip()
        if token.lower().startswith("boundary="):
            boundary = token.split("=", 1)[1].strip().strip('"')
            break
    if not boundary:
        return {}
    sep = ("--" + boundary).encode()
    campos = {}
    for chunk in body.split(sep):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        head, _, data = chunk.partition(b"\r\n\r\n")
        nome = filename = None
        for line in head.split(b"\r\n"):
            chave, _, valor = line.partition(b":")
            if chave.strip().lower() != b"content-disposition":
                continue
            for param in valor.split(b";"):
                param = param.strip()
                if param.lower().startswith(b"name="):
                    nome = param[5:].strip(b'"').decode("utf-8", "replace")
                elif param.lower().startswith(b"filename="):
                    filename = param[9:].strip(b'"').decode("utf-8", "replace")
        if nome:
            campos[nome] = {"filename": filename or None, "content": data}
    return campos


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[commit-sounds] %s\n" % (fmt % args))

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _send_json(self, status, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authed(self, dado):
        return bool(SECRET) and hmac.compare_digest(dado or "", SECRET)

    def do_POST(self):
        rota = urlparse(self.path).path.rstrip("/")
        if rota == "/upload":
            self._upload()
        elif rota == "/play":
            self._play()
        else:
            self._send_json(404, {"erro": "rota nao existe"})

    def _upload(self):
        if not self._authed(self.headers.get("X-Secreto")):
            self._send_json(403, {"erro": "secreto invalido"})
            return
        ctype = self.headers.get("Content-Type", "")
        if not ctype.lower().startswith("multipart/form-data"):
            self._send_json(415, {"erro": "precisa ser multipart/form-data"})
            return
        campos = parse_multipart(ctype, self._read_body())
        amigo = campos.get("amigo")
        som = campos.get("som")
        if not amigo or not som:
            self._send_json(400, {"erro": "campos 'amigo' e 'som' sao obrigatorios"})
            return
        amigo = amigo["content"].decode("utf-8", "replace").strip()
        if not valid_amigo(amigo):
            self._send_json(400, {"erro": "nome de amigo invalido"})
            return
        ext = Path(som["filename"] or "som.wav").suffix.lower()
        if ext not in VALID_EXTS:
            aceitas = ", ".join(sorted(VALID_EXTS))
            self._send_json(400, {"erro": "extensao nao suportada: %s (aceitas: %s)" % (ext or "(vazia)", aceitas)})
            return
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        destino = SOUNDS_DIR / ("%s%s" % (amigo, ext))
        destino.write_bytes(som["content"])
        self._send_json(200, {"ok": True, "amigo": amigo, "arquivo": destino.name})

    def _play(self):
        dados = {}
        try:
            raw = self._read_body()
            if raw:
                dados = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        secreto_ok = self._authed(self.headers.get("X-Secreto")) or self._authed(str(dados.get("secreto", "")))
        if not secreto_ok:
            self._send_json(403, {"erro": "secreto invalido"})
            return
        amigo = str(dados.get("amigo", "")).strip()
        if not valid_amigo(amigo):
            self._send_json(400, {"erro": "nome de amigo invalido"})
            return
        matches = [p for p in SOUNDS_DIR.glob("%s.*" % amigo) if p.is_file()]
        if not matches:
            self._send_json(404, {"erro": "nao tem som para o amigo %s" % amigo})
            return
        som_path = sorted(matches)[0]
        if play_sound(som_path):
            self._send_json(200, {"ok": True, "amigo": amigo, "som": som_path.name})
        else:
            self._send_json(500, {"erro": "nenhum player de audio disponivel"})


SECRET = ""


def main():
    parser = argparse.ArgumentParser(description="commit-sounds listener")
    parser.add_argument("--init", action="store_true", help="cria/genera config.json e sai")
    args = parser.parse_args()

    cfg = load_config()
    global SECRET
    SECRET = cfg["secreto"]

    if args.init:
        print("config em %s" % CONFIG_PATH)
        print("secreto: %s" % SECRET)
        return

    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    host, port = cfg["host"], int(cfg["porta"])
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print("[commit-sounds] ouvindo em %s:%s" % (host, port))
    print("[commit-sounds] seu secreto: %s" % SECRET)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[commit-sounds] parando...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()