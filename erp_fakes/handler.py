import itertools
import json
import re
import socket
import threading
import time
from collections import Counter, deque
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import dados, erp_netpacs, erp_tasy, ops, perfil, roteiros
from .catalog import DIFERENCAS, DOC_URL, ENDPOINTS, NAO_IMPLEMENTADAS
from .describe import describe_model
from .erp_netpacs import NetpacsMixin
from .erp_tasy import TasyMixin
from .faults import PRESETS, PRESETS_POR_ERP, TIPOS, FaultEngine
from .idstore import IdStore
from .model import PROC_TYPES, STATUSES, Conflito, Model, br, sdate

MAX_TEXTO = 6000
SEM_DIARIO = ("/_admin", "/_local")
SEM_DIARIO_EXATO = ("/", "/health", "/ui", "/dashboard", "/favicon.ico")

ROUTES = {
    ("GET", "/company/list-unity"): "_unidades",
    ("GET", "/company/list-local"): "_locais",
    ("GET", "/insurance/list"): "_convenios",
    ("GET", "/specialties/list"): "_especialidades",
    ("GET", "/patient/list-privates"): "_tabelas",
    ("GET", "/patient/search"): "_paciente_buscar",
    ("GET", "/patient/list"): "_paciente_listar",
    ("POST", "/patient/create"): "_paciente_criar",
    ("POST", "/patient/edit"): "_paciente_editar",
    ("GET", "/procedures/types"): "_tipos",
    ("GET", "/procedures/list"): "_procedimentos",
    ("GET", "/procedures/insurance-procedures-list"): "_procedimento_convenios",
    ("GET", "/professional/list"): "_prof_listar",
    ("GET", "/professional/search"): "_prof_buscar",
    ("GET", "/professional/insurance"): "_prof_convenios",
    ("GET", "/appoints/status"): "_status",
    ("GET", "/appoints/motives"): "_motivos",
    ("GET", "/appoints/list-channel"): "_canais",
    ("POST", "/appoints/statusUpdate"): "_status_atualizar",
    ("POST", "/appoints/confirm"): "_confirmar",
    ("GET", "/appoints/search"): "_agendamentos",
    ("GET", "/appoints/available-schedule"): "_horarios",
    ("POST", "/appoints/new-appoint"): "_agendar",
    ("POST", "/appoints/cancel-appoint"): "_cancelar",
    ("POST", "/appoints/reschedule"): "_remarcar",
    ("GET", "/lock/list"): "_bloqueios",
    ("GET", "/financial2/external/private-table/list"): "_planos_particular",
}


def _int(valor, padrao=None):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _data(texto):
    for f in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(texto).split(" ")[0], f).date()
        except ValueError:
            pass
    raise ValueError(f"data inválida: {texto}")


