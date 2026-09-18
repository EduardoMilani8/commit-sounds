#!/usr/bin/env python3
import argparse
import hmac
import json
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

APP_DIR = Path.home() / ".commit-sounds"
SOUNDS_DIR = APP_DIR / "sounds"
CONFIG_PATH = APP_DIR / "config.json"
HOOK_CONFIG = Path.home() / ".git-hooks" / "hook-config.sh"
WEB_DIR = APP_DIR / "web"
WEB_INDEX = WEB_DIR / "index.html"

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


def mask_secreto(token):
    if not token:
        return ""
    if len(token) <= 4:
        return "*" * len(token)
    return token[:4] + "..."


def ler_hook_config():
    if not HOOK_CONFIG.exists():
        return None
    texto = HOOK_CONFIG.read_text()
    m = re.search(r'CS_AMIGO="([^"]*)"', texto)
    destinos = []
    for linha in re.findall(r'^\s*"([^"]+)"\s*$', texto, re.M):
        url, sep, token = linha.partition("|")
        if not sep or not url:
            continue
        destinos.append({"url": url, "secreto": token})
    return {"apelido": m.group(1) if m else "", "destinos": destinos}


def escrever_hook_config(apelido, destinos):
    HOOK_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    linhas = ['CS_AMIGO="%s"' % apelido, "", "CS_TARGETS=("]
    for d in destinos:
        linhas.append('  "%s|%s"' % (d["url"], d["secreto"]))
    linhas.append(")")
    HOOK_CONFIG.write_text("\n".join(linhas) + "\n")
    HOOK_CONFIG.chmod(0o600)


def probe(url):
    try:
        with urlopen(url.rstrip("/") + "/ping", timeout=3) as r:
            return True, r.status
    except Exception as ex:
        return False, type(ex).__name__


def local_ip():
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return ""


