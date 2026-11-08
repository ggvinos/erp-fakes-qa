import json
from datetime import date, datetime, timedelta

from .model import Conflito, br, cpf_ficticio, sdate

STATUS_POR_ACAO = {
    "confirmar": 7, "cancelar": 11, "desmarcar_profissional": 15, "chegou": 4, "em_atendimento": 2,
    "atendido": 3, "faltou": 6, "voltar_para_marcado": 1,
}

ACOES = [
    {"chave": "confirmar", "rotulo": "Confirmar", "ajuda": "A clínica confirma o agendamento (status 7)"},
    {"chave": "cancelar", "rotulo": "Cancelar (paciente)", "ajuda": "Desmarcado pelo paciente (status 11)"},
    {"chave": "desmarcar_profissional", "rotulo": "Desmarcar (profissional)", "ajuda": "Desmarcado pelo profissional (status 15)"},
    {"chave": "chegou", "rotulo": "Paciente chegou", "ajuda": "Aguardando atendimento (status 4)"},
    {"chave": "atendido", "rotulo": "Atendido", "ajuda": "Atendimento realizado (status 3)"},
    {"chave": "faltou", "rotulo": "Faltou", "ajuda": "Não compareceu (status 6)"},
    {"chave": "voltar_para_marcado", "rotulo": "Voltar para marcado", "ajuda": "Marcado, não confirmado (status 1)"},
    {"chave": "remarcar", "rotulo": "Remarcar", "ajuda": "Mesmo id, nova data e horário (o Feegow mantém o id)"},
    {"chave": "trocar_profissional", "rotulo": "Trocar profissional", "ajuda": "Outro profissional no mesmo agendamento"},
    {"chave": "trocar_convenio", "rotulo": "Trocar convênio", "ajuda": "Vazio volta para particular"},
    {"chave": "trocar_procedimento", "rotulo": "Trocar procedimento", "ajuda": "Outro procedimento no mesmo agendamento"},
    {"chave": "definir_valor", "rotulo": "Definir valor", "ajuda": "Valor total enviado pelo ERP (vazio remove)"},
    {"chave": "sumir", "rotulo": "Sumir do ERP", "ajuda": "O agendamento deixa de existir no ERP (teste de não encontrado)"},
]

ENTIDADES = {
    "unidades": ("unidade_id", {"nome_fantasia": "texto", "razao_social": "texto", "cnpj": "texto", "telefone_1": "texto",
                                "endereco": "texto", "numero": "texto", "bairro": "texto", "cidade": "texto",
                                "estado": "texto", "cep": "texto"}),
    "especialidades": ("especialidade_id", {"nome": "texto", "codigo_tiss": "texto"}),
    "convenios": ("convenio_id", {"nome": "texto", "registro_ans": "texto"}),
    "planos": ("plano_id", {"plano": "texto", "convenio_id": "inteiro"}),
    "tabelas": ("tabela_id", {"nome_tabela": "texto", "mult": "decimal"}),
    "procedimentos": ("procedimento_id", {"nome": "texto", "tipo_procedimento": "inteiro", "base": "inteiro", "preparo": "texto"}),
    "profissionais": ("profissional_id", {"nome": "texto", "sexo": "texto", "ativo": "booleano", "unidades": "lista",
                                           "especialidades": "lista", "convenios": "lista"}),
    "pacientes": ("paciente_id", {"nome": "texto", "nascimento": "texto", "sexo": "texto", "celular": "texto",
                                   "email": "texto", "cpf": "texto"}),
    "bloqueios": ("id", {"description": "texto", "professional_id": "inteiro", "date_start": "texto", "date_end": "texto",
                          "time_start": "texto", "time_end": "texto", "week_day": "lista", "units": "lista"}),
}


def _coerce(tipo, valor):
    if tipo == "inteiro":
        return None if valor in (None, "") else int(valor)
    if tipo == "decimal":
        return float(str(valor).replace(",", "."))
    if tipo == "booleano":
        return valor in (True, "true", "1", 1, "sim")
    if tipo == "lista":
        if isinstance(valor, list):
            return valor
        return [x.strip() for x in str(valor).split(",") if x.strip()]
    return None if valor is None else str(valor)


def _planos(m):
    return [dict(pl, convenio_id=i["convenio_id"]) for i in m.insurances for pl in i["planos"]]


