#!/usr/bin/env python3
import argparse
import fcntl
import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

APP_DIR = Path(os.environ.get("COMMIT_SOUNDS_DIR") or Path.home() / ".commit-sounds")
CONFIG_PATH = APP_DIR / "config.json"
AMIGOS_PATH = APP_DIR / "amigos.json"
LOCK_PATH = APP_DIR / ".amigos.lock"
CACHE_DIR = APP_DIR / "cache"
LOG_PATH = APP_DIR / "avisos.log"

APELIDO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
VALID_EXTS = {".mp3", ".wav", ".ogg", ".opus", ".flac", ".m4a", ".aac"}

DURACAO_MAX = 5
TAMANHO_MAX = 5 * 1024 * 1024
JANELA = 600
ANUNCIO_SEG = 30
ONLINE_SEG = 90
ESQUECER_SEG = 7 * 24 * 3600

BICHOS = ("frog", "cat", "duck", "fox", "wolf", "bear", "owl", "panda",
          "otter", "lynx", "tiger", "koala", "eagle", "shark", "llama", "gecko")
CORES = ("blue", "purple", "green", "black", "pink", "orange", "golden", "silver",
         "white", "gray", "red", "yellow")
ALFABETO = "abcdefghjkmnpqrstuvwxyz23456789"

PLAYERS = (
    ("pw-play", ("%f",)),
    ("paplay", ("%f",)),
    ("aplay", ("%f",)),
    ("ffplay", ("-nodisp", "-autoexit", "%f")),
)

OPENER = request.build_opener(request.ProxyHandler({}))


class Recusado(Exception):
    def __init__(self, motivo, status=403):
        super().__init__(motivo)
        self.status = status


def ler_json(path, padrao):
    try:
        dado = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return padrao
    return dado if isinstance(dado, type(padrao)) else padrao


