#!/usr/bin/env python3
import argparse
import atexit
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from . import perfil, tunel_bin
from .handler import Handler, build_server

HERE = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".config" / "erp-fakes"
STATE_FILE = STATE_DIR / "state.json"
OLD_STATE_DIR = Path.home() / ".config" / "feegow-fake"


def migrate_state():
    """Copia estado e ids da pasta antiga (feegow-fake) para que chaves e ids permanentes continuem valendo."""
    if STATE_FILE.exists() or not OLD_STATE_DIR.exists():
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for arq in OLD_STATE_DIR.glob("*.json"):
        shutil.copy2(arq, STATE_DIR / arq.name)

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

tunnel = {"status": "desligado", "url": None, "since": None, "history": [], "error": None}
state = {"token": None, "tokens": {}, "ack_url": None}
lock = threading.Lock()


def load_state():
    try:
        state.update(json.loads(STATE_FILE.read_text()))
    except (OSError, ValueError):
        pass


def save_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({**state, "history": tunnel["history"][-20:]}))
    STATE_FILE.chmod(0o600)


def host_of(url):
    return urlparse(url).netloc if url else None


class Tunnel(threading.Thread):
    def __init__(self, binary, port):
        super().__init__(daemon=True)
        self.binary, self.port, self.proc, self.stop = binary, port, None, False

    def run(self):
        while not self.stop:
            with lock:
                tunnel.update(status="iniciando", error=None)
            try:
                self.proc = subprocess.Popen(
                    [self.binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in self.proc.stdout:
                    m = URL_RE.search(line)
                    with lock:
                        if m and m.group(0) != tunnel["url"]:
                            tunnel.update(url=m.group(0), since=time.time())
                            tunnel["history"].append({"url": m.group(0), "since": time.time()})
                            save_state()
                        if "Registered tunnel connection" in line:
                            tunnel["status"] = "conectado"
            except OSError as e:
                with lock:
                    tunnel.update(status="erro", error=str(e))
            with lock:
                if not self.stop:
                    tunnel.update(status="caiu", url=tunnel["url"])
            time.sleep(4)

    def close(self):
        self.stop = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def probe_loop():
    fails = 0
    while True:
        time.sleep(20)
        url = tunnel["url"]
        if not url or tunnel["status"] not in ("conectado", "sem resposta"):
            continue
        try:
            urllib.request.urlopen(url + "/health", timeout=8)
            fails = 0
            with lock:
                tunnel["status"] = "conectado"
        except Exception:
            fails += 1
            if fails >= 2:
                with lock:
                    tunnel["status"] = "sem resposta"


def carga_em_andamento(journal, agora=None):
    """[[O_cliente]] costuma levar de 1 a 2 minutos na carga, com pausas de até 10 s entre unidades."""
    agora = agora or time.time()
    via_tunel = [e for e in journal if e["tunel"]]
    recentes = [e for e in via_tunel if agora - e["t"] < 120]
    return bool(via_tunel) and agora - via_tunel[-1]["t"] < 25 and len(recentes) >= 6


def alerts(journal):
    out = []
    now = time.time()
    url = tunnel["url"]
    host = host_of(url)
    via_tunel = [e for e in journal if e["tunel"]]
    on_current = [e for e in via_tunel if e["host"] == host]
    if tunnel["status"] in ("desligado",):
        out.append(("info", "Túnel desligado", "Iniciado com --no-tunnel. [[O_cliente]] só alcança o fake se houver um endereço público."))
    elif tunnel["status"] in ("iniciando",):
        out.append(("info", "Túnel iniciando", "Aguarde alguns segundos até o endereço aparecer."))
    elif tunnel["status"] in ("caiu", "erro", "sem resposta"):
        detail = tunnel["error"] or "A conexão caiu ou o endereço não responde. O programa tenta reconectar sozinho, e o endereço pode mudar."
        out.append(("erro", "Túnel fora do ar", detail))
    if url and on_current:
        state["ack_url"] = url
    if url and state["ack_url"] != url and tunnel["status"] == "conectado":
        out.append(("alerta", "URL desatualizada na conta",
                    "O endereço público mudou. Copie a URL nova na tela Início e cole em [[caminho_conta]] no campo de URL do ERP."))
    bad = [e for e in via_tunel if e["status"] in (401, 403) and now - e["t"] < 900]
    if bad and via_tunel[-1]["status"] in (401, 403):
        out.append(("alerta", "Token diferente na conta",
                    f"{len(bad)} chamadas recusadas por chave inválida nos últimos 15 minutos. Copie a chave na tela Início e cole no campo de chave ou token da integração da conta."))
    falhas = [e for e in via_tunel if e["falha"] and now - e["t"] < 300]
    if falhas:
        out.append(("info", "Falha simulada ativa", f"{len(falhas)} chamadas [[do_cliente]] receberam falha simulada nos últimos 5 minutos. Veja a tela Falhas."))
    if url and state["ack_url"] == url and on_current and now - on_current[-1]["t"] > 900:
        out.append(("info", "Sem chamadas [[do_cliente]] há mais de 15 minutos",
                    "A conta pode estar com a integração desligada, ou nenhuma carga rodou. [[instrucao_carga]]"))
    if carga_em_andamento(journal, now):
        out.insert(0, ("info", "Carga [[do_cliente]] em andamento",
                       "[[O_cliente]] está puxando dados agora. Espere esse aviso sumir antes de conferir o resultado no banco."))
    if not out:
        out.append(("ok", "Tudo certo", "[[O_cliente]] está chamando o fake pelo endereço atual com o token correto."))
    return [{"nivel": a, "titulo": b, "detalhe": c} for a, b, c in out]


class LHandler(Handler):
    def _is_local(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("localhost", "127.0.0.1", "[::1]") and not self.headers.get("Cf-Ray") \
            and not self.headers.get("Cf-Connecting-Ip")

    def _route(self, metodo):
        caminho = self._caminho
        if caminho in ("/", "/dashboard", "/ui") or caminho.startswith("/_local/"):
            if not self._is_local():
                return self._send({"message": "não encontrado"}, 404)
            return self._local(caminho)
        return super()._route(metodo)

    @staticmethod
    def _contas(url):
        """Campos a preencher na conta do sistema integrado para cada ERP simulado."""
        tk, p = state["tokens"], perfil.ativo()
        rot = {**perfil.GENERICO.campos_conta, **p.campos_conta}
        valores = {"feegow": (url + "/v1/api" if url else None, state["token"]), "netpacs": (url + "/v2" if url else None, tk.get("netpacs")),
                   "tasy": (url if url else None, tk.get("tasy"))}
        avisos = {"netpacs": "A URL precisa terminar em /v2. Se o endereço do túnel tiver a sequência v2, o NetPacs quebra a URL: reinicie o túnel.",
                  "tasy": "A chave tem 32 caracteres ou mais, como o Tasy exige para assinar o JWT.", **p.avisos_conta}
        nomes = {"feegow": "Feegow", "netpacs": "NetPacs", "tasy": "Tasy (agente)"}
        out = {}
        for erp, (u, k) in valores.items():
            out[erp] = {"nome": nomes[erp], "campos": [(rot[erp][0], u), (rot[erp][1], k)]}
            if erp in avisos:
                out[erp]["aviso"] = avisos[erp]
        return out

    def _local(self, caminho):
        if caminho == "/ui":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if caminho in ("/", "/dashboard"):
            raw = perfil.aplicar((HERE / "app.html").read_text(encoding="utf-8")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return self.wfile.write(raw)
        if caminho == "/_local/status":
            with lock:
                t = dict(tunnel)
                journal = list(self.journal)
                al = alerts(journal)
            via_tunel = [e for e in journal if e["tunel"]]
            now = time.time()
            return self._send({
                "token": state["token"], "porta": self.server.server_address[1],
                "erps": self._contas(t["url"]),
                "tunel": {"status": t["status"], "url": t["url"], "desde": t["since"],
                          "url_conta": t["url"] + "/v1/api" if t["url"] else None, "historico": t["history"][-5:]},
                "alertas": al,
                "perfil": {"nome": perfil.ativo().nome, "conferencia": perfil.ativo().consulta is not None,
                           "conta_padrao": perfil.ativo().conta_padrao, "instrucao_banco": perfil.ativo().instrucao_banco,
                           "roteiros": bool(perfil.ativo().roteiros)},
                "cliente": {"em_andamento": carga_em_andamento(journal, now), "ultima_chamada": via_tunel[-1]["t"] if via_tunel else None,
                         "chamadas_5min": sum(1 for e in via_tunel if now - e["t"] < 300)},
                "agora": now})
        if caminho == "/_local/ack":
            state["ack_url"] = tunnel["url"]
            save_state()
            return self._send({"ok": True})
        return self._send({"message": "não encontrado"}, 404)


def main():
    ap = argparse.ArgumentParser(description="ERP Fakes: Feegow, NetPacs e Tasy simulados, com túnel e painel local")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-tunnel", action="store_true")
    ap.add_argument("--existing-tunnel", default=None, metavar="URL",
                    help="usa um túnel já aberto por outro processo (https://....trycloudflare.com) em vez de abrir um novo")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--cloudflared", default=None)
    ap.add_argument("--perfil", default=None, help="perfil do sistema integrado: nome do módulo com PERFIL (ou 'exemplo'); também via ERP_FAKES_PERFIL")
    ap.add_argument("--instalar-tunel", action="store_true", help="baixa o cloudflared para a pasta do programa e sai")
    ap.add_argument("--token", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--patients", type=int, default=600)
    ap.add_argument("--schedules", type=int, default=1500)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--units", type=int, default=3)
    ap.add_argument("--phone", default=os.environ.get("FAKE_PHONE"))
    ap.add_argument("--phone-count", type=int, default=5)
    a = ap.parse_args()

    if a.instalar_tunel:
        try:
            print(f"cloudflared instalado em {tunel_bin.instalar()}")
        except Exception as e:
            raise SystemExit(f"Não consegui instalar o cloudflared: {e}")
        return

    try:
        if a.perfil is not None:
            perfil.ativar(a.perfil)
        else:
            perfil.ativar_do_ambiente()
    except ValueError as e:
        raise SystemExit(str(e))
    migrate_state()
    load_state()
    if a.token:
        state["token"] = a.token
    elif not state["token"]:
        state["token"] = secrets.token_urlsafe(16)
    for nome, tamanho in (("netpacs", 24), ("tasy", 48)):
        if not state["tokens"].get(nome):
            state["tokens"][nome] = secrets.token_urlsafe(tamanho)
    save_state()

    httpd = build_server(a.port, a.host, token=state["token"], tokens=state["tokens"], seed=a.seed, patients=a.patients,
                         schedules=a.schedules, days=a.days, phone=a.phone, phone_count=a.phone_count,
                         units=a.units, base=LHandler, ids_path=STATE_FILE.parent / "ids.json")
    local_url = f"http://localhost:{a.port}/"

    tun = None
    if a.existing_tunnel:
        url = a.existing_tunnel.rstrip("/")
        tunnel.update(status="conectado", url=url, since=time.time())
        tunnel["history"].append({"url": url, "since": time.time()})
        threading.Thread(target=probe_loop, daemon=True).start()
    elif not a.no_tunnel:
        binary = tunel_bin.garantir(a.cloudflared)
        if not binary:
            tunnel.update(status="erro", error="cloudflared não encontrado. Rode erp-fakes --instalar-tunel ou use --no-tunnel.")
        else:
            tun = Tunnel(binary, a.port)
            tun.start()
            threading.Thread(target=probe_loop, daemon=True).start()
            atexit.register(tun.close)

    print(f"Painel local: {local_url}")
    for nome, ctx in httpd.RequestHandlerClass.ctxs.items():
        print(f"{nome}: {len(ctx.model.schedules)} agendamentos, {len(ctx.model.patients)} pacientes")
    print("Ctrl+C para encerrar.")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(local_url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if tun:
            tun.close()


if __name__ == "__main__":
    main()