def _linhas(m, tipo):
    if tipo == "unidades":
        return m.units
    if tipo == "especialidades":
        return m.specialties
    if tipo == "convenios":
        return [{k: v for k, v in i.items() if k != "planos"} | {"planos": len(i["planos"])} for i in m.insurances]
    if tipo == "planos":
        return _planos(m)
    if tipo == "tabelas":
        return [{k: v for k, v in t.items() if k != "ExibirAgendamentoOnline"} for t in m.tables]
    if tipo == "procedimentos":
        return m.procedures
    if tipo == "profissionais":
        return [{"profissional_id": p["profissional_id"], "nome": p["nome"], "sexo": p["sexo"], "ativo": p["ativo"],
                 "unidades": p["unidades"], "especialidades": [e["especialidade_id"] for e in p["especialidades"]],
                 "convenios": [c["convenio_id"] for c in p["convenios"]]} for p in m.professionals]
    if tipo == "pacientes":
        return [{"paciente_id": p["paciente_id"], "nome": p["nome"], "nascimento": p["nascimento"], "sexo": p["sexo"],
                 "celular": p["celular"], "email": p["email"], "cpf": p["documentos"]["cpf"]} for p in m.patients.values()]
    if tipo == "bloqueios":
        return m.blocks
    raise ValueError(f"tipo de entidade desconhecido: {tipo}")


def listar(m, tipo, q="", limite=20, inicio=0):
    if tipo not in ENTIDADES:
        raise ValueError(f"tipo de entidade desconhecido: {tipo}")
    idf, campos = ENTIDADES[tipo]
    rows = _linhas(m, tipo)
    if q:
        q = q.lower()
        rows = [r for r in rows if q in json.dumps(r, ensure_ascii=False, default=str).lower()]
    return {"tipo": tipo, "id": idf, "editaveis": campos, "total": len(rows), "linhas": rows[inicio:inicio + limite]}


def _achar(m, tipo, ident):
    idf = ENTIDADES[tipo][0]
    ident = int(ident)
    fontes = {"unidades": m.units, "especialidades": m.specialties, "convenios": m.insurances, "tabelas": m.tables,
              "procedimentos": m.procedures, "profissionais": m.professionals, "bloqueios": m.blocks}
    if tipo == "planos":
        for i in m.insurances:
            for pl in i["planos"]:
                if pl["plano_id"] == ident:
                    return pl, i
        return None, None
    if tipo == "pacientes":
        return m.patients.get(ident), None
    return next((x for x in fontes[tipo] if x[idf] == ident), None), None


def _aplicar(m, tipo, obj, campos):
    meta = ENTIDADES[tipo][1]
    for k, v in campos.items():
        if k not in meta:
            continue
        v = _coerce(meta[k], v)
        if tipo == "profissionais" and k == "especialidades":
            obj["especialidades"] = [e for e in m.specialties if str(e["especialidade_id"]) in {str(x) for x in v}]
        elif tipo == "profissionais" and k == "convenios":
            obj["convenios"] = [c for c in m.insurances if str(c["convenio_id"]) in {str(x) for x in v}]
        elif tipo == "profissionais" and k == "unidades":
            obj["unidades"] = [int(x) for x in v]
        elif tipo == "pacientes" and k == "celular":
            obj["celular"] = v
            obj["celulares"] = [v]
        elif tipo == "pacientes" and k == "cpf":
            obj["documentos"] = dict(obj.get("documentos") or {}, cpf=v)
        elif tipo == "bloqueios" and k in ("week_day", "units"):
            obj[k] = [str(x) for x in v]
        elif tipo == "planos" and k == "convenio_id":
            continue
        else:
            obj[k] = v


def atualizar(m, tipo, ident, campos):
    obj, _ = _achar(m, tipo, ident)
    if obj is None:
        raise Conflito("registro não encontrado")
    _aplicar(m, tipo, obj, campos)