def _dd_mm_aaaa(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return iso


def _cortar(texto):
    return texto if len(texto) <= MAX_TEXTO else texto[:MAX_TEXTO] + f"... (+{len(texto) - MAX_TEXTO} caracteres)"


ERPS = ("feegow", "netpacs", "tasy")
MARCAS = {"feegow": ("Fake", 101, 0), "netpacs": ("NetPacs", 301, 1), "tasy": ("Tasy", 501, 2)}


def dialeto_do_caminho(c):
    if c.startswith(("/netris/", "/netpacs/")):
        return "netpacs"
    if c.lstrip("/").split("/")[0] in erp_tasy.PRIMEIROS:
        return "tasy"
    return "feegow"


class Ctx:
    """Dados de um ERP simulado: modelo, ids permanentes e chave de acesso."""

    def __init__(self, nome, args, ids, token):
        self.nome, self.args, self.ids, self.token = nome, args, ids, token
        self.faults = FaultEngine()
        self.extra = {}
        self.model = self.novo_model()

    def novo_model(self):
        marca, base, _ = MARCAS[self.nome]
        return Model(*self.args, ids=self.ids, marca=marca, unit_base=base, **self.extra)


class Handler(NetpacsMixin, TasyMixin, BaseHTTPRequestHandler):
    ctxs = None
    ctx = None
    erp = "feegow"
    journal = None
    lock = None
    seq = None
    config = None
    ids = None

    def log_message(self, *a):
        pass

    @property
    def model(self):
        return self.ctx.model

    @property
    def faults(self):
        return self.ctx.faults

    @property
    def ids(self):
        return self.ctx.ids

    @property
    def token(self):
        return self.ctx.token

    @property
    def model_args(self):
        return self.ctx.args

    # ----- respostas -----
    def _send_text(self, texto, code=200, ctype="application/json; charset=utf-8"):
        self._resp = (code, texto)
        raw = perfil.aplicar(texto).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send(self, body, code=200):
        self._send_text(json.dumps(body, ensure_ascii=False, default=str), code)

    def _ok(self, content, **extra):
        self._send({"success": True, "content": content, **extra})

    def _erro(self, code, content):
        self._send({"success": False, "content": content}, code)

    # ----- ciclo da requisição -----
    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, metodo):
        self._t0 = time.perf_counter()
        self._resp, self._falha, self._corpo = None, None, None
        url = urlparse(self.path)
        self._caminho = re.sub(r"^(/v\d+(\.\d+)?)?(/api)?", "", url.path).rstrip("/") or "/"
        self._query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.erp = self._resolver_erp()
        self.ctx = self.ctxs[self.erp]
        try:
            self._route(metodo)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._erro(500, f"erro interno do fake: {e!r}")
            except Exception:
                pass
        finally:
            self._registrar(metodo)

    def _resolver_erp(self):
        c = self._caminho
        if c.startswith("/_admin"):
            erp = self.headers.get("x-erp") or self._query.get("erp") or "feegow"
            return erp if erp in self.ctxs else "feegow"
        return dialeto_do_caminho(c)

    def _registrar(self, metodo):
        c = self._caminho
        if c.startswith(SEM_DIARIO) or c in SEM_DIARIO_EXATO:
            return
        code, texto = self._resp or (0, "(sem resposta: conexão derrubada)")
        entrada = {
            "id": next(self.seq), "t": time.time(), "metodo": metodo, "caminho": c, "query": self._query,
            "corpo": _cortar(json.dumps(self._corpo, ensure_ascii=False, default=str)) if self._corpo else None,
            "status": code, "resposta": _cortar(texto), "ms": int((time.perf_counter() - self._t0) * 1000),
            "erp": self.erp, "tunel": bool(self.headers.get("Cf-Ray") or self.headers.get("Cf-Connecting-Ip")),
            "host": self.headers.get("Host"), "falha": self._falha}
        with self.lock:
            self.journal.append(entrada)

    def _route(self, metodo):
        c, q = self._caminho, self._query
        if c == "/health":
            return self._send({"ok": True})
        if c == "/favicon.ico":
            self._resp = (204, "")
            self.send_response(204)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        n = int(self.headers.get("Content-Length") or 0)
        bruto = self.rfile.read(n) if n else b""
        corpo = {}
        if bruto:
            try:
                corpo = json.loads(bruto)
            except ValueError:
                self._corpo = bruto[:300].decode(errors="replace")
                if self.erp == "feegow" or c.startswith("/_admin"):
                    return self._erro(422, "O corpo da requisição não é um JSON válido")
                corpo = bruto.decode(errors="replace")
        self._corpo = corpo
        if c.startswith("/_admin"):
            if self._auth_admin():
                return
            return self._admin(metodo, c, q, corpo)
        if getattr(self, f"_auth_{self.erp}")():
            return
        falha = self.faults.pick(metodo, c)
        if falha and self._aplicar_falha(falha):
            return
        if self.erp == "feegow":
            nome = ROUTES.get((metodo, c))
            grupos = ()
        else:
            nome, grupos = None, ()
            for m_, rx, n_ in (erp_netpacs.ROTAS if self.erp == "netpacs" else erp_tasy.ROTAS):
                achou = rx.fullmatch(c) if m_ == metodo else None
                if achou:
                    nome, grupos = n_, achou.groups()
                    break
        if not nome:
            return self._erro(404, f"fake: rota não implementada {metodo} {c}")
        getattr(self, nome)(q, corpo, *grupos)

    def _auth_feegow(self):
        if self.token:
            chave = self.headers.get("x-access-token")
            if not chave:
                self._erro(401, "Chave de acesso ausente")
                return True
            if chave != self.token:
                self._erro(403, "Chave de acesso inativa")
                return True
        return False

    def _auth_admin(self):
        tokens = {c.token for c in self.ctxs.values() if c.token}
        if not tokens:
            return False
        chave = self.headers.get("x-access-token")
        if not chave:
            self._erro(401, "Chave de acesso ausente")
            return True
        if chave not in tokens:
            self._erro(403, "Chave de acesso inativa")
            return True
        return False

    def _aplicar_falha(self, f):
        self._falha = f"{f['tipo']}" + (f" {f['valor']}" if f["valor"] is not None else "")
        if f["tipo"] == "atraso":
            time.sleep(f["valor"] / 1000)
        elif f["tipo"] == "timeout":
            time.sleep(f["valor"])
        elif f["tipo"] == "status":
            self._erro(f["valor"], "Falha simulada pelo fake")
            return True
        elif f["tipo"] == "vazio":
            self._send({} if self.erp == "feegow" else [])
            return True
        elif f["tipo"] == "quebrado":
            self._send_text("<html><body>Erro interno do servidor</body></html>", 200, "text/html; charset=utf-8")
            return True
        elif f["tipo"] == "derrubar":
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return True
        return False

    # ----- leitura -----
    def _unidades(self, q, b):
        u = self.model.units
        self._ok({"matriz": u[:1], "unidades": u[1:]})

    def _locais(self, q, b):
        self._ok([{"id": u["unidade_id"], "local": f"Consultório {i + 1}", "unidade_id": u["unidade_id"]}
                  for i, u in enumerate(self.model.units)])

    def _convenios(self, q, b):
        self._ok([{"convenio_id": i["convenio_id"], "nome": i["nome"], "registro_ans": i["registro_ans"],
                   "planos": i["planos"]} for i in self.model.insurances])

    def _especialidades(self, q, b):
        self._ok(self.model.specialties, total=len(self.model.specialties))

    def _tabelas(self, q, b):
        t = [{k: v for k, v in x.items() if k != "mult"} for x in self.model.tables]
        self._ok(t, total=len(t))

    def _tipos(self, q, b):
        self._ok([{"id": i, "tipo": n} for i, n in PROC_TYPES.items()])

    def _item_procedimento(self, p, valor=None):
        espec = [str(e["especialidade_id"]) for e in self.model.specialties[:2]]
        return {"procedimento_id": p["procedimento_id"], "nome": p["nome"], "tipo_procedimento": p["tipo_procedimento"],
                "opcoes_agendamento": 1, "permite_agendamento_online": True, "preparo": p["preparo"],
                "dias_retorno": None, "codigo": str(p["procedimento_id"]), "grupo_procedimento": 0, "tempo": "00:20:00",
                "valor": p["base"] if valor is None else valor, "especialidade_id": espec}

    def _procedimentos(self, q, b):
        m = self.model
        pid = q.get("procedimento_id")
        if pid:
            proc = next((p for p in m.procedures if str(p["procedimento_id"]) == pid), None)
            tab = next((t for t in m.tables if str(t["tabela_id"]) == q.get("tabela_id", "1")), None)
            if not proc or not tab or (tab["tabela_id"] == 2 and proc["procedimento_id"] in m.no_price_table2):
                return self._ok([])
            item = self._item_procedimento(proc, int(proc["base"] * tab["mult"]))
            item["tabela_id"] = tab["tabela_id"]
            return self._ok([item])
        procs = [p for p in m.procedures if not q.get("tipo_procedimento") or str(p["tipo_procedimento"]) == q["tipo_procedimento"]]
        if q.get("nome_procedimento"):
            procs = [p for p in procs if q["nome_procedimento"].lower() in p["nome"].lower()]
        self._ok([self._item_procedimento(p) for p in procs])

    def _procedimento_convenios(self, q, b):
        m = self.model
        pid, nome = q.get("procedimentoID"), q.get("nomeProcedimento")
        if not pid and not nome:
            return self._erro(400, "O Id ou nome do procedimento devem ser informados")
        procs = [p for p in m.procedures if (pid and str(p["procedimento_id"]) == pid)
                 or (nome and nome.lower() in p["nome"].lower())]
        if not procs:
            return self._erro(400, "Não foi encontrado nenhum procedimento")
        ids = ",".join(str(i["convenio_id"]) for i in m.insurances)
        nomes = ", ".join(i["nome"] for i in m.insurances)
        self._ok([{"procedimento_id": str(p["procedimento_id"]), "nome_procedimento": p["nome"], "Convenios": ids,
                   "Nao_aceita_particular": 0, "Nao_aceita_convenio": 0, "Convenios_nome": nomes} for p in procs])

    def _prof_listar(self, q, b):
        if q.get("ativo") not in ("0", "1"):
            return self._send({"ativo": ["validation.required"]}, 422)
        quer = q["ativo"] == "1"
        out = []
        for p in self.model.professionals:
            if p["ativo"] != quer:
                continue
            if q.get("unidade_id") and _int(q["unidade_id"]) not in p["unidades"]:
                continue
            if q.get("especialidade_id") and not any(str(e["especialidade_id"]) == q["especialidade_id"] for e in p["especialidades"]):
                continue
            out.append({"profissional_id": p["profissional_id"], "sys_user": p["profissional_id"] + 9000, "nome": p["nome"],
                        "tratamento": None, "rqe": None, "conselho": "CRM", "documento_conselho": str(p["profissional_id"] * 7),
                        "uf_conselho": "SC", "foto": None, "sexo": p["sexo"], "email": f"prof{p['profissional_id']}@teste.invalid",
                        "cpf": None, "age_restriction": [{"age_from": None, "age_to": None}],
                        "especialidades": [{"especialidade_id": e["especialidade_id"], "nome_especialidade": e["nome"], "CBOS": ""}
                                           for e in p["especialidades"]]})
        self._ok(out)

    def _prof(self, q):
        return next((x for x in self.model.professionals if str(x["profissional_id"]) == q.get("profissional_id")), None)

    def _prof_buscar(self, q, b):
        p = self._prof(q)
        if not p:
            return self._erro(409, "Profissional não encontrado.")
        info = {"rqe": None, "conselho": "CRM", "documento_conselho": str(p["profissional_id"] * 7), "uf_conselho": "SC",
                "CPF": None, "nome": p["nome"], "foto": None, "data_nascimento": "1980-01-01", "sexo": p["sexo"],
                "telefones": [], "celulares": [], "email": f"prof{p['profissional_id']}@teste.invalid", "idade_minima": None,
                "rua": None, "numero_rua": None, "complemento": None, "cidade": "Florianópolis", "bairro": None, "CEP": None}
        esp = [{"especialidade_id": e["especialidade_id"], "nome_especialidade": e["nome"], "CBOS": "", "rqe": None,
                "conselho": "CRM", "documento_conselho": info["documento_conselho"], "uf_conselho": "SC"} for e in p["especialidades"]]
        self._ok({"informacoes": [info], "especialidades": esp})

    def _prof_convenios(self, q, b):
        p = self._prof(q)
        self._ok([{"convenio_id": i["convenio_id"], "registro_ans": i["registro_ans"], "nome": i["nome"]}
                  for i in (p["convenios"] if p else [])])

    # ----- pacientes -----
    def _paciente_buscar(self, q, b):
        m = self.model
        p = m.patients.get(_int(q.get("paciente_id"), -1))
        if not p and q.get("paciente_cpf"):
            p = next((x for x in m.patients.values() if x["documentos"]["cpf"] == q["paciente_cpf"]), None)
        if not p:
            return self._erro(409, "Paciente não existe")
        self._ok({"nome": p["nome"], "nascimento": _dd_mm_aaaa(p["nascimento"]), "sexo": p["sexo"], "endereco": None,
                  "numero": None, "complemento": None, "bairro": None, "cidade": None, "estado": None, "cep": None,
                  "profissao": None, "foto": None, "telefones": [None], "celulares": [p["celular"]],
                  "documentos": {"rg": None, "cpf": p["documentos"]["cpf"]}, "email": [p["email"]], "convenios": []})

    def _paciente_listar(self, q, b):
        pacs = list(self.model.patients.values())
        if q.get("cpf"):
            pacs = [p for p in pacs if p["documentos"]["cpf"] == re.sub(r"\D", "", q["cpf"])]
        if q.get("telefone"):
            pacs = [p for p in pacs if re.sub(r"\D", "", q["telefone"]) in re.sub(r"\D", "", p["celular"] or "")]
        total, inicio, limite = len(pacs), _int(q.get("offset"), 0), _int(q.get("limit"), 100)
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._ok([{"patient_id": p["paciente_id"], "nome": p["nome"], "nome_social": None, "nascimento": p["nascimento"],
                   "bairro": None, "tabela_id": 1, "sexo_id": 1 if p["sexo"] == "Masculino" else 3, "email": p["email"],
                   "celular": p["celular"], "criado_em": agora, "alterado_em": agora, "programa_de_saude": []}
                  for p in pacs[inicio:inicio + limite]], total=total)

    def _paciente_criar(self, q, b):
        erros = {}
        if not b.get("nome_completo"):
            erros["nome_completo"] = ["validation.required"]
        if not b.get("cpf") and not b.get("sem_cpf"):
            erros["cpf"] = ["validation.required"]
        if erros:
            return self._send(erros, 422)
        cpf = re.sub(r"\D", "", str(b.get("cpf") or ""))
        igual = next((p for p in self.model.patients.values() if cpf and p["documentos"]["cpf"] == cpf
                      and p["nascimento"] == b.get("data_nascimento")), None)
        if igual:
            return self._ok({"paciente_id": igual["paciente_id"]})
        self._ok({"paciente_id": self.model.add_patient(dict(b, cpf=cpf))})

    def _paciente_editar(self, q, b):
        if not b.get("paciente_id"):
            return self._send({"paciente_id": ["validation.required"]}, 422)
        p = self.model.patients.get(_int(b["paciente_id"], -1))
        if not p:
            return self._send({"success": False, "content": "Paciente não atualizado"})
        cpf = re.sub(r"\D", "", str(b.get("cpf") or ""))
        if cpf and p["documentos"]["cpf"] and cpf != p["documentos"]["cpf"]:
            return self._send({"cpf": ["Um CPF já cadastrado não pode ser alterado"]}, 422)
        for chave, destino in (("nome_completo", "nome"), ("email", "email"), ("data_nascimento", "nascimento")):
            if b.get(chave):
                p[destino] = b[chave]
        if b.get("genero"):
            p["sexo"] = "Feminino" if b["genero"] == "F" else "Masculino"
        if b.get("celular") or b.get("telefone"):
            p["celular"] = b.get("celular") or b["telefone"]
            p["celulares"] = [p["celular"]]
        self._ok("Paciente atualizado")

    # ----- agenda -----
    def _status(self, q, b):
        self._ok([{"id": i, "status": n} for i, n in STATUSES])

    def _motivos(self, q, b):
        self._ok([{"id": 1, "motivo": "Solicitado pelo paciente"}, {"id": 2, "motivo": "Solicitado pelo profissional"},
                  {"id": 3, "motivo": "Solicitado pela clínica"}])

    def _canais(self, q, b):
        self._ok([{"id": 1, "canal": "Telefone"}, {"id": 2, "canal": "WhatsApp"}, {"id": 3, "canal": "Site"},
                  {"id": 4, "canal": perfil.ativo().canal}])

    def _agendamento(self, q, b, *chaves):
        for chave in chaves:
            valor = q.get(chave) or b.get(chave)
            if valor:
                return self.model.schedules.get(_int(valor, -1))
        return None

    def _status_atualizar(self, q, b):
        s = self._agendamento(q, b, "AgendamentoID", "agendamento_id")
        if not s:
            return self._erro(409, "Agendamento não existe")
        s["status_id"] = _int(b.get("StatusID") or q.get("StatusID"), s["status_id"])
        self._ok({"msg": "Status atualizado"})

    def _confirmar(self, q, b):
        s = self._agendamento(q, b, "agendamento_id")
        if not s:
            return self._erro(409, "Agendamento não existe")
        s["status_id"] = 7
        self._ok("Agendamento confirmado")

    def _agendamentos(self, q, b):
        m = self.model
        try:
            inicio = _data(q["data_start"]) if q.get("data_start") else date.min
            fim = _data(q["data_end"]) if q.get("data_end") else date.max
        except ValueError as e:
            return self._send({"data_start": [str(e)]}, 422)
        status = {_int(x) for x in re.split(r"[,;]", q.get("status_id") or q.get("status_ids") or "") if x}
        lista_proc = q.get("list_procedures") == "1"
        out = []
        for s in m.schedules.values():
            if not inicio <= sdate(s) <= fim:
                continue
            if q.get("unidade_id") and str(s["unidade_id"]) != q["unidade_id"]:
                continue
            if q.get("local_id") and str(s["unidade_id"]) != q["local_id"]:
                continue
            if q.get("paciente_id") and str(s["paciente_id"]) != q["paciente_id"]:
                continue
            if q.get("agendamento_id") and str(s["agendamento_id"]) != q["agendamento_id"]:
                continue
            if q.get("profissional_id") and str(s["profissional_id"]) != q["profissional_id"]:
                continue
            if q.get("procedimento_id") and str(s["procedimento_id"]) != q["procedimento_id"]:
                continue
            if q.get("especialidade_id") and str(s["especialidade_id"]) != q["especialidade_id"]:
                continue
            if status and s["status_id"] not in status:
                continue
            out.append(m.schedule_json(s, lista_proc))
        out.sort(key=lambda x: (x["data"][6:], x["data"][3:5], x["data"][:2], x["horario"]))
        if lista_proc and self.config["paginacao_real"]:
            ini, qtd = _int(q.get("start"), 0), _int(q.get("offset"), 50)
            out = out[ini:ini + qtd]
        self._ok(out)

    def _horarios(self, q, b):
        m = self.model
        faltando = {k: ["validation.required"] for k in ("tipo", "data_start", "data_end") if not q.get(k)}
        if faltando:
            return self._send(faltando, 422)
        fmt = "%d-%m-%Y"
        try:
            primeiro = max(datetime.strptime(q["data_start"], fmt).date(), date.today())
            ultimo = datetime.strptime(q["data_end"], fmt).date()
        except ValueError as e:
            return self._send({"data_start": [str(e)]}, 422)
        unidade = _int(q.get("unidade_id"))
        if q.get("profissional_id"):
            profs = [p for p in m.professionals if str(p["profissional_id"]) == q["profissional_id"]]
            ultimo = min(ultimo, primeiro + timedelta(days=90))
        else:
            profs = [p for p in m.professionals if unidade in p["unidades"]]
            if q.get("tipo") == "E" and q.get("especialidade_id"):
                profs = [p for p in profs if any(str(e["especialidade_id"]) == q["especialidade_id"] for e in p["especialidades"])]
            ultimo = min(ultimo, primeiro + timedelta(days=10))
        arvore, total = {}, 0
        for p in profs:
            dias = m.free_slots(p, unidade, primeiro, ultimo) if unidade else {}
            if dias:
                arvore[str(p["profissional_id"])] = {"local_id": {str(unidade): dias}}
                total += sum(len(h) for h in dias.values())
        if not total:
            return self._send({"success": True, "total": 0, "content": []})
        self._send({"success": True, "total": total, "content": {"profissional_id": arvore}})

    def _agendar(self, q, b):
        try:
            sid = self.model.add_schedule(b)
        except Conflito as e:
            return self._erro(409, str(e))
        except ValueError as e:
            return self._send({"data": [str(e)]}, 422)
        except (KeyError, StopIteration, TypeError) as e:
            return self._send({str(e).strip("'"): ["validation.required"]} if isinstance(e, KeyError)
                              else {"profissional_id": ["validation.exists"]}, 422)
        self._ok({"agendamento_id": sid, "link": f"https://fake.feegow.local/agenda/{sid}", "eventos": {"total": 1}})

    def _cancelar(self, q, b):
        s = self._agendamento(q, b, "agendamento_id")
        if not s:
            return self._erro(409, "Agendamento não existe")
        s["status_id"] = 11 if _int(q.get("motivo_id") or b.get("motivo_id"), 1) == 1 else 15
        self._ok("Agendamento cancelado")

    def _remarcar(self, q, b):
        s = self._agendamento(q, b, "agendamento_id")
        if not s:
            return self._erro(409, "Agendamento não existe")
        try:
            nova = _data(b["data"])
            hora = str(b["horario"])
            hora = hora if hora.count(":") == 2 else hora + ":00"
        except (KeyError, ValueError) as e:
            return self._send({"data": [f"validation.required ({e})"]}, 422)
        if self.model.slot_taken(s["profissional_id"], nova, hora, s["agendamento_id"]):
            return self._erro(409, "Horário ocupado")
        s["abs_date"], s["horario"], s["status_id"] = nova, hora, 1
        self._ok("Agendamento remarcado")

    def _bloqueios(self, q, b):
        out = self.model.blocks
        if q.get("bloqueio_id"):
            out = [x for x in out if str(x["id"]) == q["bloqueio_id"]]
        if q.get("profissional_id"):
            out = [x for x in out if str(x["professional_id"]) == q["profissional_id"]]
        if q.get("unidade_id"):
            out = [x for x in out if x["units"] is None or q["unidade_id"] in x["units"]]
        self._ok(out)

    def _planos_particular(self, q, b):
        data = [{"id": pl["plano_id"], "name": pl["plano"]} for i in self.model.insurances for pl in i["planos"]]
        pagina, por = _int(q.get("page"), 1), _int(q.get("perPage"), 50)
        self._send({"count": len(data), "data": data[(pagina - 1) * por: pagina * por]})

    # ----- administração -----
    def _admin(self, metodo, c, q, b):
        m = self.model
        if c == "/_admin/scenarios":
            cont = Counter(s["scenario"] for s in m.schedules.values())
            exemplos = {n: [s["agendamento_id"] for s in m.schedules.values() if s["scenario"] == n][:5] for n in cont}
            return self._send({"total": len(m.schedules), "por_cenario": cont, "exemplos": exemplos,
                               "convenios_ocultos": [{"convenio_id": i["convenio_id"], "nome": i["nome"]} for i in m.hidden_insurances]})
        if c == "/_admin/log":
            with self.lock:
                return self._send([f"{datetime.fromtimestamp(e['t']):%H:%M:%S} {e['metodo']} {e['caminho']}" for e in self.journal])
        if c == "/_admin/journal":
            return self._diario(q)
        if c == "/_admin/journal/limpar" and metodo == "POST":
            with self.lock:
                self.journal.clear()
            return self._send({"ok": True})
        if c == "/_admin/reset" and metodo == "POST":
            self.ctx.model = self.ctx.novo_model()
            return self._send({"ok": True})
        if c == "/_admin/model":
            return self._send(describe_model(m, self.erp))
        if c == "/_admin/catalog":
            return self._send(self._catalogo())
        if c == "/_admin/config":
            if metodo == "POST":
                self.config.update({k: v for k, v in b.items() if k in self.config})
            return self._send(self.config)
        if c == "/_admin/faults" and metodo == "GET":
            return self._send({"regras": self.faults.list(), "tipos": TIPOS, "atalhos": PRESETS_POR_ERP.get(self.erp, PRESETS)})
        if c == "/_admin/faults" and metodo == "POST":
            try:
                return self._send(self.faults.add(b.get("rota"), b.get("tipo"), b.get("valor"), b.get("vezes"), b.get("metodo")))
            except ValueError as e:
                return self._send({"erro": str(e)}, 422)
        if c == "/_admin/faults/remover" and metodo == "POST":
            self.faults.remove(b.get("id"))
            return self._send({"ok": True})
        if c == "/_admin/faults/limpar" and metodo == "POST":
            self.faults.clear()
            return self._send({"ok": True})
        try:
            return self._admin_dados(metodo, c, q, b)
        except Conflito as e:
            return self._send({"erro": str(e)}, 409)
        except (ValueError, KeyError, TypeError) as e:
            return self._send({"erro": f"{type(e).__name__}: {e}"}, 422)

    def _admin_dados(self, metodo, c, q, b):
        m = self.model
        if c == "/_admin/status-cliente" and metodo == "GET":
            return self._send({"status": [{"codigo": c, "nome": n, "descricao": d} for c, n, d in perfil.status_pares()]})
        if c == "/_admin/roteiros" and metodo == "GET":
            return self._send({"roteiros": roteiros.listar(self.erp), "usados": self.model.ids.total_usados()})
        if c == "/_admin/roteiros/limpar-usados" and metodo == "POST":
            self.model.ids.limpar_usados()
            return self._send({"ok": True})
        mr = re.fullmatch(r"/_admin/roteiros/([\w-]+)/executar", c)
        if mr and metodo == "POST":
            execucao = roteiros.executar(m, mr.group(1), self.erp)
            execucao["consulta"] = roteiros.consulta(execucao["ids_externos"], _int(b.get("conta"), None))
            return self._send(execucao)
        if c == "/_admin/conferencia/consulta" and metodo == "POST":
            ids = [str(i) for i in b.get("ids", [])]
            return self._send({"consulta": roteiros.consulta(ids, _int(b.get("conta"), None))})
        if c == "/_admin/roteiros/avaliar" and metodo == "POST":
            return self._send({"resultados": roteiros.avaliar(b.get("verificacoes", []), b.get("linhas", []), b.get("antes"))})
        if c == "/_admin/modelos" and metodo == "GET":
            return self._send(dados.modelos())
        if c == "/_admin/exportar" and metodo == "GET":
            return self._send(dados.exportar(m))
        if c == "/_admin/importar" and metodo == "POST":
            return self._send(dados.importar(m, b.get("texto"), b.get("formato", "auto"), b.get("entidade"), b.get("modo", "acrescentar"),
                                             bool(b.get("permitir_telefone_real")), bool(b.get("simular", True))))
        if c == "/_admin/volume" and metodo == "GET":
            return self._send(self._totais())
        if c == "/_admin/volume" and metodo == "POST":
            return self._send(self._volume(b))
        if c == "/_admin/horarios" and metodo == "GET":
            try:
                return self._send(ops.horarios_da_agenda(m, q.get("profissional_id"), q.get("unidade_id"), q.get("dias") or 7))
            except (Conflito, TypeError, ValueError) as e:
                return self._erro(409, str(e))
        if c == "/_admin/schedules" and metodo == "GET":
            return self._send(ops.buscar_agendamentos(
                m, q.get("q", ""), q.get("cenario"), q.get("unidade_id"), q.get("profissional_id"), q.get("status_id"),
                q.get("dia"), _int(q.get("limite"), 20), _int(q.get("inicio"), 0)))
        if c == "/_admin/schedule" and metodo == "POST":
            return self._send(ops.criar_agendamento(m, b))
        mt = re.fullmatch(r"/_admin/schedule/(\d+)(?:/(acao))?", c)
        if mt and metodo == "POST":
            sid = int(mt.group(1))
            if mt.group(2):
                acao = {k: v for k, v in b.items() if k != "acao"}
                return self._send({"ok": True, "agendamento": ops.acao(m, sid, b.get("acao"), **acao)})
            s = m.schedules.get(sid)
            if not s:
                return self._send({"ok": False}, 404)
            s.update({k: v for k, v in b.items() if k in s and k not in ("agendamento_id",)})
            return self._send({"ok": True, "agendamento": m.schedule_json(s, True)})
        if c == "/_admin/insurance/sync" and metodo == "POST":
            achado = next((i for i in m.hidden_insurances if i["convenio_id"] == b.get("convenio_id")), None)
            if not achado:
                return self._send({"ok": False, "message": "convenio_id não está na lista oculta"}, 404)
            m.hidden_insurances.remove(achado)
            m.insurances.append(achado)
            return self._send({"ok": True})
        mt = re.fullmatch(r"/_admin/entities/(\w+)(?:/(\d+)(?:/(remover))?)?", c)
        if mt:
            tipo, ident, remover = mt.groups()
            if metodo == "GET" and not ident:
                return self._send(ops.listar(m, tipo, q.get("q", ""), _int(q.get("limite"), 20), _int(q.get("inicio"), 0)))
            if metodo == "POST" and not ident:
                return self._send({"id": ops.criar(m, tipo, b)})
            if metodo == "POST" and remover:
                ops.remover(m, tipo, ident)
                return self._send({"ok": True})
            if metodo == "POST":
                ops.atualizar(m, tipo, ident, b)
                return self._send({"ok": True})
        return self._send({"ok": False, "message": "rota admin desconhecida"}, 404)

    def _volume(self, b):
        modo = b.get("modo", "acrescentar")
        n = lambda k, p=0: int(b.get(k) or p)
        if modo == "acrescentar":
            feito = dados.acrescentar_volume(self.model, n("pacientes"), n("profissionais"), n("agendamentos"), n("dias", 14), b.get("semente"))
            return {"modo": modo, "criados": feito, **self._totais()}
        if modo != "regerar":
            raise ValueError("modo deve ser acrescentar ou regerar")
        lim = dados.LIMITES
        pac, ag, prof, un = n("pacientes", 600), n("agendamentos", 1500), n("profissionais", 40), n("unidades", 3)
        if not (0 <= pac <= lim["pacientes"] and 0 <= ag <= lim["agendamentos"] and 1 <= prof <= lim["profissionais"] and 1 <= un <= 4):
            raise ValueError(f"Limites: pacientes até {lim['pacientes']}, agendamentos até {lim['agendamentos']}, "
                             f"profissionais de 1 a {lim['profissionais']}, unidades de 1 a 4 (para mais unidades, importe)")
        c = self.ctx
        seed = int(b["semente"]) if b.get("semente") not in (None, "") else c.args[0]
        c.args = (seed, pac, ag, max(1, min(n("dias", 14), 365)), c.args[4], c.args[5], un)
        c.extra = {"profissionais": prof}
        c.model = c.novo_model()
        return {"modo": modo, **self._totais()}

    def _totais(self):
        m = self.model
        return {"totais": {"unidades": len(m.units), "profissionais": len(m.professionals), "pacientes": len(m.patients),
                           "agendamentos": len(m.schedules)}}

    def _diario(self, q):
        with self.lock:
            itens = list(self.journal)
        if q.get("desde_id"):
            itens = [e for e in itens if e["id"] > _int(q["desde_id"], 0)]
        if q.get("caminho"):
            itens = [e for e in itens if q["caminho"].lower() in e["caminho"].lower()]
        if q.get("so_erros") == "1":
            itens = [e for e in itens if e["status"] >= 400 or e["status"] == 0 or e["falha"]]
        if q.get("erp"):
            itens = [e for e in itens if e.get("erp") == q["erp"]]
        if q.get("origem") == "tunel":
            itens = [e for e in itens if e["tunel"]]
        limite = _int(q.get("limite"), 100)
        return self._send({"total": len(itens), "itens": itens[::-1][:limite]})

    def _catalogo(self):
        if self.erp == "netpacs":
            return erp_netpacs.CATALOGO
        if self.erp == "tasy":
            return erp_tasy.CATALOGO
        itens = []
        for metodo, caminho, secao, resumo, params, erros, uso in ENDPOINTS:
            itens.append({"metodo": metodo, "caminho": caminho, "secao": secao, "resumo": resumo, "parametros": params,
                          "erros": erros, "uso_cliente": uso, "implementado": (metodo, caminho) in ROUTES,
                          "na_documentacao": "NÃO aparece na documentação" not in uso and not secao.startswith("Financeiro")})
        return {"fonte": DOC_URL, "consultada_em": "15/10/2026", "rotas": itens, "nao_implementadas": NAO_IMPLEMENTADAS,
                "diferencas": DIFERENCAS}


