"""Dialeto NetPacs: mesma clínica do modelo, servida no formato da API REST do NetPacs (rotas /netris/api/...)."""
import json
from datetime import date, datetime, timedelta

from .dialeto import compila, data_br, digitos, epoch_ms, epoch_ms_hora, rota, sexo_letra
from .model import STATUSES, Conflito, sdate

ID_FILIAL = 1
SITUACOES = {1: "A confirmar", 2: "Tentativa de confirmação", 3: "Confirmado", 4: "Chegou", 5: "Em exame",
             6: "Finalizado", 7: "Cancelado", 8: "Paciente faltou"}
SITUACAO_PARA_STATUS = {1: 1, 2: 1, 3: 7, 4: 4, 5: 2, 6: 3, 7: 11, 8: 6}
STATUS_PARA_NOME = {1: "A confirmar", 7: "Confirmado", 11: "Cancelado pelo paciente", 15: "Cancelado pelo profissional",
                    16: "Reagendado", 2: "Em exame", 3: "Finalizado", 4: "Chegou", 5: "Chegou", 6: "Paciente faltou"}
DURACAO = 20

ROTAS = compila([
    ("GET", "/netris/api/atendimentos", "_np_atendimentos"),
    ("GET", "/netris/api/atendimentos/{id}", "_np_atendimento"),
    ("PATCH", "/netris/api/atendimentos/{id}/alterar-situacao", "_np_alterar_situacao"),
    ("PATCH", "/netris/api/atendimentos/{id}/cancelar", "_np_cancelar"),
    ("GET", "/netris/api/pacientes", "_np_pacientes_buscar"),
    ("POST", "/netris/api/pacientes", "_np_paciente_criar"),
    ("GET", "/netris/api/pacientes/{id}", "_np_paciente_ler"),
    ("PUT", "/netris/api/pacientes/{id}", "_np_paciente_atualizar"),
    ("GET", "/netris/api/horarios", "_np_horarios"),
    ("POST", "/netris/api/horarios", "_np_agendar"),
    ("GET", "/netris/api/consultarPreco", "_np_preco"),
    ("GET", "/netris/api/unidades", "_np_unidades"),
    ("GET", "/netris/api/modalidades", "_np_modalidades"),
    ("GET", "/netris/api/procedimentos", "_np_procedimentos"),
    ("GET", "/netris/api/procedimentos/{id}", "_np_procedimento"),
    ("GET", "/netris/api/plano-convenios", "_np_planos"),
    ("GET", "/netris/api/plano-convenios/{id}", "_np_plano"),
    ("GET", "/netris/api/convenios/{id}", "_np_convenio"),
    ("GET", "/netris/api/especialidade/list", "_np_especialidades"),
    ("GET", "/netris/api/especialidade/{id}", "_np_especialidade_medicos"),
])


def _pagina(lista, q):
    limite = max(1, min(int(q.get("limit") or 100), 100))
    pag = max(1, int(q.get("page") or 1))
    return lista[(pag - 1) * limite: pag * limite]


def _valor_numerico(texto):
    """Número em reais como o NetPacs envia. Fora do limite [[do_cliente]] ainda sai como número, para ela descartar."""
    if texto in (None, ""):
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    t = "".join(c for c in str(texto) if c.isdigit() or c in ",.-")
    if not t:
        return None
    vc, vp = t.rfind(","), t.rfind(".")
    if vc >= 0 and vp >= 0:
        t = t.replace(".", "").replace(",", ".") if vc > vp else t.replace(",", "")
    elif vc >= 0:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