def criar(m, tipo, campos):
    idf = ENTIDADES[tipo][0]
    if tipo == "unidades":
        novo = {"unidade_id": max(u["unidade_id"] for u in m.units) + 1, "nome_fantasia": "Nova unidade", "telefone_1": "",
                "bairro": "", "endereco": "", "numero": "", "cep": "", "razao_social": "", "cnpj": "", "cidade": "",
                "estado": "SC", "ExibirAgendamentoOnline": "1"}
        m.units.append(novo)
    elif tipo == "especialidades":
        novo = {"especialidade_id": max(e["especialidade_id"] for e in m.specialties) + 1, "nome": "Nova especialidade",
                "consulta_id": 1001, "consulta_online_id": 1003, "exibir_agendamento_online": 1, "codigo_tiss": ""}
        m.specialties.append(novo)
    elif tipo == "convenios":
        todos = m.insurances + m.hidden_insurances
        novo = {"convenio_id": max(i["convenio_id"] for i in todos if i["convenio_id"] < 290) + 1, "nome": "Novo convênio",
                "registro_ans": "", "planos": []}
        m.insurances.append(novo)
    elif tipo == "planos":
        conv = next((i for i in m.insurances if i["convenio_id"] == int(campos.get("convenio_id") or 0)), None)
        if conv is None:
            raise Conflito("informe convenio_id de um convênio existente")
        novo = {"plano_id": max([pl["plano_id"] for i in m.insurances for pl in i["planos"]] + [400]) + 1, "plano": "Novo plano"}
        conv["planos"].append(novo)
    elif tipo == "tabelas":
        novo = {"tabela_id": max(t["tabela_id"] for t in m.tables) + 1, "nome_tabela": "Nova tabela",
                "ExibirAgendamentoOnline": "1", "mult": 1.0}
        m.tables.append(novo)
    elif tipo == "procedimentos":
        novo = {"procedimento_id": max(p["procedimento_id"] for p in m.procedures) + 1, "nome": "Novo procedimento",
                "tipo_procedimento": 2, "preparo": None, "base": 10000}
        m.procedures.append(novo)
    elif tipo == "profissionais":
        novo = {"profissional_id": max(p["profissional_id"] for p in m.professionals) + 1, "nome": "Dr. Novo Profissional",
                "especialidades": m.specialties[:1], "convenios": m.insurances[:2], "sexo": "Masculino",
                "unidades": [m.units[0]["unidade_id"]], "ativo": True}
        m.professionals.append(novo)
    elif tipo == "pacientes":
        n = m.ids.next("patient", max(m.patients) + 1 if m.patients else 0)
        novo = {"paciente_id": n, "nome": "Novo Paciente", "nome_social": None, "sexo": "Feminino", "nascimento": "1990-01-01",
                "celulares": [f"554800{n:07d}"[:13]], "celular": f"554800{n:07d}"[:13], "email": f"paciente{n}@teste.invalid",
                "documentos": {"cpf": cpf_ficticio(f"{n:011d}")}}
        m.patients[n] = novo
    elif tipo == "bloqueios":
        n = max([b["id"] for b in m.blocks] + [0]) + 1
        hoje = date.today()
        novo = {"id": n, "date_start": hoje.isoformat(), "date_end": (hoje + timedelta(days=1)).isoformat(),
                "time_start": "08:00:00", "time_end": "18:00:00", "holiday_id": None,
                "professional_id": m.professionals[0]["profissional_id"], "description": "Bloqueio de teste",
                "week_day": [str(i) for i in range(1, 8)], "units": None}
        m.blocks.append(novo)
    else:
        raise ValueError(f"tipo de entidade desconhecido: {tipo}")
    _aplicar(m, tipo, novo, campos)
    return novo[idf] if tipo != "planos" else novo["plano_id"]


def remover(m, tipo, ident):
    obj, pai = _achar(m, tipo, ident)
    if obj is None:
        raise Conflito("registro não encontrado")
    if tipo == "unidades":
        raise ValueError("não é possível remover unidade (há agendamentos e profissionais vinculados)")
    if tipo == "especialidades":
        m.specialties.remove(obj)
        for p in m.professionals:
            p["especialidades"] = [e for e in p["especialidades"] if e is not obj]
    elif tipo == "convenios":
        m.insurances.remove(obj)
        for p in m.professionals:
            p["convenios"] = [c for c in p["convenios"] if c is not obj]
    elif tipo == "planos":
        pai["planos"].remove(obj)
    elif tipo == "tabelas":
        m.tables.remove(obj)
    elif tipo == "procedimentos":
        m.procedures.remove(obj)
    elif tipo == "profissionais":
        m.professionals.remove(obj)
    elif tipo == "pacientes":
        del m.patients[int(ident)]
    elif tipo == "bloqueios":
        m.blocks.remove(obj)


def _data(texto):
    texto = str(texto).split(" ")[0]
    for f in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, f).date()
        except ValueError:
            pass
    raise ValueError(f"data inválida: {texto}")


def _hora(texto):
    texto = str(texto)
    return texto if texto.count(":") == 2 else texto + ":00"


