"""Dialeto Tasy: a interface HTTP do agente tasy-api que [[o_cliente]] enxerga (o banco Oracle fica escondido atrás dele)."""
import base64
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta

from . import perfil
from .dialeto import compila, data_br, digitos, epoch_ms, rota, sexo_letra, ts_texto
from .model import Conflito, sdate

STATUS_TASY = {1: "N", 7: "CN", 11: "C", 15: "I", 2: "E", 3: "O", 4: "AC", 5: "AR", 6: "F"}
STATUS_DOMINIO = {"N": "Normal", "CN": "Confirmado", "C": "Cancelado", "I": "Inativado", "E": "Em atendimento", "O": "Atendido",
                  "AC": "Aguardando", "AR": "Aguardando retorno", "F": "Faltou", "L": "Livre", "M": "Marcado", "B": "Bloqueado"}
DURACAO = 30
PRIMEIROS = {"schedules", "schedule", "clientSchedules", "price", "codestatus", "client", "register_client",
             "update_personal_data", "free_hours", "agenda_free_hours", "register_schedule_with_client_data", "reschedule",
             "reserve_hour", "reserve_hour_exam", "cancel_reserve_hour", "selectGeneric", "executeGeneric",
             "callGenericProcedure", "schedulesStatus", "agenda", "professionals_available", "cooperados_available",
             "waitingList", "customSchedules"}

ROTAS = compila([
    ("GET", "/codestatus", "_ta_codestatus"),
    ("GET", "/schedules", "_ta_schedules"),
    ("GET", "/clientSchedules", "_ta_schedules"),
    ("GET", "/schedules/{id}/confirmStatus", "_ta_confirm_status"),
    ("GET", "/schedule/{id}/confirmStatus", "_ta_confirm_status"),
    ("GET", "/schedules/{id}/transfer", "_ta_transfer"),
    ("POST", "/schedules/{id}/confirm", "_ta_confirmar"),
    ("DELETE", "/schedules/{id}/cancel", "_ta_cancelar"),
    ("POST", "/schedulesStatus/{tipo}", "_ta_status_lote"),
    ("GET", "/price", "_ta_preco"),
    ("POST", "/selectGeneric/{nome}", "_ta_select_generico"),
    ("GET", "/agenda/blocks", "_ta_vazio_objeto"),
    ("GET", "/professionals_available", "_ta_profissionais"),
    ("GET", "/client", "_ta_cliente"),
    ("POST", "/register_client", "_ta_cliente_criar"),
    ("POST", "/update_personal_data", "_ta_cliente_atualizar"),
    ("GET", "/free_hours", "_ta_horarios"),
    ("GET", "/agenda_free_hours", "_ta_vazio_objeto"),
    ("POST", "/register_schedule_with_client_data", "_ta_agendar"),
    ("POST", "/reschedule", "_ta_reagendar"),
    ("POST", "/reserve_hour", "_ta_ok"),
    ("POST", "/cancel_reserve_hour", "_ta_ok"),
])


def _b64d(texto):
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


ALGORITMOS = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}


def jwt_valido(token, segredo):
    """Confere a assinatura HMAC (HS256, HS384 ou HS512, o que a biblioteca [[do_cliente]] escolhe pelo tamanho da chave)."""
    try:
        cab, corpo, assinatura = token.split(".")
        alg = json.loads(_b64d(cab)).get("alg", "HS256")
        if alg not in ALGORITMOS:
            return False
        esperado = hmac.new(segredo.encode(), f"{cab}.{corpo}".encode(), ALGORITMOS[alg]).digest()
        if not hmac.compare_digest(esperado, _b64d(assinatura)):
            return False
        dados = json.loads(_b64d(corpo))
        emissor = perfil.ativo().emissor_jwt
        return (emissor is None or dados.get("iss") == emissor) and dados.get("exp", 1e18) > datetime.now().timestamp()
    except (ValueError, KeyError, TypeError):
        return False


def id_horario(prof, unidade, d, hhmm):
    return int(f"{prof}{unidade}{d.strftime('%Y%m%d')}{hhmm[:2]}{hhmm[3:5]}")


def decodifica_horario(hid):
    t = str(hid)
    if len(t) < 16 or not t.isdigit():
        raise ValueError("hourId inválido")
    hhmm, dia, unidade, prof = t[-4:], t[-12:-4], t[-15:-12], t[:-15]
    return int(prof), int(unidade), datetime.strptime(dia, "%Y%m%d").date(), f"{hhmm[:2]}:{hhmm[2:]}"


