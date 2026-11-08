"""Volume e importação de dados: gerar mais registros, importar CSV ou JSON (inclusive gerado por IA) e exportar.

Regras de segurança dos dados fictícios, valem na geração e na importação:
- telefone sempre no padrão inexistente 554800 + 7 dígitos (a importação recusa outros, salvo permissão explícita);
- CPF gerado é fictício com dígitos verificadores corretos; CPF informado é conferido só no formato;
- e-mail gerado usa o domínio @teste.invalid.
"""
import copy
import csv
import io
import json
import random
import re
from datetime import date, datetime

from . import ops
from .idstore import IdStore
from .model import (FIRST_F, FIRST_M, LAST, SCENARIOS, Conflito, Model, cpf_ficticio, cpf_valido, sdate)

LIMITES = {"pacientes": 100000, "profissionais": 500, "agendamentos": 100000, "unidades": 20}
ENTIDADES = ["unidades", "especialidades", "convenios", "procedimentos", "profissionais", "pacientes", "agendamentos"]
CAMPOS = {
    "unidades": (["nome_fantasia"], ["id", "nome_fantasia", "telefone_1", "endereco", "numero", "bairro", "cidade", "estado", "cep", "cnpj", "razao_social"]),
    "especialidades": (["nome"], ["id", "nome", "codigo_tiss"]),
    "convenios": (["nome"], ["id", "nome", "registro_ans", "planos"]),
    "procedimentos": (["nome"], ["id", "nome", "tipo", "valor", "preparo"]),
    "profissionais": (["nome", "unidades"], ["id", "nome", "sexo", "unidades", "especialidades", "convenios"]),
    "pacientes": (["nome"], ["id", "nome", "nascimento", "sexo", "celular", "email", "cpf"]),
    "agendamentos": (["paciente", "profissional", "procedimento", "data", "horario"],
                     ["id", "paciente", "profissional", "procedimento", "unidade", "data", "horario", "convenio", "valor", "status_id"]),
}
EXEMPLOS = {
    "unidades": [{"nome_fantasia": "Clínica Exemplo Centro", "telefone_1": "(48) 0000-0001", "cidade": "Florianópolis", "estado": "SC", "bairro": "Centro"}],
    "especialidades": [{"nome": "Reumatologia", "codigo_tiss": "22501"}],
    "convenios": [{"nome": "Convênio Exemplo", "registro_ans": "340001", "planos": "Básico|Plus|Premium"}],
    "procedimentos": [{"nome": "Consulta Reumatológica", "tipo": "consulta", "valor": "250,00", "preparo": ""},
                      {"nome": "Densitometria Óssea", "tipo": "exame", "valor": "180,00", "preparo": "Sem preparo"}],
    "profissionais": [{"nome": "Dra. Ana Exemplo", "sexo": "F", "unidades": "Clínica Exemplo Centro", "especialidades": "Reumatologia",
                       "convenios": "Convênio Exemplo"}],
    "pacientes": [{"nome": "Maria Exemplo da Silva", "nascimento": "1985-03-21", "sexo": "F", "celular": "5548000000001",
                   "email": "maria.exemplo@teste.invalid", "cpf": ""}],
    "agendamentos": [{"paciente": "Maria Exemplo da Silva", "profissional": "Dra. Ana Exemplo", "procedimento": "Consulta Reumatológica",
                      "unidade": "Clínica Exemplo Centro", "data": "2026-11-03", "horario": "10:20", "convenio": "", "valor": "250,00"}],
}


def celular_seguro(texto):
    return bool(re.fullmatch(r"554800\d{7}", re.sub(r"\D", "", str(texto or ""))))


def _prox(m, lista, chave, piso=0):
    return max([x[chave] for x in lista] + [piso]) + 1


def _nome_unico(prof_nomes, rnd, homem):
    base = f"{'Dr.' if homem else 'Dra.'} {rnd.choice(FIRST_M if homem else FIRST_F)} {rnd.choice(LAST)}"
    nome, k = base, 0
    while nome in prof_nomes:
        nome = base + " " + LAST[k % len(LAST)]
        k += 1
    prof_nomes.add(nome)
    return nome