def build_server(port=0, host="127.0.0.1", *, token="fake-token", seed=42, patients=600, schedules=1500, days=14,
                 phone=None, phone_count=5, units=3, base=Handler, ids_path=None, tokens=None):
    """`token` vale para o Feegow. `tokens` ({"netpacs": ..., "tasy": ...}) liga os outros ERPs com chave própria."""
    tokens = dict(tokens or {})
    ctxs = {}
    for nome in ERPS:
        args = (seed + MARCAS[nome][2], patients, schedules, days, phone, phone_count, units)
        ids = IdStore(_ids_do_erp(ids_path, nome))
        ctxs[nome] = Ctx(nome, args, ids, (token or None) if nome == "feegow" else tokens.get(nome, token or None))
    handler = type("FakeHandler", (base,), {
        "ctxs": ctxs, "ctx": ctxs["feegow"], "journal": deque(maxlen=1000),
        "lock": threading.Lock(), "seq": itertools.count(1),
        "config": {"paginacao_real": True}})
    return ThreadingHTTPServer((host, port), handler)


def _ids_do_erp(ids_path, nome):
    if ids_path is None or nome == "feegow":
        return ids_path
    from pathlib import Path
    caminho = Path(ids_path)
    return caminho.with_name(f"{caminho.stem}-{nome}{caminho.suffix}")