class TasyMixin:
    def _auth_tasy(self):
        cab = self.headers.get("Authorization") or ""
        partes = cab.split(" ")
        if len(partes) < 2:
            self._send_text("Ops!", 401, "text/plain; charset=utf-8")
            return True
        if self.token and not jwt_valido(partes[1], self.token):
            self._send_text("Ops!", 401, "text/plain; charset=utf-8")
            return True
        return False

    def _ta_texto(self, texto, code=200):
        self._send_text(texto, code, "text/plain; charset=utf-8")

    def _ta_ok(self, q, b, *g):
        self._ta_texto("OK")

    def _ta_vazio_objeto(self, q, b, *g):
        self._send({})

    def _ta_profissionais(self, q, b):
        self._send([])

    def _ta_select_generico(self, q, b, nome):
        self._send([])

    def _ta_codestatus(self, q, b):
        self._send(STATUS_DOMINIO)

    def _ta_agente_json(self, s):
        m = self.model
        prof = next((p for p in m.professionals if p["profissional_id"] == s["profissional_id"]), None) or {}
        proc = next((p for p in m.procedures if p["procedimento_id"] == s["procedimento_id"]), None) or {}
        unit = next((u for u in m.units if u["unidade_id"] == s["unidade_id"]), None) or {}
        pac = m.patients.get(s["paciente_id"]) or {"nome": f"Paciente {s['paciente_id']}", "documentos": {}}
        esp = next((e for e in m.specialties if e["especialidade_id"] == s.get("especialidade_id")), None)
        conv = next((i for i in m.insurances + m.hidden_insurances if i["convenio_id"] == s["convenio_id"]), None)
        plano = next((pl for pl in (conv or {}).get("planos", []) if pl["plano_id"] == s.get("plano_id")), None)
        d, hh = sdate(s), s["horario"][:5]
        nasc = None
        if pac.get("nascimento"):
            try:
                nasc = epoch_ms(datetime.strptime(str(pac["nascimento"])[:10], "%Y-%m-%d").date())
            except ValueError:
                nasc = None
        st = STATUS_TASY.get(s["status_id"], "N")
        valor = s["valor_total_agendamento"]
        preco = f"{valor:.2f}" if isinstance(valor, (int, float)) else (valor if valor not in (None, "") else None)
        return {
            "id": str(s["agendamento_id"]), "compId": str(s["unidade_id"]), "compName": unit.get("nome_fantasia"),
            "resourceId": str(s["profissional_id"]), "resourceName": prof.get("nome"),
            "expertise": esp["nome"] if esp else None, "expertiseId": str(esp["especialidade_id"]) if esp else None,
            "payTypeId": str(conv["convenio_id"]) if conv else "1", "payTypeName": conv["nome"] if conv else "Particular",
            "planTypeId": str(plano["plano_id"]) if plano else None, "planTypeName": plano["plano"] if plano else None,
            "typeId": str(s["procedimento_id"]), "typeName": proc.get("nome"), "typeNotes": proc.get("preparo"),
            "duration": DURACAO, "clientId": str(s["paciente_id"]), "clientName": pac.get("nome"),
            "clientPhone": pac.get("celular"), "clientEmail": pac.get("email"), "clientBirthdate": nasc,
            "sex": sexo_letra(pac.get("sexo")), "CPF": digitos(pac["documentos"].get("cpf")) or None, "status": st,
            "date": epoch_ms(d, hh), "agenda": f"{s['profissional_id']};Agenda {prof.get('nome')};Normal", "fit": False,
            "price": preco, "agendaType": "c", "confirmationDate": ts_texto(d, hh) if st == "CN" else None,
            "confirmUser": "recepcao" if st == "CN" else None}

    def _ta_schedules(self, q, b):
        m = self.model
        if q.get("exams") == "true":
            return self._send([])
        hoje = date.today()
        alvo = q.get("id_agendamento")
        lista = [s for s in m.schedules.values() if s["status_id"] != 16]
        if alvo and alvo.isdigit():
            lista = [s for s in lista if str(s["agendamento_id"]) == alvo]
        else:
            dias = int(q["maxDays"]) if str(q.get("maxDays", "")).isdigit() else 7
            lista = [s for s in lista if hoje <= sdate(s) < hoje + timedelta(days=dias)]
        if q.get("companyCustomIds") not in (None, "", "null"):
            ids = {x for x in q["companyCustomIds"].split(",")}
            lista = [s for s in lista if str(s["unidade_id"]) in ids]
        lista.sort(key=lambda s: (sdate(s), s["horario"], s["agendamento_id"]))
        self._send([self._ta_agente_json(s) for s in lista])

    def _ta_achar(self, ident):
        n = ident.split("_")[0]
        return self.model.schedules.get(int(n)) if n.isdigit() else None

    def _ta_confirm_status(self, q, b, ident):
        s = self._ta_achar(ident)
        if not s or s["status_id"] == 16:
            return self._send({})
        d, hh = sdate(s), s["horario"][:5]
        confirmado = s["status_id"] == 7
        self._send({"ie_status_agenda": STATUS_TASY.get(s["status_id"], "N"),
                    "dt_confirmacao": ts_texto(d, hh) if confirmado else None,
                    "nm_usuario_confirm": "recepcao" if confirmado else None, "dt_agenda": ts_texto(d, hh)})

    def _ta_transfer(self, q, b, ident):
        s = self._ta_achar(ident)
        self._ta_texto("Transferido para outro horário (fake)" if s and s["status_id"] == 16 else "null")

    def _ta_confirmar(self, q, b, ident):
        s = self._ta_achar(ident)
        if not s:
            return self._ta_texto("NOT_FOUND")
        if s["status_id"] not in (1, 7):
            return self._ta_texto(f"NOT_VALID_STATUS={STATUS_TASY.get(s['status_id'], '?')}")
        s["status_id"] = 7
        s["confirmacao"] = {"canal": q.get("system"), "desc": q.get("desc")}
        self._ta_texto("OK")

    def _ta_cancelar(self, q, b, ident):
        s = self._ta_achar(ident)
        if not s:
            return self._ta_texto("NOT_FOUND")
        if s["status_id"] not in (1, 7):
            return self._ta_texto(f"NOT_VALID_STATUS={STATUS_TASY.get(s['status_id'], '?')}")
        s["status_id"] = 11
        s["cancelamento"] = {"canal": q.get("system"), "desc": q.get("desc")}
        self._ta_texto("OK")

    def _ta_status_lote(self, q, b, tipo):
        ids = [x.strip() for x in str(b if not isinstance(b, dict) else "").split(",") if x.strip()]
        out = {}
        for i in ids:
            s = self._ta_achar(i)
            if s:
                out[i] = f"{STATUS_TASY.get(s['status_id'], 'N')};{'true' if s['status_id'] == 3 else 'false'}"
        self._send(out)

    def _ta_preco(self, q, b):
        proc = next((p for p in self.model.procedures if str(p["procedimento_id"]) == str(q.get("customScheduleTypeId", "")).split(";")[0]), None)
        if not proc:
            return self._ta_texto("")
        self._send({"price": float(proc["base"]), "inCents": True})

    # ----- paciente -----
    def _ta_cliente_json(self, p):
        nasc = str(p.get("nascimento") or "")[:10]
        cel = digitos(p.get("celular"))
        return {"ID_PACIENTE": str(p["paciente_id"]), "CARTEIRINHA": None, "NR_CPF_P": digitos(p["documentos"].get("cpf")),
                "NM_PESSOA_FISICA_P": p["nome"], "NM_SOCIAL_P": p.get("nome_social"),
                "DT_NASCIMENTO_P": f"{nasc} 00:00:00" if nasc else None, "IE_SEXO_P": sexo_letra(p.get("sexo")),
                "NR_DDD_CELULAR_P": cel[2:4] if cel.startswith("55") else cel[:2],
                "NR_TELEFONE_CELULAR_P": cel[4:] if cel.startswith("55") else cel[2:]}

    def _ta_cliente(self, q, b):
        cpf = digitos(q.get("CPF"))
        achado = next((p for p in self.model.patients.values() if cpf and digitos(p["documentos"].get("cpf")) == cpf), None)
        self._send(self._ta_cliente_json(achado) if achado else {})

    def _ta_cliente_criar(self, q, b):
        if not q.get("clientName") or not q.get("clientCPF"):
            return self._ta_texto("ERROR")
        nasc = None
        if str(q.get("clientBirthdate", "")).isdigit():
            nasc = datetime.fromtimestamp(int(q["clientBirthdate"]) / 1000).date().isoformat()
        self.model.add_patient({"nome_completo": q["clientName"], "cpf": digitos(q["clientCPF"]), "data_nascimento": nasc,
                                "genero": q.get("clientGender"), "celular": digitos(q.get("clientPhone")) or None})
        self._ta_texto("OK")

    def _ta_cliente_atualizar(self, q, b):
        p = self.model.patients.get(int(q["clientId"])) if str(q.get("clientId", "")).isdigit() else None
        if not p:
            return self._ta_texto("NOT_FOUND")
        if q.get("clientName"):
            p["nome"] = q["clientName"]
        if q.get("clientPhone"):
            p["celular"] = digitos(q["clientPhone"])
            p["celulares"] = [p["celular"]]
        if q.get("clientEmail"):
            p["email"] = q["clientEmail"]
        self._ta_texto("OK")

    # ----- horários e agendamento -----
    def _ta_horarios(self, q, b):
        m = self.model
        if not str(q.get("company", "")).isdigit():
            return self._send([])
        unidade = int(q["company"])
        esp = q.get("expertiseId")
        medico = q.get("resourceCustomId")
        itens = []
        for p in m.professionals:
            if unidade not in p["unidades"]:
                continue
            if medico not in (None, "", "null") and str(p["profissional_id"]) != medico:
                continue
            if esp not in (None, "", "null") and not any(str(e["especialidade_id"]) == esp for e in p["especialidades"]):
                continue
            for dia, horas in m.free_slots(p, unidade, date.today(), date.today() + timedelta(days=6)).items():
                for h in horas:
                    itens.append((dia, h[:5], p))
        itens.sort(key=lambda x: (x[0], x[1], x[2]["profissional_id"]))
        saida = []
        for dia, hh, p in itens[:80]:
            d = date.fromisoformat(dia)
            saida.append({"hourId": str(id_horario(p["profissional_id"], unidade, d, hh)), "hour": epoch_ms(d, hh),
                          "hourString": ts_texto(d, hh), "resourceCustomId": str(p["profissional_id"]), "turn": "1",
                          "customStatus": "L"})
        self._send(saida)

    def _ta_agendar(self, q, b):
        m = self.model
        try:
            prof, unidade, d, hhmm = decodifica_horario(q["nr_sequencia"])
        except (KeyError, ValueError):
            return self._ta_texto("ERROR")
        cpf = digitos(q.get("clientCPF"))
        pac = next((p for p in m.patients.values() if cpf and digitos(p["documentos"].get("cpf")) == cpf), None)
        if not pac:
            return self._ta_texto("<html>404 paciente não encontrado</html>", 404)
        proc = next((p for p in m.procedures if p["tipo_procedimento"] == 1), m.procedures[0])
        conv = int(q["paymentTypeCustomId"]) if str(q.get("paymentTypeCustomId", "")).isdigit() else None
        corpo = {"paciente_id": pac["paciente_id"], "profissional_id": prof, "procedimento_id": proc["procedimento_id"],
                 "local_id": unidade, "data": d.isoformat(), "horario": hhmm + ":00"}
        if conv in {i["convenio_id"] for i in m.insurances}:
            corpo["convenio_id"] = conv
        try:
            m.add_schedule(corpo, forced_id=int(q["nr_sequencia"]))
        except Conflito:
            return self._ta_texto("OCCUPIED")
        except (KeyError, StopIteration, TypeError, ValueError):
            return self._ta_texto("ERROR")
        self._ta_texto("OK")

    def _ta_reagendar(self, q, b):
        s = self._ta_achar(str(q.get("id", "")))
        if not s:
            return self._ta_texto(f"SCHEDULE_NOT_FOUND: {q.get('id')}")
        try:
            prof, unidade, d, hhmm = decodifica_horario(q["toId"])
        except (KeyError, ValueError):
            return self._ta_texto("INVALID_QUERY")
        if self.model.slot_taken(prof, d, hhmm + ":00", ignore_id=s["agendamento_id"]):
            return self._ta_texto("ERROR")
        s.update(abs_date=d, horario=hhmm + ":00", profissional_id=prof, unidade_id=unidade, status_id=1)
        self._ta_texto("OK")