def play_sound(path):
    timeout = shutil.which("timeout")
    for nome, args in PLAYERS:
        if nome == "aplay" and path.suffix.lower() != ".wav":
            continue
        exe = shutil.which(nome)
        if not exe:
            continue
        cmd = [exe] + [a.replace("%f", str(path)) for a in args]
        if timeout and DURACAO_MAX > 0:
            cmd = [timeout, str(DURACAO_MAX)] + cmd
        try:
            proc = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            continue
        try:
            rc = proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            return nome
        if rc == 0:
            return nome
        sys.stderr.write(
            "[commit-sounds] %s falhou (rc=%s) em %s; tentando outro player\n"
            % (nome, rc, path.name)
        )
    return None


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

    def _read_json_body(self):
        raw = self._read_body()
        if not raw:
            return {}
        try:
            dados = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return {}
        return dados if isinstance(dados, dict) else {}

    def do_POST(self):
        rota = urlparse(self.path).path.rstrip("/")
        if rota == "/upload":
            self._upload()
        elif rota == "/play":
            self._play()
        elif rota == "/api/config":
            self._api_config()
        elif rota == "/api/remover":
            self._api_remover()
        elif rota == "/api/testar":
            self._api_testar()
        else:
            self._send_json(404, {"erro": "rota nao existe"})

    def do_GET(self):
        rota = urlparse(self.path).path.rstrip("/")
        if rota in ("", "/"):
            self._serve_index()
        elif rota == "/ping":
            self._send_json(200, {"ok": True})
        elif rota == "/api/info":
            self._api_info()
        elif rota == "/api/amigos":
            self._api_amigos()
        elif rota == "/api/destinos":
            self._api_destinos()
        elif rota == "/api/status":
            self._api_status()
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
        player = play_sound(som_path)
        if player:
            self.log_message("tocando %s (amigo=%s) com %s", som_path.name, amigo, player)
            self._send_json(200, {"ok": True, "amigo": amigo, "som": som_path.name, "player": player})
        else:
            self.log_message("sem player p/ %s (amigo=%s)", som_path.name, amigo)
            self._send_json(500, {"erro": "nenhum player de audio disponivel"})

    def _api_info(self):
        ip = local_ip()
        url = ("http://%s:%s" % (ip, PORTA)) if ip else ("http://127.0.0.1:%s" % PORTA)
        info = {
            "ok": True,
            "url_painel": url,
            "porta": PORTA,
            "secreto": SECRET if self._authed(self.headers.get("X-Secreto")) else None,
            "players": [n for n, _ in PLAYERS if shutil.which(n)],
            "pasta_sons": str(SOUNDS_DIR),
        }
        self._send_json(200, info)

    def _api_amigos(self):
        amigos = []
        for p in sorted(SOUNDS_DIR.glob("*")):
            if not p.is_file():
                continue
            st = p.stat()
            amigos.append({
                "apelido": p.stem,
                "arquivo": p.name,
                "tamanho": st.st_size,
                "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m %H:%M"),
            })
        self._send_json(200, {"ok": True, "amigos": amigos})

    def _api_destinos(self):
        cfg = ler_hook_config()
        if cfg is None:
            self._send_json(200, {"ok": True, "configurado": False, "apelido": "", "destinos": []})
            return
        if self._authed(self.headers.get("X-Secreto")):
            destinos = [{"url": d["url"], "secreto": d["secreto"]} for d in cfg["destinos"]]
        else:
            destinos = [{"url": d["url"], "secreto": mask_secreto(d["secreto"])} for d in cfg["destinos"]]
        self._send_json(200, {"ok": True, "configurado": True, "apelido": cfg["apelido"], "destinos": destinos})

    def _api_status(self):
        cfg = ler_hook_config()
        status = []
        for d in (cfg["destinos"] if cfg else []):
            ok, codigo = probe(d["url"])
            status.append({"url": d["url"], "ok": ok, "codigo": codigo})
        self._send_json(200, {"ok": True, "status": status})

    def _api_config(self):
        if not self._authed(self.headers.get("X-Secreto")):
            self._send_json(403, {"erro": "secreto invalido"})
            return
        dados = self._read_json_body()
        apelido = str(dados.get("apelido", "")).strip()
        if not valid_amigo(apelido):
            self._send_json(400, {"erro": "apelido invalido (letras, numeros, _ . -)"})
            return
        destinos_raw = dados.get("destinos", [])
        if not isinstance(destinos_raw, list):
            self._send_json(400, {"erro": "destinos precisa ser uma lista"})
            return
        destinos = []
        for d in destinos_raw:
            if not isinstance(d, dict):
                continue
            url = str(d.get("url", "")).strip().rstrip("/")
            token = str(d.get("secreto", "")).strip()
            if url.startswith(("http://", "https://")) and token:
                destinos.append({"url": url, "secreto": token})
        escrever_hook_config(apelido, destinos)
        self._send_json(200, {"ok": True, "destinos_salvos": len(destinos)})

    def _api_remover(self):
        if not self._authed(self.headers.get("X-Secreto")):
            self._send_json(403, {"erro": "secreto invalido"})
            return
        dados = self._read_json_body()
        apelido = str(dados.get("apelido", "")).strip()
        if not valid_amigo(apelido):
            self._send_json(400, {"erro": "apelido invalido (letras, numeros, _ . -)"})
            return
        matches = sorted(p for p in SOUNDS_DIR.glob("%s.*" % apelido) if p.is_file())
        if not matches:
            self._send_json(404, {"erro": "nao tem som do amigo %s" % apelido})
            return
        for p in matches:
            p.unlink()
        self._send_json(200, {"ok": True, "apelido": apelido, "removidos": [p.name for p in matches]})

    def _api_testar(self):
        if not self._authed(self.headers.get("X-Secreto")):
            self._send_json(403, {"erro": "secreto invalido"})
            return
        dados = self._read_json_body()
        apelido = str(dados.get("apelido", "")).strip()
        if not valid_amigo(apelido):
            self._send_json(400, {"erro": "apelido invalido (letras, numeros, _ . -)"})
            return
        matches = sorted(p for p in SOUNDS_DIR.glob("%s.*" % apelido) if p.is_file())
        if not matches:
            self._send_json(404, {"erro": "nao tem som do amigo %s" % apelido})
            return
        player = play_sound(matches[0])
        if player:
            self._send_json(200, {"ok": True, "som": matches[0].name, "player": player})
        else:
            self._send_json(500, {"erro": "nenhum player de audio disponivel"})

    def _serve_index(self):
        if WEB_INDEX.exists():
            html = WEB_INDEX.read_bytes()
        else:
            html = "<h1>commit-sounds</h1><p>painel web nao instalado.</p>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


SECRET = ""
HOST = ""
PORTA = 0


def main():
    parser = argparse.ArgumentParser(description="commit-sounds listener")
    parser.add_argument("--init", action="store_true", help="cria/genera config.json e sai")
    args = parser.parse_args()

    cfg = load_config()
    global SECRET, HOST, PORTA
    SECRET = cfg["secreto"]
    HOST = cfg["host"]
    PORTA = int(cfg["porta"])

    if args.init:
        print("config em %s" % CONFIG_PATH)
        print("secreto: %s" % SECRET)
        return

    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORTA), Handler)
    httpd.daemon_threads = True
    print("[commit-sounds] ouvindo em %s:%s" % (HOST, PORTA))
    print("[commit-sounds] painel web: http://localhost:%s" % PORTA)
    print("[commit-sounds] seu secreto: %s" % SECRET)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[commit-sounds] parando...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()