def gravar_json(path, dado):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(json.dumps(dado, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def carregar_config():
    cfg = ler_json(CONFIG_PATH, {})
    padrao = {"id": secrets.token_hex(8), "porta": 8008, "porta_sala": 8008}
    faltou = [k for k in padrao if k not in cfg]
    for k in faltou:
        cfg[k] = padrao[k]
    if faltou:
        gravar_json(CONFIG_PATH, cfg)
    return cfg


def configurado(cfg):
    return valid_apelido(cfg.get("apelido")) and bool(cfg.get("sala"))


def valid_apelido(nome):
    return isinstance(nome, str) and bool(APELIDO_RE.fullmatch(nome))


def valid_porta(porta):
    return isinstance(porta, int) and 0 < porta < 65536


def normalizar_sala(sala):
    return "-".join(sala.strip().lower().split())


def gerar_sala():
    sufixo = "".join(secrets.choice(ALFABETO) for _ in range(6))
    return "%s-%s-%s" % (secrets.choice(BICHOS), secrets.choice(CORES), sufixo)


@functools.lru_cache(maxsize=4)
def chave(sala):
    return hashlib.pbkdf2_hmac("sha256", normalizar_sala(sala).encode(), b"commit-sounds", 200_000)


def assinar(cfg, **extra):
    dados = {
        "id": cfg["id"],
        "apelido": cfg["apelido"],
        "porta": cfg["porta"],
        "ts": int(time.time()),
        "nonce": secrets.token_hex(8),
    }
    dados.update(extra)
    d = json.dumps(dados, separators=(",", ":"))
    return {"d": d, "h": hmac.new(chave(cfg["sala"]), d.encode(), "sha256").hexdigest()}


def abrir(cfg, env, nonces=None):
    if not isinstance(env, dict) or not isinstance(env.get("d"), str) or not isinstance(env.get("h"), str):
        raise Recusado("invalid message", 400)
    esperado = hmac.new(chave(cfg["sala"]), env["d"].encode(), "sha256").hexdigest()
    if not hmac.compare_digest(esperado, env["h"]):
        raise Recusado("different room")
    try:
        dados = json.loads(env["d"])
    except ValueError:
        raise Recusado("invalid message", 400)
    if (not isinstance(dados, dict)
            or not HEX16_RE.fullmatch(str(dados.get("id", "")))
            or not valid_apelido(dados.get("apelido"))
            or not valid_porta(dados.get("porta"))):
        raise Recusado("invalid message", 400)
    ts = dados.get("ts")
    if not isinstance(ts, int) or abs(time.time() - ts) > JANELA:
        raise Recusado("clock out of sync")
    if nonces is not None and not nonces.novo(str(dados.get("nonce", ""))):
        raise Recusado("repeated message", 409)
    return dados


class Nonces:
    def __init__(self):
        self.vistos = {}
        self.lock = threading.Lock()

    def novo(self, nonce):
        agora = time.time()
        with self.lock:
            for n, t in list(self.vistos.items()):
                if agora - t > 2 * JANELA:
                    del self.vistos[n]
            if not nonce or nonce in self.vistos:
                return False
            self.vistos[nonce] = agora
            return True


NONCES = Nonces()


def atualizar_amigos(fn):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        amigos = ler_json(AMIGOS_PATH, {})
        resultado = fn(amigos)
        gravar_json(AMIGOS_PATH, amigos)
        return resultado


def registrar(dados, ip, manual=False):
    agora = int(time.time())

    def fn(amigos):
        for outro, a in list(amigos.items()):
            if outro != dados["id"] and a.get("ip") == ip and a.get("porta") == dados["porta"]:
                del amigos[outro]
        a = amigos.get(dados["id"], {})
        novo = a.get("ip") != ip or agora - a.get("visto", 0) > ONLINE_SEG
        a.update(apelido=dados["apelido"], ip=ip, porta=dados["porta"], visto=agora)
        if manual:
            a["manual"] = True
        amigos[dados["id"]] = a
        return novo

    return atualizar_amigos(fn)


def listar_amigos(cfg):
    amigos = ler_json(AMIGOS_PATH, {})
    return {k: v for k, v in amigos.items()
            if k != cfg["id"] and isinstance(v, dict) and v.get("ip") and valid_porta(v.get("porta"))}


def url_amigo(a, rota):
    return "http://%s:%s%s" % (a["ip"], a["porta"], rota)


def http(url, metodo="GET", corpo=None, cabecalhos=None, timeout=4):
    req = request.Request(url, data=corpo, method=metodo, headers=cabecalhos or {})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(TAMANHO_MAX + 1)
    except error.HTTPError as e:
        return e.code, dict(e.headers), e.read(65536)
    except (OSError, ValueError) as e:
        return 0, {}, str(e).encode()


def cabecalho_sala(cfg, tipo):
    return {"X-Sala": json.dumps(assinar(cfg, tipo=tipo))}


def erro_de(corpo):
    try:
        return str(json.loads(corpo).get("erro", "")) or corpo.decode("utf-8", "replace")
    except (ValueError, AttributeError):
        return corpo.decode("utf-8", "replace")


def meu_som(cfg):
    nome = cfg.get("som")
    if not nome:
        return None
    caminho = APP_DIR / nome
    try:
        dado = caminho.read_bytes()
    except OSError:
        return None
    return caminho, dado, hashlib.sha256(dado).hexdigest()[:16], caminho.suffix.lower()


def definir_som(cfg, origem):
    origem = Path(origem).expanduser()
    if not origem.is_file():
        return "file not found: %s" % origem
    ext = origem.suffix.lower()
    if ext not in VALID_EXTS:
        return "unsupported format: %s (accepted: %s)" % (ext or "(no extension)", ", ".join(sorted(VALID_EXTS)))
    if origem.stat().st_size > TAMANHO_MAX:
        return "file too large (max %d MB)" % (TAMANHO_MAX // (1024 * 1024))
    APP_DIR.mkdir(parents=True, exist_ok=True)
    destino = APP_DIR / ("meu-som%s" % ext)
    tmp = APP_DIR / ".meu-som.tmp"
    shutil.copyfile(origem, tmp)
    for velho in APP_DIR.glob("meu-som.*"):
        velho.unlink(missing_ok=True)
    os.replace(tmp, destino)
    cfg["som"] = destino.name
    return None


def players_instalados():
    return [nome for nome, _ in PLAYERS if shutil.which(nome)]


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
        log("%s failed (rc=%s) on %s; trying another player" % (nome, rc, path.name))
    return None


def log(msg):
    sys.stderr.write("[commit-sounds] %s\n" % msg)
    sys.stderr.flush()


def baixar_som(cfg, dados, ip, destino):
    url = url_amigo({"ip": ip, "porta": dados["porta"]}, "/som")
    status, _, corpo = http(url, cabecalhos=cabecalho_sala(cfg, "som"), timeout=5)
    if status != 200:
        return "could not download the sound from %s (HTTP %s)" % (dados["apelido"], status)
    if len(corpo) > TAMANHO_MAX:
        return "sound from %s is too large" % dados["apelido"]
    if hashlib.sha256(corpo).hexdigest()[:16] != dados["som_hash"]:
        return "downloaded sound from %s does not match its hash" % dados["apelido"]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / (".%s.tmp" % destino.name)
    tmp.write_bytes(corpo)
    for velho in CACHE_DIR.glob("%s-*" % dados["id"]):
        velho.unlink(missing_ok=True)
    os.replace(tmp, destino)
    log("downloaded the new sound from %s (%s)" % (dados["apelido"], destino.name))
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log("%s %s" % (self.client_address[0], fmt % args))

    def _json(self, status, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _autenticar(self, env):
        cfg = carregar_config()
        if not configurado(cfg):
            self._json(503, {"erro": "this PC is not set up yet"})
            return cfg, None
        try:
            dados = abrir(cfg, env, NONCES)
        except Recusado as e:
            self._json(e.status, {"erro": str(e)})
            return cfg, None
        if dados["id"] != cfg["id"]:
            registrar(dados, self.client_address[0])
        return cfg, dados

    def do_GET(self):
        rota = urlparse(self.path).path.rstrip("/")
        if rota not in ("/quem", "/som"):
            self._json(404, {"erro": "route not found"})
            return
        try:
            env = json.loads(self.headers.get("X-Sala", ""))
        except ValueError:
            env = None
        cfg, dados = self._autenticar(env)
        if not dados:
            return
        if rota == "/quem":
            self._json(200, assinar(cfg, tipo="quem"))
            return
        som = meu_som(cfg)
        if not som:
            self._json(404, {"erro": "no sound configured"})
            return
        _, corpo, som_hash, ext = som
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("X-Som-Hash", som_hash)
        self.send_header("X-Som-Ext", ext)
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/aviso":
            self._json(404, {"erro": "route not found"})
            return
        try:
            tamanho = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            tamanho = 0
        if tamanho <= 0 or tamanho > 65536:
            self.close_connection = True
            self._json(400, {"erro": "invalid body"})
            return
        try:
            env = json.loads(self.rfile.read(tamanho))
        except ValueError:
            env = None
        cfg, dados = self._autenticar(env)
        if not dados:
            return
        if dados["id"] == cfg["id"]:
            self._json(200, {"ok": True, "ignorado": "notice from myself"})
            return
        som_hash, ext = str(dados.get("som_hash", "")), dados.get("som_ext")
        if not HEX16_RE.fullmatch(som_hash) or ext not in VALID_EXTS:
            self._json(400, {"erro": "invalid sound in notice"})
            return
        if cfg.get("mudo_ate", 0) > time.time():
            self._json(200, {"ok": True, "mudo": True})
            return
        som = CACHE_DIR / ("%s-%s%s" % (dados["id"], som_hash, ext))
        if not som.is_file():
            falha = baixar_som(cfg, dados, self.client_address[0], som)
            if falha:
                log(falha)
                self._json(502, {"erro": falha})
                return
        player = play_sound(som)
        if player:
            log("playing sound from %s with %s" % (dados["apelido"], player))
            self._json(200, {"ok": True, "player": player})
        else:
            log("no player could play the sound from %s" % dados["apelido"])
            self._json(500, {"erro": "no audio player could play it"})


def enviar_oi(sock, cfg, destino, resposta=False):
    pacote = json.dumps(assinar(cfg, tipo="oi", resposta=resposta)).encode()
    try:
        sock.sendto(pacote, destino)
    except OSError:
        pass


def anunciar_sempre(sock):
    while True:
        cfg = carregar_config()
        if configurado(cfg):
            enviar_oi(sock, cfg, ("255.255.255.255", cfg["porta_sala"]))
            for a in listar_amigos(cfg).values():
                enviar_oi(sock, cfg, (a["ip"], cfg["porta_sala"]))
        time.sleep(ANUNCIO_SEG)


def servir_sala(porta_sala):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(("", porta_sala))
    except OSError as e:
        log("could not open room port %s/udp (%s); automatic discovery disabled" % (porta_sala, e))
        return
    threading.Thread(target=anunciar_sempre, args=(sock,), daemon=True).start()
    while True:
        try:
            pacote, origem = sock.recvfrom(4096)
        except OSError:
            continue
        cfg = carregar_config()
        if not configurado(cfg):
            continue
        try:
            dados = abrir(cfg, json.loads(pacote), NONCES)
        except (ValueError, Recusado):
            continue
        if dados.get("tipo") != "oi" or dados["id"] == cfg["id"]:
            continue
        if registrar(dados, origem[0]):
            log("friend in the room: %s (%s)" % (dados["apelido"], origem[0]))
            if not dados.get("resposta"):
                enviar_oi(sock, cfg, origem, resposta=True)


def podar_amigos():
    limite = time.time() - ESQUECER_SEG

    def fn(amigos):
        for k, a in list(amigos.items()):
            if not isinstance(a, dict) or (not a.get("manual") and a.get("visto", 0) < limite):
                del amigos[k]

    atualizar_amigos(fn)


def cmd_servir(args):
    cfg = carregar_config()
    if not configurado(cfg):
        log("not set up yet; run: commit-sounds setup")
        return 1
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    podar_amigos()
    httpd = ThreadingHTTPServer(("0.0.0.0", cfg["porta"]), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=servir_sala, args=(cfg["porta_sala"],), daemon=True).start()
    log("%s in the room, listening on %s/tcp and %s/udp" % (cfg["apelido"], cfg["porta"], cfg["porta_sala"]))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def enviar_avisos(cfg):
    som = meu_som(cfg)
    if not som:
        return None
    _, _, som_hash, ext = som
    corpo = json.dumps(assinar(cfg, tipo="aviso", som_hash=som_hash, som_ext=ext)).encode()
    cab = {"Content-Type": "application/json"}

    def um(a):
        status, _, resp = http(url_amigo(a, "/aviso"), "POST", corpo, cab, timeout=8)
        return a, status, resp

    amigos = list(listar_amigos(cfg).values())
    if not amigos:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(amigos))) as ex:
        return list(ex.map(um, amigos))


def cmd_avisar(args):
    cfg = carregar_config()
    linhas = []
    if not configurado(cfg):
        linhas.append("not set up - nothing to do")
    else:
        resultados = enviar_avisos(cfg)
        if resultados is None:
            linhas.append("no sound set - nothing to do")
        elif not resultados:
            linhas.append("no known friends in the room")
        for a, status, resp in resultados or []:
            if status == 0:
                linhas.append("  -> %s (%s): connection FAILED" % (a["apelido"], a["ip"]))
            else:
                linhas.append("  -> %s (%s): HTTP %s %s" % (a["apelido"], a["ip"], status,
                                                           resp.decode("utf-8", "replace").strip()))
    agora = time.strftime("%F %T")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write("%s == push by %s ==\n" % (agora, cfg.get("apelido", "?")))
        for linha in linhas:
            f.write("%s %s\n" % (agora, linha))
    return 0


def dica(status, resp, cfg):
    if status == 0:
        return "could not connect: PC is off, on another network, or its firewall is closed"
    if status == 200:
        try:
            dados = json.loads(resp)
        except ValueError:
            dados = {}
        if dados.get("mudo"):
            return "is muted"
        return "played (%s)" % dados.get("player", "?")
    erro = erro_de(resp)
    if status == 403 and erro == "different room":
        return "room code differs from yours"
    if status == 403:
        return "%s: check the date/time on both PCs" % erro
    if status == 409:
        return "duplicate notice, ignored"
    if status == 502:
        return ("could not download your sound: is the service running on this PC? "
                "is port %s/tcp open here?" % cfg["porta"])
    if status == 500:
        return "their PC could not play it: ffmpeg is probably missing there, or use a .wav"
    return "HTTP %s: %s" % (status, erro)


def cmd_testar(args):
    cfg = carregar_config()
    if not configurado(cfg):
        print("Not set up yet. Run: commit-sounds setup")
        return 1
    if args.aqui:
        som = meu_som(cfg)
        if not som:
            print("You have not picked a sound yet. Run: commit-sounds sound /path/to/sound.mp3")
            return 1
        player = play_sound(som[0])
        if player:
            print("Playing %s on this PC with %s. If you heard nothing, check volume/audio output." % (som[0].name, player))
            return 0
        print("No player could play it here (installed: %s)." % (", ".join(players_instalados()) or "none"))
        print("Install ffmpeg (sudo apt install ffmpeg) or use a .wav sound.")
        return 1
    resultados = enviar_avisos(cfg)
    if resultados is None:
        print("You have not picked a sound yet. Run: commit-sounds sound /path/to/sound.mp3")
        return 1
    if not resultados:
        print("No friends found in the room yet.")
        print("  - did they install it and use the same room code (%s)?" % cfg["sala"])
        print("  - if the network blocks discovery: commit-sounds add FRIEND_IP")
        return 1
    falhou = 0
    for a, status, resp in resultados:
        ok = status == 200 or status == 409
        falhou |= not ok
        print("  %s %-12s %-15s %s" % ("OK" if ok else "X ", a["apelido"], a["ip"], dica(status, resp, cfg)))
    return 1 if falhou else 0


def cmd_status(args):
    cfg = carregar_config()
    if not configurado(cfg):
        print("Not set up yet. Run: commit-sounds setup")
        return 1
    som = meu_som(cfg)
    local, _, _ = http("http://127.0.0.1:%s/quem" % cfg["porta"], cabecalhos=cabecalho_sala(cfg, "quem"), timeout=2)
    players = players_instalados()
    print("You:      %s" % cfg["apelido"])
    print("Room:     %s" % cfg["sala"])
    print("Sound:    %s" % (som[0].name if som else "NONE -> commit-sounds sound /path/to/sound.mp3"))
    print("Service:  %s" % ("running" if local == 200 else "STOPPED -> systemctl --user restart commit-sounds"))
    audio = ", ".join(players) if players else "NO player -> sudo apt install ffmpeg"
    if players and "ffplay" not in players:
        audio += " (no ffmpeg: friends' mp3s may not play)"
    print("Audio:    %s" % audio)
    if cfg.get("mudo_ate", 0) > time.time():
        print("Muted:    until %s" % time.strftime("%H:%M", time.localtime(cfg["mudo_ate"])))

    amigos = list(listar_amigos(cfg).values())
    print("")
    if not amigos:
        print("No friends in the room yet.")
        print("  Invite: send them the code '%s' and ask them to run bash install.sh" % cfg["sala"])
        print("  Network blocks discovery? commit-sounds add FRIEND_IP")
        return 0

    def checar(a):
        status, _, resp = http(url_amigo(a, "/quem"), cabecalhos=cabecalho_sala(cfg, "quem"), timeout=2)
        return a, status, resp

    with ThreadPoolExecutor(max_workers=min(16, len(amigos))) as ex:
        resultados = list(ex.map(checar, amigos))
    print("Friends:")
    for a, status, resp in sorted(resultados, key=lambda r: r[0]["apelido"].lower()):
        if status == 200:
            estado = "online"
        elif status == 0:
            estado = "offline (seen %s)" % tempo_atras(a.get("visto", 0))
        else:
            estado = "error: %s" % dica(status, resp, cfg)
        print("  %-12s %-21s %s" % (a["apelido"], "%s:%s" % (a["ip"], a["porta"]), estado))
    return 0


def tempo_atras(ts):
    seg = int(time.time() - ts)
    if seg < 120:
        return "just now"
    if seg < 7200:
        return "%d min ago" % (seg // 60)
    if seg < 172800:
        return "%d h ago" % (seg // 3600)
    return "%d days ago" % (seg // 86400)


def perguntar(texto, atual=None):
    sufixo = " [%s]" % atual if atual else ""
    try:
        resposta = input("%s%s: " % (texto, sufixo)).strip()
    except EOFError:
        resposta = ""
    return resposta or (atual or "")


def cmd_configurar(args):
    cfg = carregar_config()
    interativo = sys.stdin.isatty() and not (args.apelido or args.sala or args.som)

    apelido = args.apelido or cfg.get("apelido", "")
    if interativo:
        apelido = perguntar("Your nickname (letters, numbers, _ . -)", apelido or None)
        while not valid_apelido(apelido):
            print("  invalid nickname")
            apelido = perguntar("Your nickname (letters, numbers, _ . -)")
    if not valid_apelido(apelido):
        print("invalid nickname: %r" % apelido)
        return 1

    sala = args.sala or cfg.get("sala", "")
    if interativo:
        if sala:
            sala = perguntar("Room code", sala)
        else:
            sala = perguntar("Room code (Enter to create a new one)")
    sala = normalizar_sala(sala) if sala else gerar_sala()
    sala_nova = sala != cfg.get("sala")

    cfg["apelido"] = apelido
    cfg["sala"] = sala
    if args.som:
        falha = definir_som(cfg, args.som)
        if falha:
            print(falha)
            return 1
    elif interativo:
        atual = cfg.get("som") if meu_som(cfg) else None
        while True:
            texto = "Path to your sound (mp3, wav, ogg...)"
            caminho = perguntar(texto + (" [Enter keeps the current one]" if atual else ""))
            if not caminho and atual:
                break
            if not caminho:
                print("  a sound is required; e.g. ~/Downloads/laugh.mp3")
                continue
            falha = definir_som(cfg, caminho)
            if not falha:
                break
            print("  " + falha)
    gravar_json(CONFIG_PATH, cfg)
    if sala_nova:
        atualizar_amigos(lambda amigos: amigos.clear())

    print("")
    print("Done: %s in room '%s'." % (apelido, sala))
    print("To invite friends, send them this room code.")
    return 0


def cmd_som(args):
    cfg = carregar_config()
    falha = definir_som(cfg, args.arquivo)
    if falha:
        print(falha)
        return 1
    gravar_json(CONFIG_PATH, cfg)
    print("Sound changed to %s. Friends get the new one on your next push." % Path(args.arquivo).name)
    return 0


def cmd_sala(args):
    cfg = carregar_config()
    if not configurado(cfg):
        print("Not set up yet. Run: commit-sounds setup")
        return 1
    print(cfg["sala"])
    if sys.stdout.isatty():
        print("")
        print("To join: clone commit-sounds, run 'bash install.sh' and use this code.")
    return 0


def cmd_adicionar(args):
    cfg = carregar_config()
    if not configurado(cfg):
        print("Not set up yet. Run: commit-sounds setup")
        return 1
    host, _, porta = args.endereco.replace("http://", "").rstrip("/").partition(":")
    porta = int(porta) if porta.isdigit() else 8008
    if not HOST_RE.fullmatch(host) or not valid_porta(porta):
        print("invalid address: %s (e.g. 192.168.0.15 or 192.168.0.15:8008)" % args.endereco)
        return 1
    status, _, resp = http("http://%s:%s/quem" % (host, porta), cabecalhos=cabecalho_sala(cfg, "quem"))
    if status != 200:
        print("Could not reach %s:%s -> %s" % (host, porta, dica(status, resp, cfg)))
        return 1
    try:
        dados = abrir(cfg, json.loads(resp))
    except (ValueError, Recusado) as e:
        print("Unexpected reply from %s:%s (%s)" % (host, porta, e))
        return 1
    if dados["id"] == cfg["id"]:
        print("That address is your own PC.")
        return 1
    registrar(dados, host, manual=True)
    print("Added: %s (%s:%s)" % (dados["apelido"], host, porta))
    return 0


def cmd_remover(args):
    cfg = carregar_config()

    def fn(amigos):
        alvos = [k for k, a in amigos.items() if isinstance(a, dict) and a.get("apelido", "").lower() == args.apelido.lower()]
        for k in alvos:
            del amigos[k]
        return len(alvos)

    if atualizar_amigos(fn):
        print("Removed: %s (if they are still in the room, they will show up again on their own)" % args.apelido)
        return 0
    print("No friend named %s" % args.apelido)
    return 1


def cmd_mudo(args):
    cfg = carregar_config()
    texto = (args.minutos or "60").lower()
    if texto in ("0", "off", "no"):
        cfg.pop("mudo_ate", None)
        gravar_json(CONFIG_PATH, cfg)
        print("Mute off.")
        return 0
    if not texto.isdigit():
        print("usage: commit-sounds mute [minutes | off]")
        return 1
    cfg["mudo_ate"] = int(time.time()) + int(texto) * 60
    gravar_json(CONFIG_PATH, cfg)
    print("Muted until %s. To unmute sooner: commit-sounds mute off" % time.strftime("%H:%M", time.localtime(cfg["mudo_ate"])))
    return 0


def main():
    parser = argparse.ArgumentParser(prog="commit-sounds", description="plays your friends' sounds when they git push")
    sub = parser.add_subparsers(dest="comando")

    sub.add_parser("status", help="show your config and which friends are online")
    p = sub.add_parser("test", help="play your sound on your friends' PCs now")
    p.add_argument("--here", dest="aqui", action="store_true", help="play your sound on this PC, to test the audio")
    p = sub.add_parser("sound", help="change your sound")
    p.add_argument("arquivo", metavar="file")
    sub.add_parser("room", help="show the room code to invite someone")
    p = sub.add_parser("add", help="add a friend by IP, if automatic discovery fails")
    p.add_argument("endereco", metavar="address", help="IP or IP:port")
    p = sub.add_parser("remove", help="forget a friend")
    p.add_argument("apelido", metavar="nickname")
    p = sub.add_parser("mute", help="silence sounds for a while")
    p.add_argument("minutos", metavar="minutes", nargs="?", help="minutes (default 60) or off")
    p = sub.add_parser("setup", help="set nickname, room and sound")
    p.add_argument("--nick", dest="apelido")
    p.add_argument("--room", dest="sala")
    p.add_argument("--sound", dest="som")
    sub.add_parser("serve", help="run the service (used by systemd)")
    sub.add_parser("notify", help="notify friends of a push (used by the hook)")

    legado = {"testar": "test", "som": "sound", "sala": "room", "adicionar": "add", "remover": "remove",
              "mudo": "mute", "configurar": "setup", "servir": "serve", "avisar": "notify"}
    argv = sys.argv[1:]
    if argv and argv[0] in legado:
        argv[0] = legado[argv[0]]
    args = parser.parse_args(argv)
    comandos = {
        "status": cmd_status,
        "test": cmd_testar,
        "sound": cmd_som,
        "room": cmd_sala,
        "add": cmd_adicionar,
        "remove": cmd_remover,
        "mute": cmd_mudo,
        "setup": cmd_configurar,
        "serve": cmd_servir,
        "notify": cmd_avisar,
    }
    return comandos.get(args.comando or "status")(args)


if __name__ == "__main__":
    sys.exit(main())