def _r(metodo, caminho, resumo, params=(), uso="", erros=(), doc=True):
    r = rota(metodo, caminho, "Agente Tasy", resumo, params, erros, uso)
    r["na_documentacao"] = doc
    return r


CATALOGO = {
    "fonte": "[[fonte_tasy]]",
    "consultada_em": "16/10/2026",
    "rotas": [
        _r("GET", "/codestatus", "Domínio de status do Tasy", [], "Também serve de ping: [[o_cliente]] considera o agente no ar se isto responde"),
        _r("GET", "/schedules", "Agendamentos de consulta (exams=false) ou exame (exams=true). O campo price vem da coluna VL_AGENDAMENTO", ["exams", "maxDays", "id_agendamento", "companyCustomIds"],
           "Carga principal. Tudo (unidade, profissional, convênio, procedimento, paciente) vem embutido em cada item.",
           ["5xx, JSON inválido ou corpo vazio falham a carga daquele tipo", "[] não cancela nada na hora: [[o_cliente]] confere cada sumido em transfer e confirmStatus"]),
        _r("GET", "/schedules/{nr}/confirmStatus", "Estado de um agendamento que não veio na carga", [], "{} significa que não existe mais (tratado como agendamento removido)"),
        _r("GET", "/schedules/{nr}/transfer", "Histórico de transferência", [], "Texto significa transferido; 'null' significa que não achou"),
        _r("POST", "/schedules/{nr}/confirm", "Confirma", ["system", "desc", "exam"], "Só a resposta exata OK conta como sucesso"),
        _r("DELETE", "/schedules/{nr}/cancel", "Cancela", ["system", "desc", "exam"], "Só OK conta. Outra resposta faz [[o_cliente]] marcar como sumido do Tasy"),
        _r("POST", "/schedulesStatus/{schedule|exam}", "Status em lote (presença)", ["corpo texto: ids separados por vírgula"], "Job de execução"),
        _r("GET", "/price", "Preço de tabela", ["customPaymentTypeId", "customScheduleTypeId", "customCompanyId"],
           "Observado em 16/10/2026: [[o_cliente]] chama durante a carga, uma vez por procedimento e unidade (34 x 3 = 90 chamadas), só para particular (customPaymentTypeId 1). Convênio fica sem preço."),
        _r("GET", "/client", "Busca paciente", ["CPF", "CD_USUARIO_CONVENIO"], "{} quando não acha"),
        _r("POST", "/register_client", "Cria paciente", ["clientName", "clientCPF", "clientBirthdate", "clientGender", "clientPhone"], "OK ou ERROR"),
        _r("POST", "/update_personal_data", "Atualiza paciente", ["clientId", "clientName", "clientPhone", "clientEmail"], "Resposta ignorada [[pelo_cliente]]"),
        _r("GET", "/free_hours", "Horários livres", ["company", "expertiseId", "resourceCustomId", "agendaType"], "Chatbot e reagendamento"),
        _r("POST", "/register_schedule_with_client_data", "Agenda no horário livre", ["nr_sequencia (hourId)", "clientCPF", "paymentTypeCustomId"],
           "OK ou OCCUPIED. [[O_cliente]] relê /schedules?id_agendamento=hourId e exige mesma data e nome do paciente"),
        _r("POST", "/reschedule", "Move agendamento para outro horário livre", ["id", "toId"], "OK exigido"),
        _r("POST", "/reserve_hour", "Reserva horário", ["NR_SEQUENCIA"], "OK"),
        _r("POST", "/cancel_reserve_hour", "Cancela reserva", ["NR_SEQUENCIA", "turn"], "OK"),
        _r("POST", "/selectGeneric/{QUERY}", "Consulta nomeada ao banco do cliente", [], "O fake devolve [] (AGENDAS, MODALITIES e as demais)"),
        _r("GET", "/agenda/blocks", "Bloqueios de agenda", ["agendas"], "O fake devolve {}"),
        _r("GET", "/professionals_available", "Profissionais disponíveis", [], "O fake devolve []"),
    ],
    "nao_implementadas": [
        "Exames: /schedules?exams=true devolve sempre [], e as rotas de exame (SCHEDULE_EXAM, PROCEDURE_RESCHEDULE_EXAM) não existem.",
        "executeGeneric, callGenericProcedure, waitingList, check-in, upload de arquivo, laudo, fila de senha e bloqueios reais.",
        "Integrações Tasy diferentes do agente: Tasy JDBC direto, Tasy TIE, Tasy Web e Clínica Sim.",
    ],
    "diferencas": [
        "Autenticação: [[o_cliente]] envia um JWT HS256 assinado com a chave da conta (32 caracteres ou mais). O fake confere a assinatura[[nota_emissor]].",
        "[[nota_tasy_conta]]",
        "O agendamento pode trazer price (texto): número com 2 casas como \"80.00\" quando a coluna é numérica, ou o texto do ERP como \"R$ 1.234,56\". Sem price, [[o_cliente]] usa o preço de tabela: chama /price por procedimento e unidade e grava só para particular (227 de 371 na primeira carga). Para mudar o preço de tabela, edite o valor base do procedimento em Dados.",
        "hourId dos horários livres codifica profissional, unidade, data e hora. É assim que o fake sabe qual horário foi pedido.",
        "Status do Tasy usados: N (a confirmar), CN, C, I, E, O, AC, AR, F. Agendamento remarcado some de /schedules e aparece em transfer.",
    ],
}