def _parse_valor(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return f"R$ {br(float(v))}"
    return str(v)


def valor_para_numero(texto):
    """Valor do ERP em texto para o número com 2 casas que [[o_cliente]] grava (ou None se ela descartaria)."""
    if texto in (None, ""):
        return None
    if isinstance(texto, (int, float)):
        n = float(texto)
    else:
        t = "".join(c for c in str(texto) if c.isdigit() or c in ",.-")
        if not t:
            return None
        vc, vp = t.rfind(","), t.rfind(".")
        if vc >= 0 and vp >= 0:
            t = t.replace(".", "").replace(",", ".") if vc > vp else t.replace(",", "")
        elif vc >= 0:
            t = t.replace(",", ".")
        try:
            n = float(t)
        except ValueError:
            return None
    return f"{n:.2f}" if 0 < n <= 99999.99 else None


def acao(m, sid, nome, **p):
    s = m.schedules.get(int(sid))
    if s is None:
        raise Conflito("Agendamento não existe")
    if nome in STATUS_POR_ACAO:
        s["status_id"] = STATUS_POR_ACAO[nome]
    elif nome == "remarcar":
        d = _data(p["data"]) if p.get("data") else sdate(s)
        h = _hora(p["horario"]) if p.get("horario") else s["horario"]
        s["abs_date"], s["horario"], s["status_id"] = d, h, 1
    elif nome == "trocar_profissional":
        prof = next((x for x in m.professionals if x["profissional_id"] == int(p["profissional_id"])), None)
        if prof is None:
            raise Conflito("Profissional não encontrado")
        s["profissional_id"] = prof["profissional_id"]
        if prof["especialidades"]:
            s["especialidade_id"] = prof["especialidades"][0]["especialidade_id"]
    elif nome == "trocar_convenio":
        c = p.get("convenio_id")
        if c in (None, "", "particular"):
            s.update(convenio_id=None, plano_id=None, tabela_id=s.get("tabela_id") or 1)
        else:
            s.update(convenio_id=int(c), plano_id=None, tabela_id=None)
    elif nome == "trocar_procedimento":
        if not any(x["procedimento_id"] == int(p["procedimento_id"]) for x in m.procedures):
            raise Conflito("Procedimento não encontrado")
        s["procedimento_id"] = int(p["procedimento_id"])
        s["procedimentos"] = [{"procedimentoID": s["procedimento_id"], "valor": 0}]
    elif nome == "definir_valor":
        s["valor_total_agendamento"] = _parse_valor(p.get("valor"))
    elif nome == "sumir":
        del m.schedules[int(sid)]
        return None
    else:
        raise ValueError(f"ação desconhecida: {nome}")
    return m.schedule_json(s, True)


def criar_agendamento(m, spec):
    pac = spec.get("paciente_id")
    if not pac:
        novo = spec.get("paciente") or {}
        n = m.ids.next("patient", max(m.patients) + 1 if m.patients else 0)
        cel = novo.get("celular") or f"554800{n:07d}"[:13]
        m.patients[n] = {"paciente_id": n, "nome": novo.get("nome") or f"Paciente Teste {n}", "nome_social": None,
                         "sexo": novo.get("sexo") or "Feminino", "nascimento": novo.get("nascimento") or "1990-01-01",
                         "celulares": [cel], "celular": cel, "email": novo.get("email") or f"paciente{n}@teste.invalid",
                         "documentos": {"cpf": novo.get("cpf") or cpf_ficticio(f"{n:011d}")}}
        pac = n
    prof = next((x for x in m.professionals if x["profissional_id"] == int(spec["profissional_id"])), None)
    if prof is None:
        raise Conflito("Profissional não encontrado")
    if not any(x["procedimento_id"] == int(spec["procedimento_id"]) for x in m.procedures):
        raise Conflito("Procedimento não encontrado")
    if spec.get("em_horas") not in (None, ""):
        alvo = datetime.now() + timedelta(hours=float(spec["em_horas"]))
        d, h = alvo.date(), alvo.strftime("%H:%M:00")
    else:
        d, h = _data(spec["data"]), _hora(spec["horario"])
    if m.slot_taken(prof["profissional_id"], d, h):
        raise Conflito("Horário ocupado")
    unidade = int(spec.get("unidade_id") or prof["unidades"][0])
    conv = spec.get("convenio_id")
    conv = None if conv in (None, "", "particular") else int(conv)
    esp = spec.get("especialidade_id") or (prof["especialidades"][0]["especialidade_id"] if prof["especialidades"] else None)
    sid = m.ids.next("schedule", max(m.schedules) + 1 if m.schedules else 0)
    m.schedules[sid] = {
        "agendamento_id": sid, "abs_date": d, "day_offset": 0, "horario": h, "unidade_id": unidade,
        "profissional_id": prof["profissional_id"], "procedimento_id": int(spec["procedimento_id"]),
        "paciente_id": int(pac), "status_id": int(spec.get("status_id") or 1), "convenio_id": conv, "plano_id": None,
        "tabela_id": None if conv else int(spec.get("tabela_id") or 1),
        "especialidade_id": int(esp) if esp else None, "valor_total_agendamento": _parse_valor(spec.get("valor")),
        "procedimentos": [{"procedimentoID": int(spec["procedimento_id"]), "valor": 0}], "scenario": "criado_no_painel"}
    return m.schedule_json(m.schedules[sid], True)


def buscar_agendamentos(m, q="", cenario=None, unidade_id=None, profissional_id=None, status_id=None, dia=None,
                         limite=20, inicio=0):
    prof = {p["profissional_id"]: p["nome"] for p in m.professionals}
    proc = {p["procedimento_id"]: p["nome"] for p in m.procedures}
    conv = {i["convenio_id"]: i["nome"] for i in m.insurances + m.hidden_insurances}
    tab = {t["tabela_id"]: t["nome_tabela"] for t in m.tables}
    from .model import STATUSES
    st = dict(STATUSES)
    out = []
    for s in m.schedules.values():
        if cenario and s["scenario"] != cenario:
            continue
        if unidade_id and s["unidade_id"] != int(unidade_id):
            continue
        if profissional_id and s["profissional_id"] != int(profissional_id):
            continue
        if status_id and s["status_id"] != int(status_id):
            continue
        if dia and sdate(s).isoformat() != dia:
            continue
        pac = m.patients.get(s["paciente_id"]) or {"nome": f"Paciente {s['paciente_id']}", "celular": ""}
        linha = {"agendamento_id": s["agendamento_id"], "data": sdate(s).isoformat(), "horario": s["horario"],
                 "unidade_id": s["unidade_id"], "profissional_id": s["profissional_id"],
                 "profissional": prof.get(s["profissional_id"], "?"), "procedimento_id": s["procedimento_id"],
                 "procedimento": proc.get(s["procedimento_id"], "?"), "paciente_id": s["paciente_id"],
                 "paciente": pac["nome"], "celular": pac.get("celular"),
                 "convenio_id": s["convenio_id"],
                 "convenio": conv.get(s["convenio_id"], "?") if s["convenio_id"] else tab.get(s["tabela_id"], "Particular"),
                 "valor": s["valor_total_agendamento"], "status_id": s["status_id"], "status": st.get(s["status_id"], "?"),
                 "cenario": s["scenario"]}
        if q and q.lower() not in json.dumps(linha, ensure_ascii=False, default=str).lower():
            continue
        out.append(linha)
    out.sort(key=lambda x: (x["data"], x["horario"], x["agendamento_id"]))
    return {"total": len(out), "linhas": out[inicio:inicio + limite], "acoes": ACOES}


def horarios_da_agenda(m, profissional_id, unidade_id, dias=7):
    """Grade do profissional na unidade: horários livres e ocupados (com o agendamento que ocupa)."""
    from datetime import date, timedelta
    prof = next((p for p in m.professionals if p["profissional_id"] == int(profissional_id)), None)
    if not prof:
        raise Conflito("Profissional não encontrado.")
    unidade_id = int(unidade_id)
    dias = max(1, min(int(dias), 31))
    primeiro = date.today()
    ultimo = primeiro + timedelta(days=dias - 1)
    livres = m.free_slots(prof, unidade_id, primeiro, ultimo)
    ocupados = {}
    for s in m.schedules.values():
        d = sdate(s)
        if s["profissional_id"] == prof["profissional_id"] and primeiro <= d <= ultimo and s["status_id"] not in (11, 15, 16):
            pac = m.patients.get(s["paciente_id"], {})
            ocupados.setdefault(d.isoformat(), []).append(
                {"horario": s["horario"][:5], "agendamento_id": s["agendamento_id"], "paciente": pac.get("nome")})
    out, d = [], primeiro
    while d <= ultimo:
        k = d.isoformat()
        if d.weekday() < 5:
            out.append({"data": k, "livres": [h[:5] for h in livres.get(k, [])],
                        "ocupados": sorted(ocupados.get(k, []), key=lambda x: x["horario"])})
        d += timedelta(days=1)
    return {"profissional": prof["nome"], "unidade_id": unidade_id, "dias": out,
            "atende_na_unidade": unidade_id in prof["unidades"]}
