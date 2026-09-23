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

BICHOS = ("sapo", "gato", "pato", "tatu", "onca", "lobo", "urso", "boto",
          "mico", "anta", "capivara", "jacare", "tucano", "coruja", "galo", "arara")
CORES = ("azul", "roxo", "verde", "preto", "rosa", "laranja", "dourado", "prata",
         "branco", "cinza", "vermelho", "amarelo")
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
    padrao = {"id": secrets.token_hex(8), "porta": 8080, "porta_sala": 8080}
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
        raise Recusado("mensagem invalida", 400)
    esperado = hmac.new(chave(cfg["sala"]), env["d"].encode(), "sha256").hexdigest()
    if not hmac.compare_digest(esperado, env["h"]):
        raise Recusado("sala diferente")
    try:
        dados = json.loads(env["d"])
    except ValueError:
        raise Recusado("mensagem invalida", 400)
    if (not isinstance(dados, dict)
            or not HEX16_RE.fullmatch(str(dados.get("id", "")))
            or not valid_apelido(dados.get("apelido"))
            or not valid_porta(dados.get("porta"))):
        raise Recusado("mensagem invalida", 400)
    ts = dados.get("ts")
    if not isinstance(ts, int) or abs(time.time() - ts) > JANELA:
        raise Recusado("relogio fora de sincronia")
    if nonces is not None and not nonces.novo(str(dados.get("nonce", ""))):
        raise Recusado("mensagem repetida", 409)
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
        return "arquivo nao encontrado: %s" % origem
    ext = origem.suffix.lower()
    if ext not in VALID_EXTS:
        return "formato nao suportado: %s (aceitos: %s)" % (ext or "(sem extensao)", ", ".join(sorted(VALID_EXTS)))
    if origem.stat().st_size > TAMANHO_MAX:
        return "arquivo grande demais (maximo %d MB)" % (TAMANHO_MAX // (1024 * 1024))
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
        log("%s falhou (rc=%s) em %s; tentando outro player" % (nome, rc, path.name))
    return None


def log(msg):
    sys.stderr.write("[commit-sounds] %s\n" % msg)
    sys.stderr.flush()


def baixar_som(cfg, dados, ip, destino):
    url = url_amigo({"ip": ip, "porta": dados["porta"]}, "/som")
    status, _, corpo = http(url, cabecalhos=cabecalho_sala(cfg, "som"), timeout=5)
    if status != 200:
        return "nao consegui baixar o som de %s (HTTP %s)" % (dados["apelido"], status)
    if len(corpo) > TAMANHO_MAX:
        return "som de %s grande demais" % dados["apelido"]
    if hashlib.sha256(corpo).hexdigest()[:16] != dados["som_hash"]:
        return "som baixado de %s nao confere" % dados["apelido"]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / (".%s.tmp" % destino.name)
    tmp.write_bytes(corpo)
    for velho in CACHE_DIR.glob("%s-*" % dados["id"]):
        velho.unlink(missing_ok=True)
    os.replace(tmp, destino)
    log("baixei o som novo de %s (%s)" % (dados["apelido"], destino.name))
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
            self._json(503, {"erro": "este PC ainda nao foi configurado"})
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
            self._json(404, {"erro": "rota nao existe"})
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
            self._json(404, {"erro": "sem som configurado"})
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
            self._json(404, {"erro": "rota nao existe"})
            return
        try:
            tamanho = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            tamanho = 0
        if tamanho <= 0 or tamanho > 65536:
            self.close_connection = True
            self._json(400, {"erro": "corpo invalido"})
            return
        try:
            env = json.loads(self.rfile.read(tamanho))
        except ValueError:
            env = None
        cfg, dados = self._autenticar(env)
        if not dados:
            return
        if dados["id"] == cfg["id"]:
            self._json(200, {"ok": True, "ignorado": "aviso de mim mesmo"})
            return
        som_hash, ext = str(dados.get("som_hash", "")), dados.get("som_ext")
        if not HEX16_RE.fullmatch(som_hash) or ext not in VALID_EXTS:
            self._json(400, {"erro": "som invalido no aviso"})
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
            log("tocando som de %s com %s" % (dados["apelido"], player))
            self._json(200, {"ok": True, "player": player})
        else:
            log("nenhum player conseguiu tocar o som de %s" % dados["apelido"])
            self._json(500, {"erro": "nenhum player de audio conseguiu tocar"})


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
        log("nao consegui abrir a porta da sala %s/udp (%s); descoberta automatica desligada" % (porta_sala, e))
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
            log("amigo na sala: %s (%s)" % (dados["apelido"], origem[0]))
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
        log("nao configurado ainda; rode: commit-sounds configurar")
        return 1
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    podar_amigos()
    httpd = ThreadingHTTPServer(("0.0.0.0", cfg["porta"]), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=servir_sala, args=(cfg["porta_sala"],), daemon=True).start()
    log("%s na sala, ouvindo em %s/tcp e %s/udp" % (cfg["apelido"], cfg["porta"], cfg["porta_sala"]))
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
        linhas.append("nao configurado - nada a fazer")
    else:
        resultados = enviar_avisos(cfg)
        if resultados is None:
            linhas.append("sem som configurado - nada a fazer")
        elif not resultados:
            linhas.append("nenhum amigo conhecido na sala")
        for a, status, resp in resultados or []:
            if status == 0:
                linhas.append("  -> %s (%s): FALHA de conexao" % (a["apelido"], a["ip"]))
            else:
                linhas.append("  -> %s (%s): HTTP %s %s" % (a["apelido"], a["ip"], status,
                                                           resp.decode("utf-8", "replace").strip()))
    agora = time.strftime("%F %T")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write("%s == push de %s ==\n" % (agora, cfg.get("apelido", "?")))
        for linha in linhas:
            f.write("%s %s\n" % (agora, linha))
    return 0


def dica(status, resp, cfg):
    if status == 0:
        return "nao conectou: PC desligado, fora da rede ou firewall dele fechado"
    if status == 200:
        try:
            dados = json.loads(resp)
        except ValueError:
            dados = {}
        if dados.get("mudo"):
            return "esta no mudo"
        return "tocou (%s)" % dados.get("player", "?")
    erro = erro_de(resp)
    if status == 403 and erro == "sala diferente":
        return "codigo da sala diferente do seu"
    if status == 403:
        return "%s: confira a data/hora dos dois PCs" % erro
    if status == 409:
        return "aviso duplicado, ignorado"
    if status == 502:
        return ("nao conseguiu baixar seu som: o servico deste PC esta rodando? "
                "a porta %s/tcp esta liberada aqui?" % cfg["porta"])
    if status == 500:
        return "o PC dele nao conseguiu tocar: falta ffmpeg la, ou use um .wav"
    return "HTTP %s: %s" % (status, erro)


def cmd_testar(args):
    cfg = carregar_config()
    if not configurado(cfg):
        print("Ainda nao configurado. Rode: commit-sounds configurar")
        return 1
    if args.aqui:
        som = meu_som(cfg)
        if not som:
            print("Voce ainda nao escolheu um som. Rode: commit-sounds som /caminho/som.mp3")
            return 1
        player = play_sound(som[0])
        if player:
            print("Tocando %s neste PC com %s. Se nao ouviu, confira volume/saida de audio." % (som[0].name, player))
            return 0
        print("Nenhum player conseguiu tocar aqui (instalados: %s)." % (", ".join(players_instalados()) or "nenhum"))
        print("Instale o ffmpeg (sudo apt install ffmpeg) ou use um som .wav.")
        return 1
    resultados = enviar_avisos(cfg)
    if resultados is None:
        print("Voce ainda nao escolheu um som. Rode: commit-sounds som /caminho/som.mp3")
        return 1
    if not resultados:
        print("Nenhum amigo encontrado na sala ainda.")
        print("  - eles instalaram e usaram o mesmo codigo de sala (%s)?" % cfg["sala"])
        print("  - se a rede bloquear a descoberta: commit-sounds adicionar IP_DO_AMIGO")
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
        print("Ainda nao configurado. Rode: commit-sounds configurar")
        return 1
    som = meu_som(cfg)
    local, _, _ = http("http://127.0.0.1:%s/quem" % cfg["porta"], cabecalhos=cabecalho_sala(cfg, "quem"), timeout=2)
    players = players_instalados()
    print("Voce:     %s" % cfg["apelido"])
    print("Sala:     %s" % cfg["sala"])
    print("Seu som:  %s" % (som[0].name if som else "NENHUM -> commit-sounds som /caminho/som.mp3"))
    print("Servico:  %s" % ("rodando" if local == 200 else "PARADO -> systemctl --user restart commit-sounds"))
    audio = ", ".join(players) if players else "NENHUM player -> sudo apt install ffmpeg"
    if players and "ffplay" not in players:
        audio += " (sem ffmpeg: mp3 dos amigos pode nao tocar)"
    print("Audio:    %s" % audio)
    if cfg.get("mudo_ate", 0) > time.time():
        print("Mudo:     ate %s" % time.strftime("%H:%M", time.localtime(cfg["mudo_ate"])))

    amigos = list(listar_amigos(cfg).values())
    print("")
    if not amigos:
        print("Nenhum amigo na sala ainda.")
        print("  Convide: mande o codigo '%s' e peca pra rodarem bash instalar.sh" % cfg["sala"])
        print("  Rede bloqueia descoberta? commit-sounds adicionar IP_DO_AMIGO")
        return 0

    def checar(a):
        status, _, resp = http(url_amigo(a, "/quem"), cabecalhos=cabecalho_sala(cfg, "quem"), timeout=2)
        return a, status, resp

    with ThreadPoolExecutor(max_workers=min(16, len(amigos))) as ex:
        resultados = list(ex.map(checar, amigos))
    print("Amigos:")
    for a, status, resp in sorted(resultados, key=lambda r: r[0]["apelido"].lower()):
        if status == 200:
            estado = "online"
        elif status == 0:
            estado = "offline (visto %s)" % tempo_atras(a.get("visto", 0))
        else:
            estado = "erro: %s" % dica(status, resp, cfg)
        print("  %-12s %-21s %s" % (a["apelido"], "%s:%s" % (a["ip"], a["porta"]), estado))
    return 0


def tempo_atras(ts):
    seg = int(time.time() - ts)
    if seg < 120:
        return "agora"
    if seg < 7200:
        return "ha %d min" % (seg // 60)
    if seg < 172800:
        return "ha %d h" % (seg // 3600)
    return "ha %d dias" % (seg // 86400)


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
        apelido = perguntar("Seu apelido (letras, numeros, _ . -)", apelido or None)
        while not valid_apelido(apelido):
            print("  apelido invalido")
            apelido = perguntar("Seu apelido (letras, numeros, _ . -)")
    if not valid_apelido(apelido):
        print("apelido invalido: %r" % apelido)
        return 1

    sala = args.sala or cfg.get("sala", "")
    if interativo:
        if sala:
            sala = perguntar("Codigo da sala", sala)
        else:
            sala = perguntar("Codigo da sala (Enter para criar uma nova)")
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
            texto = "Caminho do seu som (mp3, wav, ogg...)"
            caminho = perguntar(texto + (" [Enter mantem o atual]" if atual else ""))
            if not caminho and atual:
                break
            if not caminho:
                print("  precisa de um som; ex: ~/Downloads/risada.mp3")
                continue
            falha = definir_som(cfg, caminho)
            if not falha:
                break
            print("  " + falha)
    gravar_json(CONFIG_PATH, cfg)
    if sala_nova:
        atualizar_amigos(lambda amigos: amigos.clear())

    print("")
    print("Configurado: %s na sala '%s'." % (apelido, sala))
    print("Para chamar amigos, mande esse codigo de sala pra eles.")
    return 0


def cmd_som(args):
    cfg = carregar_config()
    falha = definir_som(cfg, args.arquivo)
    if falha:
        print(falha)
        return 1
    gravar_json(CONFIG_PATH, cfg)
    print("Som trocado para %s. Os amigos recebem o novo no seu proximo push." % Path(args.arquivo).name)
    return 0


def cmd_sala(args):
    cfg = carregar_config()
    if not configurado(cfg):
        print("Ainda nao configurado. Rode: commit-sounds configurar")
        return 1
    print(cfg["sala"])
    if sys.stdout.isatty():
        print("")
        print("Para alguem entrar: clonar o commit-sounds, rodar 'bash instalar.sh' e usar esse codigo.")
    return 0


def cmd_adicionar(args):
    cfg = carregar_config()
    if not configurado(cfg):
        print("Ainda nao configurado. Rode: commit-sounds configurar")
        return 1
    host, _, porta = args.endereco.replace("http://", "").rstrip("/").partition(":")
    porta = int(porta) if porta.isdigit() else 8080
    if not HOST_RE.fullmatch(host) or not valid_porta(porta):
        print("endereco invalido: %s (ex: 192.168.0.15 ou 192.168.0.15:8080)" % args.endereco)
        return 1
    status, _, resp = http("http://%s:%s/quem" % (host, porta), cabecalhos=cabecalho_sala(cfg, "quem"))
    if status != 200:
        print("Nao consegui falar com %s:%s -> %s" % (host, porta, dica(status, resp, cfg)))
        return 1
    try:
        dados = abrir(cfg, json.loads(resp))
    except (ValueError, Recusado) as e:
        print("Resposta estranha de %s:%s (%s)" % (host, porta, e))
        return 1
    if dados["id"] == cfg["id"]:
        print("Esse endereco e o seu proprio PC.")
        return 1
    registrar(dados, host, manual=True)
    print("Adicionado: %s (%s:%s)" % (dados["apelido"], host, porta))
    return 0


def cmd_remover(args):
    cfg = carregar_config()

    def fn(amigos):
        alvos = [k for k, a in amigos.items() if isinstance(a, dict) and a.get("apelido", "").lower() == args.apelido.lower()]
        for k in alvos:
            del amigos[k]
        return len(alvos)

    if atualizar_amigos(fn):
        print("Removido: %s (se ele continuar na sala, volta a aparecer sozinho)" % args.apelido)
        return 0
    print("Nao conheco nenhum amigo chamado %s" % args.apelido)
    return 1


def cmd_mudo(args):
    cfg = carregar_config()
    texto = (args.minutos or "60").lower()
    if texto in ("0", "off", "nao", "desligar"):
        cfg.pop("mudo_ate", None)
        gravar_json(CONFIG_PATH, cfg)
        print("Mudo desligado.")
        return 0
    if not texto.isdigit():
        print("uso: commit-sounds mudo [minutos | off]")
        return 1
    cfg["mudo_ate"] = int(time.time()) + int(texto) * 60
    gravar_json(CONFIG_PATH, cfg)
    print("Mudo ate %s. Para desligar antes: commit-sounds mudo off" % time.strftime("%H:%M", time.localtime(cfg["mudo_ate"])))
    return 0


def main():
    parser = argparse.ArgumentParser(prog="commit-sounds", description="toca o som dos amigos quando eles dao git push")
    sub = parser.add_subparsers(dest="comando")

    sub.add_parser("status", help="mostra sua config e quais amigos estao online")
    p = sub.add_parser("testar", help="toca seu som nos amigos agora")
    p.add_argument("--aqui", action="store_true", help="toca seu som neste PC, para testar o audio")
    p = sub.add_parser("som", help="troca o seu som")
    p.add_argument("arquivo")
    sub.add_parser("sala", help="mostra o codigo da sala para convidar alguem")
    p = sub.add_parser("adicionar", help="adiciona um amigo pelo IP, se a descoberta automatica falhar")
    p.add_argument("endereco", help="IP ou IP:porta")
    p = sub.add_parser("remover", help="esquece um amigo")
    p.add_argument("apelido")
    p = sub.add_parser("mudo", help="silencia os sons por um tempo")
    p.add_argument("minutos", nargs="?", help="minutos (padrao 60) ou off")
    p = sub.add_parser("configurar", help="define apelido, sala e som")
    p.add_argument("--apelido")
    p.add_argument("--sala")
    p.add_argument("--som")
    sub.add_parser("servir", help="roda o servico (usado pelo systemd)")
    sub.add_parser("avisar", help="avisa os amigos de um push (usado pelo hook)")

    args = parser.parse_args()
    comandos = {
        "status": cmd_status,
        "testar": cmd_testar,
        "som": cmd_som,
        "sala": cmd_sala,
        "adicionar": cmd_adicionar,
        "remover": cmd_remover,
        "mudo": cmd_mudo,
        "configurar": cmd_configurar,
        "servir": cmd_servir,
        "avisar": cmd_avisar,
    }
    return comandos.get(args.comando or "status")(args)


if __name__ == "__main__":
    sys.exit(main())