# ----- volume -----
def acrescentar_volume(m, pacientes=0, profissionais=0, agendamentos=0, dias=14, semente=None):
    """Acrescenta registros ao modelo atual, com ids novos e permanentes. Devolve quanto foi criado."""
    for chave, n in (("pacientes", pacientes), ("profissionais", profissionais), ("agendamentos", agendamentos)):
        if n < 0 or n > LIMITES[chave]:
            raise ValueError(f"{chave}: informe de 0 a {LIMITES[chave]}")
    dias = max(1, min(int(dias), 365))
    rnd = random.Random(semente if semente not in (None, "") else datetime.now().timestamp())
    feito = {"pacientes": 0, "profissionais": 0, "agendamentos": 0}
    nomes = {p["nome"] for p in m.professionals}
    if profissionais and not (m.units and m.specialties and m.insurances):
        raise ValueError("Para gerar profissionais é preciso haver unidades, especialidades e convênios")
    for i in range(profissionais):
        homem = rnd.random() < .5
        m.professionals.append({
            "profissional_id": _prox(m, m.professionals, "profissional_id", 2000),
            "nome": _nome_unico(nomes, rnd, homem), "especialidades": rnd.sample(m.specialties, min(len(m.specialties), 1 + i % 2)),
            "convenios": rnd.sample(m.insurances, min(len(m.insurances), 3 + i % 4)), "sexo": "Masculino" if homem else "Feminino",
            "unidades": rnd.sample([u["unidade_id"] for u in m.units], min(len(m.units), 1 + i % len(m.units))), "ativo": True})
        feito["profissionais"] += 1
    ultimo = max(m.patients) if m.patients else 0
    for _ in range(pacientes):
        n = m.ids.next("patient", ultimo + 1)
        ultimo = n
        homem = rnd.random() < .45
        cel = f"554800{n:07d}"[:13]
        m.patients[n] = {
            "paciente_id": n, "nome": f"{rnd.choice(FIRST_M if homem else FIRST_F)} {rnd.choice(LAST)} {rnd.choice(LAST)}",
            "nome_social": None, "sexo": "Masculino" if homem else "Feminino",
            "nascimento": f"{rnd.randint(1948, 2018)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
            "celulares": [cel], "celular": cel, "email": f"paciente{n}@teste.invalid",
            "documentos": {"cpf": cpf_ficticio("".join(str(rnd.randint(0, 9)) for _ in range(11)))}}
        feito["pacientes"] += 1
    if agendamentos:
        if not (m.patients and m.professionals and m.procedures and m.units):
            raise ValueError("Para gerar agendamentos é preciso haver pacientes, profissionais, procedimentos e unidades")
        nomes_cen = [s for s, _ in SCENARIOS]
        pesos = [w for _, w in SCENARIOS]
        pids = list(m.patients)
        dias_antes, m.days = m.days, dias
        ultimo = max(m.schedules) if m.schedules else 0
        try:
            for i in range(agendamentos):
                sid = m.ids.next("schedule", ultimo + 1)
                ultimo = sid
                m._make_schedule(i, rnd, rnd.choices(nomes_cen, pesos)[0], sid=sid, pids=pids)
                feito["agendamentos"] += 1
        finally:
            m.days = dias_antes
    return feito


# ----- exportar -----
def exportar(m):
    def lista(chaves, objs):
        return [{k: o.get(k) for k in chaves} for o in objs]
    return {
        "formato": "erp-fakes/1",
        "unidades": [{"id": u["unidade_id"], **{k: u.get(k) for k in CAMPOS["unidades"][1][1:]}} for u in m.units],
        "especialidades": [{"id": e["especialidade_id"], "nome": e["nome"], "codigo_tiss": e.get("codigo_tiss")} for e in m.specialties],
        "convenios": [{"id": i["convenio_id"], "nome": i["nome"], "registro_ans": i.get("registro_ans"),
                       "planos": "|".join(pl["plano"].removeprefix(i["nome"]).strip() for pl in i["planos"])} for i in m.insurances],
        "procedimentos": [{"id": p["procedimento_id"], "nome": p["nome"], "tipo": "consulta" if p["tipo_procedimento"] == 1 else "exame",
                           "valor": f"{p['base'] / 100:.2f}", "preparo": p.get("preparo")} for p in m.procedures],
        "profissionais": [{"id": p["profissional_id"], "nome": p["nome"], "sexo": p["sexo"][0], "unidades": "|".join(map(str, p["unidades"])),
                           "especialidades": "|".join(str(e["especialidade_id"]) for e in p["especialidades"]),
                           "convenios": "|".join(str(c["convenio_id"]) for c in p["convenios"])} for p in m.professionals],
        "pacientes": [{"id": p["paciente_id"], "nome": p["nome"], "nascimento": p.get("nascimento"), "sexo": (p.get("sexo") or "?")[0],
                       "celular": p.get("celular"), "email": p.get("email"), "cpf": p["documentos"].get("cpf")} for p in m.patients.values()],
        "agendamentos": [{"id": s["agendamento_id"], "paciente": s["paciente_id"], "profissional": s["profissional_id"],
                          "procedimento": s["procedimento_id"], "unidade": s["unidade_id"], "data": sdate(s).isoformat(),
                          "horario": s["horario"][:5], "convenio": s["convenio_id"] or "", "valor": s["valor_total_agendamento"] or "",
                          "status_id": s["status_id"]} for s in m.schedules.values()],
    }