class NetpacsMixin:
    def _auth_netpacs(self):
        chave = self.headers.get("Authorization")
        if not chave:
            self._send({"message": "Chave de acesso ausente"}, 401)
            return True
        if self.token and chave != self.token:
            self._send({"message": "Chave de acesso inválida"}, 403)
            return True
        return False

    def _np_json(self, corpo, code=200):
        self._send(corpo, code)

    def _np_unidade_custom(self, uid):
        return f"{ID_FILIAL}#{uid}"

    def _np_atendimento_json(self, s):
        m = self.model
        prof = next((p for p in m.professionals if p["profissional_id"] == s["profissional_id"]), None) or {}
        proc = next((p for p in m.procedures if p["procedimento_id"] == s["procedimento_id"]), None) or {}
        unit = next((u for u in m.units if u["unidade_id"] == s["unidade_id"]), None) or {}
        pac = m.patients.get(s["paciente_id"]) or {"nome": f"Paciente {s['paciente_id']}", "documentos": {}}
        esp = next((e for e in m.specialties if e["especialidade_id"] == s.get("especialidade_id")), None)
        conv = next((i for i in m.insurances + m.hidden_insurances if i["convenio_id"] == s["convenio_id"]), None)
        plano = next((pl for pl in (conv or {}).get("planos", []) if pl["plano_id"] == s.get("plano_id")), None)
        d, hh = sdate(s), s["horario"][:5]
        st = s["status_id"]
        valor = s["valor_total_agendamento"]
        numero = _valor_numerico(valor)
        valor_json = numero if numero is not None else (valor if valor not in (None, "") else None)
        nasc = None
        if pac.get("nascimento"):
            try:
                nasc = epoch_ms(datetime.strptime(str(pac["nascimento"])[:10], "%Y-%m-%d").date())
            except ValueError:
                nasc = None
        return {
            "idAtendimentoProcedimento": s["agendamento_id"], "data": epoch_ms(d), "horaInicial": epoch_ms_hora(hh),
            "nomeSituacao": STATUS_PARA_NOME.get(st, "A confirmar"), "cancelado": st in (11, 15),
            "atendido": st == 3, "executado": st == 3, "encaixe": False,
            "idFilial": ID_FILIAL, "nomeFilial": "Rede NetPacs Fake", "idUnidade": s["unidade_id"],
            "nomeUnidade": unit.get("nome_fantasia"), "telefoneUnidade": unit.get("telefone_1"),
            "enderecoUnidade": f"{unit.get('endereco', '')}, {unit.get('numero', '')}", "bairroUnidade": unit.get("bairro"),
            "idMedicoExecutor": s["profissional_id"], "nomeMedicoExecutor": prof.get("nome"),
            "idProcedimento": s["procedimento_id"], "nomeProcedimento": proc.get("nome"),
            "duracaoProcedimento": DURACAO, "orientacao": proc.get("preparo"), "valorProcedimento": valor_json,
            "idPaciente": s["paciente_id"], "nomePaciente": pac.get("nome"), "dataNascimento": nasc,
            "cpf": digitos(pac.get("documentos", {}).get("cpf")) or None, "emailPaciente": pac.get("email"),
            "telefoneCelularPaciente": pac.get("celular"), "telefonePaciente": None, "sexoPaciente": sexo_letra(pac.get("sexo")),
            "idConvenio": conv["convenio_id"] if conv else 1, "nomeConvenio": conv["nome"] if conv else "Particular",
            "idPlanoConvenio": plano["plano_id"] if plano else 0, "nomePlanoConvenio": plano["plano"] if plano else None,
            "chaveModalidade": esp["nome"].upper() if esp else None, "descricaoModalidade": esp["nome"] if esp else None}

    def _np_atendimentos(self, q, b):
        m = self.model
        try:
            ini, fim = data_br(q["dataInicial"]), data_br(q["dataFinal"])
        except (KeyError, ValueError):
            return self._send({"message": "dataInicial e dataFinal são obrigatórias (dd/MM/yyyy)"}, 400)
        lista = [s for s in m.schedules.values() if ini <= sdate(s) <= fim]
        if q.get("listPatId"):
            lista = [s for s in lista if str(s["paciente_id"]) == q["listPatId"]]
        lista.sort(key=lambda s: (sdate(s), s["horario"], s["agendamento_id"]))
        self._send([self._np_atendimento_json(s) for s in _pagina(lista, q)])

    def _np_atendimento(self, q, b, ident):
        s = self.model.schedules.get(int(ident)) if ident.isdigit() else None
        if not s:
            return self._send({"message": "Atendimento não encontrado"}, 404)
        self._send(self._np_atendimento_json(s))

    def _np_alterar_situacao(self, q, b, ident):
        s = self.model.schedules.get(int(ident)) if ident.isdigit() else None
        if not s:
            return self._send({"message": "Atendimento não encontrado"}, 404)
        try:
            sit = int(b.get("idSituacao"))
        except (TypeError, ValueError):
            return self._send({"message": "idSituacao inválido"}, 400)
        if sit not in SITUACAO_PARA_STATUS:
            return self._send({"message": f"Situação {sit} não existe"}, 400)
        s["status_id"] = SITUACAO_PARA_STATUS[sit]
        self._send({"message": "Situação alterada com sucesso"})

    def _np_cancelar(self, q, b, ident):
        s = self.model.schedules.get(int(ident)) if ident.isdigit() else None
        if not s:
            return self._send({"message": "Atendimento não encontrado"}, 404)
        s["status_id"] = 11
        s["cancelamento"] = {"idMotivoSituacao": b.get("idMotivoSituacao"), "observacao": b.get("observacao")}
        self._send({"message": "Atendimento cancelado com sucesso"})

    # ----- pacientes -----
    def _np_paciente_resumo(self, p):
        return {"id_paciente": p["paciente_id"], "nome": p["nome"], "telefone_celular": p.get("celular"), "telefone": None,
                "sexo": sexo_letra(p.get("sexo")), "pat_id": p["paciente_id"]}

    def _np_pacientes_buscar(self, q, b):
        achados = []
        if q.get("cpf"):
            cpf = digitos(q["cpf"].split(":")[-1])
            achados = [p for p in self.model.patients.values() if digitos(p["documentos"].get("cpf")) == cpf]
        elif q.get("id_paciente"):
            ident = q["id_paciente"].split(":")[-1]
            achados = [p for p in self.model.patients.values() if str(p["paciente_id"]) == ident]
        self._send([self._np_paciente_resumo(p) for p in achados])

    def _np_paciente_criar(self, q, b):
        if not isinstance(b, dict) or not b.get("nomePaciente"):
            return self._send({"message": "nomePaciente é obrigatório"}, 422)
        nasc = None
        if b.get("dataNascimentoPaciente"):
            try:
                nasc = data_br(b["dataNascimentoPaciente"]).isoformat()
            except ValueError:
                nasc = None
        cpf = digitos(b.get("cpf"))
        existente = next((p for p in self.model.patients.values() if cpf and digitos(p["documentos"].get("cpf")) == cpf), None)
        if existente:
            return self._send({"message": "Já existe paciente com este CPF"}, 409)
        n = self.model.add_patient({"nome_completo": b["nomePaciente"], "cpf": cpf or None, "data_nascimento": nasc,
                                    "genero": b.get("sexoPaciente"), "celular": b.get("telefoneCelular"), "email": b.get("email")})
        self._send({"idPaciente": str(n)})

    def _np_paciente_ler(self, q, b, ident):
        p = self.model.patients.get(int(ident)) if ident.isdigit() else None
        if not p:
            return self._send({"message": "Paciente não encontrado"}, 404)
        self._send({"idPaciente": p["paciente_id"], "nomePaciente": p["nome"], "cpf": digitos(p["documentos"].get("cpf")),
                    "telefoneCelular": p.get("celular"), "email": p.get("email"), "sexoPaciente": sexo_letra(p.get("sexo"))})

    def _np_paciente_atualizar(self, q, b, ident):
        p = self.model.patients.get(int(ident)) if ident.isdigit() else None
        if not p:
            return self._send({"message": "Paciente não encontrado"}, 404)
        if b.get("nomePaciente"):
            p["nome"] = b["nomePaciente"]
        if b.get("telefoneCelular"):
            p["celular"] = b["telefoneCelular"]
            p["celulares"] = [b["telefoneCelular"]]
        if b.get("email"):
            p["email"] = b["email"]
        self._send({"idPaciente": p["paciente_id"], "message": "Paciente atualizado"})

    # ----- horários e agendamento -----
    def _np_horarios(self, q, b):
        m = self.model
        try:
            inicio = max(data_br(q["dataBusca"]), date.today())
        except (KeyError, ValueError):
            return self._send({"message": "dataBusca é obrigatória (dd/MM/yyyy)"}, 400)
        procs = [x for x in (q.get("listIdProcedimento") or "").split(",") if x.strip().isdigit()]
        proc = next((p for p in m.procedures if str(p["procedimento_id"]) == (procs[0] if procs else "")), m.procedures[0])
        unidades = [u["unidade_id"] for u in m.units]
        medico = q.get("idMedico")
        itens = []
        for p in m.professionals:
            if medico and str(p["profissional_id"]) != medico:
                continue
            for u in p["unidades"]:
                if q.get("idUnidade") and str(u) != q["idUnidade"] or u not in unidades:
                    continue
                for dia, horas in m.free_slots(p, u, inicio, inicio + timedelta(days=4)).items():
                    for h in horas:
                        itens.append((dia, h[:5], p, u))
        itens.sort(key=lambda x: (x[0], x[1], x[2]["profissional_id"]))
        saida = []
        for dia, hh, p, u in itens[:200]:
            d = date.fromisoformat(dia)
            saida.append({"idHorario": None, "idEscala": p["profissional_id"], "idMedico": p["profissional_id"],
                          "nomeMedico": p["nome"], "idSala": u, "data": epoch_ms(d), "dataString": d.strftime("%d/%m/%Y"),
                          "horaInicial": int(hh[:2]) * 60 + int(hh[3:5]), "horaInicialString": hh,
                          "idProcedimento": proc["procedimento_id"], "nomeProcedimento": proc["nome"],
                          "duracaoProcedimento": DURACAO, "idUnidade": u, "obs": None})
        self._send([saida] if saida else [])

    def _np_agendar(self, q, b):
        m = self.model
        item = b[0] if isinstance(b, list) and b else None
        if not isinstance(item, dict) or not item.get("listHorarioDTO"):
            return self._send({"message": "Corpo inválido: esperado array com listHorarioDTO"}, 422)
        hor = item["listHorarioDTO"][0]
        if not hor.get("dataString") or not hor.get("horaInicialString"):
            return self._send({"message": "Horário sem dataString e horaInicialString (idHorario não suportado pelo fake)"}, 422)
        try:
            pac = int(item["idPaciente"])
            conv = int(item["idConvenio"]) if item.get("idConvenio") else None
        except (KeyError, ValueError):
            return self._send({"message": "idPaciente ou idConvenio inválido"}, 422)
        if pac not in m.patients:
            return self._send({"message": "Paciente não encontrado"}, 404)
        corpo = {"paciente_id": pac, "profissional_id": hor.get("idMedico"), "procedimento_id": hor.get("idProcedimento"),
                 "local_id": hor.get("idSala"), "data": data_br(hor["dataString"]).isoformat(),
                 "horario": hor["horaInicialString"][:5] + ":00"}
        if conv in {i["convenio_id"] for i in m.insurances}:
            corpo["convenio_id"] = conv
            if item.get("idPlanoConvenio"):
                corpo["convenioplano"] = item["idPlanoConvenio"]
        try:
            sid = m.add_schedule(corpo)
        except Conflito:
            return self._send({"message": "O horário já foi ocupado"}, 409)
        except (KeyError, StopIteration, TypeError, ValueError) as e:
            return self._send({"message": f"Dados inválidos: {e!r}"}, 422)
        self._send({"message": f"Agendamento realizado com sucesso. ID: {sid}"})

    def _np_preco(self, q, b):
        proc = next((p for p in self.model.procedures if str(p["procedimento_id"]) == q.get("idProcedimento")), None)
        if not proc:
            return self._send({})
        self._send({"valorTotal": proc["base"] / 100})

    # ----- cadastros e verificação -----
    def _np_unidades(self, q, b):
        self._send([{"idUnidade": u["unidade_id"], "idFilial": ID_FILIAL, "nome": u["nome_fantasia"]} for u in self.model.units])

    def _np_modalidades(self, q, b):
        lista = [{"id_modalidade": 1, "descricao": "CONSULTA"}, {"id_modalidade": 2, "descricao": "EXAME"}]
        self._send(_pagina(lista, q))

    def _np_procedimentos(self, q, b):
        lista = [{"id_procedimento": p["procedimento_id"], "id_modalidade": p["tipo_procedimento"], "nome": p["nome"],
                  "tipo": "CONSULTA" if p["tipo_procedimento"] == 1 else "EXAME", "duracao": DURACAO, "orientacao": p["preparo"]}
                 for p in self.model.procedures]
        self._send(_pagina(lista, q))

    def _np_procedimento(self, q, b, ident):
        p = next((x for x in self.model.procedures if str(x["procedimento_id"]) == ident), None)
        if not p:
            return self._send({"message": "Procedimento não encontrado"}, 404)
        self._send({"id_procedimento": p["procedimento_id"], "nome": p["nome"], "orientacao": p["preparo"]})

    def _np_planos(self, q, b):
        lista = [{"id_convenio": i["convenio_id"], "id_plano_convenio": pl["plano_id"], "nome": pl["plano"]}
                 for i in self.model.insurances for pl in i["planos"]]
        self._send(_pagina(lista, q))

    def _np_plano(self, q, b, ident):
        for i in self.model.insurances:
            for pl in i["planos"]:
                if str(pl["plano_id"]) == ident:
                    return self._send({"nome": pl["plano"]})
        self._send({"message": "Plano não encontrado"}, 404)

    def _np_convenio(self, q, b, ident):
        i = next((x for x in self.model.insurances + self.model.hidden_insurances if str(x["convenio_id"]) == ident), None)
        if not i:
            return self._send({"message": "Convênio não encontrado"}, 404)
        self._send({"nome": i["nome"], "convenio_particular": False})

    def _np_especialidades(self, q, b):
        self._send([{"idEspecialidade": e["especialidade_id"], "nome": e["nome"]} for e in self.model.specialties])

    def _np_especialidade_medicos(self, q, b, ident):
        out = [{"idMedico": p["profissional_id"], "crm": str(14000 + p["profissional_id"]), "estadoCrm": "SC"}
               for p in self.model.professionals if any(str(e["especialidade_id"]) == ident for e in p["especialidades"])]
        self._send(out)


