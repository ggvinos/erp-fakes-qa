import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from . import perfil
from .handler import build_server


class FakeErpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status, self.body = status, body


def gera_jwt(segredo, validade=3600):
    """JWT HS256 como o cliente envia ao agente Tasy."""
    def b64(x):
        return base64.urlsafe_b64encode(x).rstrip(b"=").decode()
    n = len(segredo.encode())
    alg, h = ("HS512", hashlib.sha512) if n >= 64 else ("HS384", hashlib.sha384) if n >= 48 else ("HS256", hashlib.sha256)
    cab = b64(json.dumps({"alg": alg}).encode())
    corpo = b64(json.dumps({"iss": perfil.ativo().emissor_jwt or "cliente", "exp": int(time.time()) + validade}).encode())
    ass = hmac.new(segredo.encode(), f"{cab}.{corpo}".encode(), h).digest()
    return f"{cab}.{corpo}.{b64(ass)}"


class FakeErp:
    """Sobe o ERP fake (Feegow por padrão, ou netpacs e tasy) em uma porta livre, dentro do processo, para testes."""

    def __init__(self, *, token="test-token", seed=42, patients=200, schedules=600, days=14, units=3, erp="feegow"):
        self.erp = erp
        self.token = token if erp != "tasy" or len(token) >= 32 else "t" * 40
        self._kw = dict(seed=seed, patients=patients, schedules=schedules, days=days, units=units)
        self.httpd = None
        self._thread = None

    def start(self):
        tokens = {} if self.erp == "feegow" else {self.erp: self.token}
        self.httpd = build_server(0, "127.0.0.1", token=self.token if self.erp == "feegow" else "test-token",
                                  tokens=tokens, **self._kw)
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self._thread.join(timeout=5)
            self.httpd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    @property
    def url(self):
        """Valor para o campo Feegow url da integração."""
        return self.base_url + "/v1/api"

    @property
    def model(self):
        return self.httpd.RequestHandlerClass.ctxs[self.erp].model

    def request(self, method, path, body=None, *, token="default", timeout=10):
        tok = self.token if token == "default" else token
        admin = path.startswith("/_admin") or path.startswith("/health")
        headers = {"Content-Type": "application/json"}
        if admin:
            headers["x-erp"] = self.erp
            if tok:
                headers["x-access-token"] = tok
        elif tok:
            if self.erp == "feegow":
                headers["x-access-token"] = tok
            elif self.erp == "netpacs":
                headers["Authorization"] = tok
            else:
                headers["Authorization"] = "Basic " + (gera_jwt(tok) if token == "default" else tok)
        if isinstance(body, str):
            data = body.encode()
        else:
            data = json.dumps(body).encode() if body is not None else None
        root = self.base_url if admin or self.erp != "feegow" else self.url
        req = urllib.request.Request(root + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, self._corpo(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            e.close()
            return e.code, self._corpo(raw)

    @staticmethod
    def _corpo(raw):
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode(errors="replace")

    def get(self, path, **params):
        suffix = ("?" + urlencode(params)) if params else ""
        status, body = self.request("GET", path + suffix)
        if status >= 400:
            raise FakeErpError(status, body)
        return body

    def patch(self, path, body=None, **params):
        status, resp = self.request("PATCH", path + (("?" + urlencode(params)) if params else ""), body or {})
        if status >= 400:
            raise FakeErpError(status, resp)
        return resp

    def delete(self, path, **params):
        status, resp = self.request("DELETE", path + (("?" + urlencode(params)) if params else ""))
        if status >= 400:
            raise FakeErpError(status, resp)
        return resp

    def post(self, path, body=None, **params):
        suffix = ("?" + urlencode(params)) if params else ""
        status, body = self.request("POST", path + suffix, {} if body is None else body)
        if status >= 400:
            raise FakeErpError(status, body)
        return body

    def schedules(self, scenario=None, **filters):
        """Agendamentos como o Feegow os devolve. Filtros por igualdade, ex: unidade_id=101."""
        out = [self.model.schedule_json(s, True) for s in self.model.schedules.values()]
        if scenario:
            out = [s for s in out if s["obs"] == f"cenario={scenario}"]
        return [s for s in out if all(s.get(k) == v for k, v in filters.items())]

    def update_schedule(self, schedule_id, **fields):
        return self.post(f"/_admin/schedule/{schedule_id}", fields)

    def sync_insurance(self, insurance_id):
        return self.post("/_admin/insurance/sync", {"convenio_id": insurance_id})

    def reset(self):
        return self.post("/_admin/reset")

    def calls(self):
        return self.get("/_admin/log")

    def fault(self, route, kind, value=None, times=None):
        """Ativa uma falha simulada. kind: atraso, status, vazio, quebrado, derrubar, timeout."""
        return self.post("/_admin/faults", {"rota": route, "tipo": kind, "valor": value, "vezes": times})

    def clear_faults(self):
        return self.post("/_admin/faults/limpar")

    def journal(self, **filters):
        """Diário de chamadas, da mais recente para a mais antiga. Filtros: caminho, so_erros=1, limite."""
        return self.get("/_admin/journal", **filters)["itens"]

    def action(self, schedule_id, name, **params):
        """Ação da clínica no ERP: confirmar, cancelar, remarcar, trocar_convenio, sumir, e outras."""
        return self.post(f"/_admin/schedule/{schedule_id}/acao", {"acao": name, **params})

    def forget_used_targets(self):
        """Esquece os agendamentos que roteiros já usaram (use quando a conta de teste [[do_cliente]] for limpa)."""
        return self.post("/_admin/roteiros/limpar-usados")

    def run_script(self, script_id, account=None):
        """Executa um roteiro: muda o ERP e devolve ids_externos, consulta para o banco e verificacoes."""
        return self.post(f"/_admin/roteiros/{script_id}/executar", {"conta": account} if account is not None else {})

    def evaluate(self, checks, rows, before=None):
        """Compara o resultado do banco [[do_cliente]] (lista de dicts) com as verificações de um roteiro."""
        return self.post("/_admin/roteiros/avaliar", {"verificacoes": checks, "linhas": rows, "antes": before})["resultados"]

    def edit(self, kind, ident, **fields):
        """Edita uma entidade do ERP (profissionais, convenios, pacientes, procedimentos...)."""
        return self.post(f"/_admin/entities/{kind}/{ident}", fields)

    def scenarios(self):
        return self.get("/_admin/scenarios")


FakeFeegow = FakeErp
FakeFeegowError = FakeErpError