# ----- importar -----
def _linhas_csv(texto):
    texto = texto.strip("﻿\n\r ")
    if not texto:
        return []
    try:
        dialeto = csv.Sniffer().sniff(texto.splitlines()[0], delimiters=",;\t")
    except csv.Error:
        dialeto = csv.excel
    leitor = csv.DictReader(io.StringIO(texto), dialect=dialeto)
    saida = []
    for linha in leitor:
        extra = linha.pop(None, None)
        limpa = {(k or "").strip().lower(): (v or "").strip() if isinstance(v, str) or v is None else "" for k, v in linha.items()}
        if extra:
            limpa["__erro__"] = "a linha tem mais colunas que o cabeçalho (valores com vírgula precisam de aspas)"
        saida.append(limpa)
    return saida


def interpretar(texto, formato, entidade=None):
    """Devolve {entidade: [linhas]} a partir de JSON (objeto por entidade, ou lista com `entidade`) ou CSV (precisa de `entidade`)."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Cole o conteúdo a importar")
    if formato == "auto":
        formato = "json" if texto[:1] in "[{" else "csv"
    if formato == "csv":
        if entidade not in ENTIDADES:
            raise ValueError("Para CSV escolha a entidade")
        return {entidade: _linhas_csv(texto)}
    try:
        dados = json.loads(texto)
    except ValueError as e:
        raise ValueError(f"JSON inválido: {e}")
    if isinstance(dados, list):
        if entidade not in ENTIDADES:
            raise ValueError("Para uma lista JSON escolha a entidade")
        return {entidade: dados}
    if not isinstance(dados, dict):
        raise ValueError("O JSON precisa ser um objeto com listas por entidade, ou uma lista")
    desconhecidas = [k for k in dados if k not in ENTIDADES and k != "formato"]
    if desconhecidas:
        raise ValueError(f"Entidades desconhecidas: {', '.join(desconhecidas)}. Use: {', '.join(ENTIDADES)}")
    return {k: v for k, v in dados.items() if k in ENTIDADES}


def _lista(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v or "").split("|") if x.strip()]


def _achar(lista, chave, nome_chave, ref, rotulo):
    ref = str(ref).strip()
    for o in lista:
        if str(o[chave]) == ref or str(o[nome_chave]).lower() == ref.lower():
            return o
    raise ValueError(f"{rotulo} não encontrado: '{ref}'")


def _data(texto):
    t = str(texto).strip().replace("/", "-")
    for f in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    raise ValueError(f"data inválida: '{texto}' (use AAAA-MM-DD ou DD/MM/AAAA)")


def _valor_centavos(texto):
    n = ops.valor_para_numero(texto)
    if n is None:
        raise ValueError(f"valor inválido: '{texto}'")
    return int(round(float(n) * 100))


def modelo_vazio(m):
    for nome in ("units", "specialties", "insurances", "hidden_insurances", "procedures", "professionals", "blocks"):
        setattr(m, nome, [])
    m.patients, m.schedules = {}, {}
    m.no_price_table2 = set()


def _livre(existentes, ident, chave, rotulo):
    if ident not in (None, ""):
        ident = int(ident)
        if any(x[chave] == ident for x in existentes):
            raise ValueError(f"{rotulo} com id {ident} já existe")
        return ident
    return None


def _importa_linha(m, entidade, r, permitir_telefone_real, avisos):
    ident = r.get("id")
    if entidade == "unidades":
        if not str(r.get("nome_fantasia", "")).strip():
            raise ValueError("nome_fantasia é obrigatório")
        uid = _livre(m.units, ident, "unidade_id", "Unidade") or _prox(m, m.units, "unidade_id", 100)
        m.units.append({"unidade_id": uid, "nome_fantasia": r["nome_fantasia"].strip(), "telefone_1": r.get("telefone_1") or "",
                        "bairro": r.get("bairro") or "", "endereco": r.get("endereco") or "", "numero": str(r.get("numero") or ""),
                        "cep": r.get("cep") or "", "razao_social": r.get("razao_social") or r["nome_fantasia"].strip(),
                        "cnpj": r.get("cnpj") or "", "cidade": r.get("cidade") or "", "estado": r.get("estado") or "SC",
                        "ExibirAgendamentoOnline": "1"})
    elif entidade == "especialidades":
        if not str(r.get("nome", "")).strip():
            raise ValueError("nome é obrigatório")
        eid = _livre(m.specialties, ident, "especialidade_id", "Especialidade") or _prox(m, m.specialties, "especialidade_id")
        m.specialties.append({"especialidade_id": eid, "nome": r["nome"].strip(), "consulta_id": 1001, "consulta_online_id": 1003,
                              "exibir_agendamento_online": 1, "codigo_tiss": r.get("codigo_tiss") or ""})
    elif entidade == "convenios":
        if not str(r.get("nome", "")).strip():
            raise ValueError("nome é obrigatório")
        todos = m.insurances + m.hidden_insurances
        cid = _livre(todos, ident, "convenio_id", "Convênio") or max([i["convenio_id"] for i in todos if i["convenio_id"] < 290] + [200]) + 1
        pid = max([pl["plano_id"] for i in todos for pl in i["planos"]] + [400])
        planos = []
        for nome in _lista(r.get("planos")):
            pid += 1
            planos.append({"plano_id": pid, "plano": f"{r['nome'].strip()} {nome}"})
        m.insurances.append({"convenio_id": cid, "nome": r["nome"].strip(), "registro_ans": r.get("registro_ans") or "", "planos": planos})
    elif entidade == "procedimentos":
        if not str(r.get("nome", "")).strip():
            raise ValueError("nome é obrigatório")
        tipo = 2 if str(r.get("tipo", "consulta")).strip().lower() in ("2", "exame") else 1
        pid = _livre(m.procedures, ident, "procedimento_id", "Procedimento") or _prox(m, m.procedures, "procedimento_id", 1000)
        base = _valor_centavos(r["valor"]) if str(r.get("valor", "")).strip() else 10000
        m.procedures.append({"procedimento_id": pid, "nome": r["nome"].strip(), "tipo_procedimento": tipo,
                             "preparo": r.get("preparo") or None, "base": base})
    elif entidade == "profissionais":
        if not str(r.get("nome", "")).strip():
            raise ValueError("nome é obrigatório")
        unidades = [_achar(m.units, "unidade_id", "nome_fantasia", x, "Unidade")["unidade_id"] for x in _lista(r.get("unidades"))]
        if not unidades:
            raise ValueError("unidades é obrigatório (id ou nome, separados por |)")
        esps = [_achar(m.specialties, "especialidade_id", "nome", x, "Especialidade") for x in _lista(r.get("especialidades"))]
        convs = [_achar(m.insurances, "convenio_id", "nome", x, "Convênio") for x in _lista(r.get("convenios"))]
        pid = _livre(m.professionals, ident, "profissional_id", "Profissional") or _prox(m, m.professionals, "profissional_id", 2000)
        m.professionals.append({"profissional_id": pid, "nome": r["nome"].strip(), "especialidades": esps, "convenios": convs,
                                "sexo": "Masculino" if str(r.get("sexo", "F")).strip().lower().startswith("m") else "Feminino",
                                "unidades": unidades, "ativo": True})
    elif entidade == "pacientes":
        if not str(r.get("nome", "")).strip():
            raise ValueError("nome é obrigatório")
        if ident not in (None, ""):
            n = int(ident)
            if n in m.patients:
                raise ValueError(f"Paciente com id {n} já existe")
        else:
            n = m.ids.next("patient", max(m.patients) + 1 if m.patients else 0)
        cel = re.sub(r"\D", "", str(r.get("celular") or ""))
        if cel and not celular_seguro(cel) and not permitir_telefone_real:
            raise ValueError(f"celular '{r.get('celular')}' fora do padrão seguro 554800 + 7 dígitos (marque a permissão para usar telefone real)")
        cel = cel or f"554800{n:07d}"[:13]
        cpf = re.sub(r"\D", "", str(r.get("cpf") or ""))
        if cpf and len(cpf) != 11:
            raise ValueError(f"cpf '{r.get('cpf')}' deve ter 11 dígitos")
        if cpf and cpf_valido(cpf):
            avisos.add("CPF informado passa na validação oficial: confira que não é de pessoa real.")
        nasc = r.get("nascimento") or "1990-01-01"
        try:
            nasc = _data(nasc).isoformat()
        except ValueError:
            raise ValueError(f"nascimento inválido: '{nasc}'")
        m.patients[n] = {"paciente_id": n, "nome": r["nome"].strip(), "nome_social": None,
                         "sexo": "Masculino" if str(r.get("sexo", "F")).strip().lower().startswith("m") else "Feminino",
                         "nascimento": nasc, "celulares": [cel], "celular": cel,
                         "email": r.get("email") or f"paciente{n}@teste.invalid",
                         "documentos": {"cpf": cpf or cpf_ficticio(f"{n:011d}")}}
    elif entidade == "agendamentos":
        pac = next((p for p in m.patients.values() if str(p["paciente_id"]) == str(r.get("paciente")).strip()
                    or p["nome"].lower() == str(r.get("paciente")).strip().lower()
                    or re.sub(r"\D", "", p["documentos"].get("cpf") or "") == re.sub(r"\D", "", str(r.get("paciente")))), None)
        if pac is None:
            raise ValueError(f"Paciente não encontrado: '{r.get('paciente')}'")
        prof = _achar(m.professionals, "profissional_id", "nome", r.get("profissional"), "Profissional")
        proc = _achar(m.procedures, "procedimento_id", "nome", r.get("procedimento"), "Procedimento")
        unidade = _achar(m.units, "unidade_id", "nome_fantasia", r["unidade"], "Unidade")["unidade_id"] if str(r.get("unidade", "")).strip() \
            else prof["unidades"][0]
        conv = _achar(m.insurances, "convenio_id", "nome", r["convenio"], "Convênio")["convenio_id"] if str(r.get("convenio", "")).strip() else None
        d = _data(r["data"])
        hora = str(r["horario"]).strip()
        if not re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", hora):
            raise ValueError(f"horario inválido: '{hora}' (use HH:MM)")
        novo = ops.criar_agendamento(m, {"profissional_id": prof["profissional_id"], "procedimento_id": proc["procedimento_id"],
                                         "unidade_id": unidade, "convenio_id": conv, "paciente_id": pac["paciente_id"],
                                         "data": d.isoformat(), "horario": hora if hora.count(":") == 2 else hora + ":00",
                                         "valor": r.get("valor") or None, "status_id": r.get("status_id") or 1})
        sid = novo["agendamento_id"]
        s = m.schedules[sid]
        s["scenario"] = "importado"
        if ident not in (None, ""):
            novo_id = int(ident)
            if novo_id in m.schedules:
                del m.schedules[sid]
                raise ValueError(f"Agendamento com id {novo_id} já existe")
            s["agendamento_id"] = novo_id
            m.schedules[novo_id] = m.schedules.pop(sid)
    else:
        raise ValueError(f"entidade desconhecida: {entidade}")


def importar(m, texto, formato="auto", entidade=None, modo="acrescentar", permitir_telefone_real=False, simular=True):
    """Importa dados. Com simular=True nada muda no modelo: roda numa cópia e devolve o relatório."""
    if modo not in ("acrescentar", "substituir"):
        raise ValueError("modo deve ser acrescentar ou substituir")
    conjunto = interpretar(texto, formato, entidade)
    alvo = m
    if simular:
        original = m.ids
        m.ids = None
        try:
            alvo = copy.deepcopy(m)
        finally:
            m.ids = original
        alvo.ids = IdStore()
    if modo == "substituir":
        modelo_vazio(alvo)
    criados, erros, avisos = {}, [], set()
    for ent in ENTIDADES:
        linhas = conjunto.get(ent) or []
        criados[ent] = 0
        obrig, aceitos = CAMPOS[ent]
        for i, linha in enumerate(linhas, 1):
            if not isinstance(linha, dict):
                erros.append({"entidade": ent, "linha": i, "mensagem": "cada linha precisa ser um objeto"})
                continue
            linha = {str(k).strip().lower(): v for k, v in linha.items()}
            if linha.get("__erro__"):
                erros.append({"entidade": ent, "linha": i, "mensagem": linha["__erro__"]})
                continue
            if ent == "agendamentos" and "status_id" not in linha:
                linha["status_id"] = 1
            falta = [c for c in obrig if str(linha.get(c, "")).strip() == ""]
            if falta:
                erros.append({"entidade": ent, "linha": i, "mensagem": f"faltam campos obrigatórios: {', '.join(falta)}"})
                continue
            try:
                _importa_linha(alvo, ent, linha, permitir_telefone_real, avisos)
                criados[ent] += 1
            except (Conflito, ValueError, KeyError, TypeError, StopIteration) as e:
                erros.append({"entidade": ent, "linha": i, "mensagem": str(e) if not isinstance(e, KeyError) else f"campo ausente: {e}"})
    return {"simulado": simular, "modo": modo, "criados": criados, "erros": erros[:200], "total_erros": len(erros),
            "avisos": sorted(avisos),
            "totais": {"unidades": len(alvo.units), "especialidades": len(alvo.specialties), "convenios": len(alvo.insurances),
                       "procedimentos": len(alvo.procedures), "profissionais": len(alvo.professionals),
                       "pacientes": len(alvo.patients), "agendamentos": len(alvo.schedules)}}


def _csv(colunas, linhas):
    saida = io.StringIO()
    w = csv.writer(saida, lineterminator="\n")
    w.writerow(colunas)
    for l in linhas:
        w.writerow([l.get(c, "") for c in colunas])
    return saida.getvalue().rstrip("\n")


# ----- modelos e prompt para IA -----
def modelos():
    ents = {}
    for ent in ENTIDADES:
        obrig, aceitos = CAMPOS[ent]
        exemplo = EXEMPLOS[ent]
        ents[ent] = {"obrigatorios": obrig, "colunas": aceitos, "exemplo": exemplo,
                     "csv": _csv(aceitos, exemplo)}
    prompt = (
        "Gere dados FICTÍCIOS para popular um ERP de teste da clínica, em JSON, sem texto fora do JSON.\n"
        "Formato: um objeto com listas, nesta ordem de dependência: unidades, especialidades, convenios, procedimentos, "
        "profissionais, pacientes, agendamentos.\n"
        "Colunas por entidade (* = obrigatória):\n"
        + "\n".join(f"- {e}: " + ", ".join(("*" + c if c in CAMPOS[e][0] else c) for c in CAMPOS[e][1]) for e in ENTIDADES) + "\n"
        "Regras:\n"
        "- Listas dentro de uma coluna (unidades, especialidades, convenios, planos) vão separadas por | e usam o nome exato já definido acima.\n"
        "- Telefone (celular): sempre 554800 seguido de 7 dígitos, por exemplo 5548000000123. Nunca use telefone real.\n"
        "- CPF: deixe vazio, o sistema gera um CPF fictício válido.\n"
        "- E-mail: use o domínio @teste.invalid.\n"
        "- Nomes de pessoas inventados e sem relação com pessoas reais conhecidas.\n"
        "- procedimentos.tipo: consulta ou exame. valor em reais, ex. 250,00.\n"
        "- agendamentos: data AAAA-MM-DD no futuro, horario HH:MM em múltiplos de 20 minutos, sem dois agendamentos do mesmo profissional no mesmo horário; "
        "paciente, profissional, procedimento e unidade pelo nome exato.\n"
        "Quantidade desejada: <PREENCHA, por exemplo 5 unidades, 12 profissionais, 200 pacientes, 400 agendamentos>.\n"
        "Exemplo de uma linha de paciente: " + json.dumps(EXEMPLOS["pacientes"][0], ensure_ascii=False))
    return {"entidades": ents, "prompt": prompt, "limites": LIMITES}