def _r(metodo, caminho, resumo, params=(), uso="", erros=()):
    return rota(metodo, caminho, "Atendimentos" if "atendimentos" in caminho else "NetPacs", resumo, params, erros, uso)


CATALOGO = {
    "fonte": "[[fonte_netpacs]]",
    "consultada_em": "16/10/2026",
    "rotas": [
        _r("GET", "/netris/api/atendimentos", "Lista os atendimentos (agendamentos) da janela",
           ["dataInicial dd/MM/yyyy", "dataFinal dd/MM/yyyy", "limit (100)", "page", "listPatId"],
           "Carga principal. Unidade, profissional, convênio, procedimento e paciente nascem dos campos de cada atendimento.",
           ["Resposta que não é array aborta a carga", "[] cancela tudo que [[o_cliente]] tinha na janela"]),
        _r("GET", "/netris/api/atendimentos/{id}", "Um atendimento", [], "Lido antes de confirmar e cancelar (data, paciente e status mudaram?)"),
        _r("PATCH", "/netris/api/atendimentos/{id}/alterar-situacao", "Muda a situação", ["idSituacao no corpo"],
           "Confirmar (idSituacao 3 por padrão)"),
        _r("PATCH", "/netris/api/atendimentos/{id}/cancelar", "Cancela", ["idMotivoSituacao", "observacao"], "Cancelar"),
        _r("GET", "/netris/api/pacientes", "Busca paciente", ["cpf=eq:<dígitos>", "id_paciente=eq:<id>"], "Achar paciente pelo CPF"),
        _r("POST", "/netris/api/pacientes", "Cria paciente", ["nomePaciente", "cpf", "telefoneCelular", "dataNascimentoPaciente", "sexoPaciente", "email"],
           "Resposta precisa ter idPaciente como TEXTO"),
        _r("GET", "/netris/api/pacientes/{id}", "Lê paciente", [], "Só com atualização de paciente no ERP ligada"),
        _r("PUT", "/netris/api/pacientes/{id}", "Atualiza paciente", [], "Só com atualização de paciente no ERP ligada"),
        _r("GET", "/netris/api/horarios", "Horários livres", ["dataBusca", "idFilial", "idMedico", "listIdProcedimento", "idConvenio", "idPlanoConvenio"],
           "Agendar e reagendar (chatbot). Resposta é array de arrays."),
        _r("POST", "/netris/api/horarios", "Cria agendamento", ["array com idPaciente, idConvenio, listHorarioDTO"],
           "Resposta {\"message\": \"... ID: N\"}", ["409 com 'já foi ocupado' vira horário ocupado"]),
        _r("GET", "/netris/api/consultarPreco", "Preço de tabela", ["dataString", "idPlanoConvenio", "idProcedimento"], "Chatbot, campo valorTotal em reais"),
        _r("GET", "/netris/api/unidades", "Lista unidades", [], "Verificação de que o ERP está no ar"),
        _r("GET", "/netris/api/modalidades", "Cadastro de modalidades", ["limit", "page"], "Só com importação de tipos de agendamento ligada"),
        _r("GET", "/netris/api/procedimentos", "Cadastro de procedimentos", ["limit", "page"], "Só com importação de tipos de agendamento ligada"),
        _r("GET", "/netris/api/plano-convenios", "Cadastro de planos", ["limit", "page"], "Só com importação de planos ligada"),
        _r("GET", "/netris/api/especialidade/list", "Cadastro de especialidades", [], "Só com importação de especialidades ligada"),
    ],
    "nao_implementadas": [
        "Variante V1 (URL sem /v2) e V2 POG (URL terminando em v2.pog).",
        "GET /netris/api/horarios-agrupados, laudos (/netpacs/api/laudos) e upload de arquivos.",
        "idHorario numérico em POST /netris/api/horarios: o fake devolve idHorario nulo e [[o_cliente]] envia o horário por campos.",
    ],
    "diferencas": [
        "Atendimento inexistente devolve 404. O código [[do_cliente]] também trata corpo vazio com 200 como não encontrado, e não se sabe qual dos dois o NetPacs real faz.",
        "Fuso: data e horaInicial seguem America/Sao_Paulo (UTC-3). Se [[o_cliente]] rodar em outro fuso, a hora aparece deslocada.",
        "Os nomes de situação seguem os reconhecidos pelo código [[do_cliente]] (A confirmar, Confirmado, Cancelado..., Chegou, Finalizado). Os nomes reais de cada cliente podem variar.",
        "Preço: valorProcedimento é número em reais. Valor em texto faz [[o_cliente]] descartar o preço (cenário valor_invalido).",
        "Na conta [[do_cliente]], a URL precisa terminar em /v2 e o host do túnel não pode conter a sequência v2.",
    ],
}
