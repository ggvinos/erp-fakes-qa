"""Roteiros: receitas que mudam o ERP, dizem o que [[o_cliente]] deve gravar e conferem o resultado.

Um roteiro tem passos (o que acontece no ERP) e verificações (o que se espera no cliente depois da carga).
Os roteiros vêm do perfil ativo (ver perfil.py). Executar muda o fake e devolve a lista de IDs externos afetados,
a consulta para rodar no banco do cliente e as verificações já com os valores esperados. Depois da carga,
avaliar() compara com o resultado colado do banco.
"""
from datetime import date, timedelta

from . import ops, perfil
from .model import Conflito, sdate

STATUS_FORA = (2, 3, 4, 6, 11, 15, 16)
TODOS_ERPS = ("feegow", "netpacs", "tasy")


def _roteiros():
    return perfil.ativo().roteiros


def listar(erp="feegow"):
    return [{k: r[k] for k in ("id", "titulo", "card", "descricao")} | {"passos": len(r["passos"])}
            for r in _roteiros() if erp in r.get("erps", TODOS_ERPS)]


def _escolher(m, cenario, janela, usados, status_ids=None):
    hoje = date.today()
    ini, fim = hoje + timedelta(days=janela[0]), hoje + timedelta(days=janela[1])
    for s in m.schedules.values():
        if s["scenario"] == cenario and s["agendamento_id"] not in usados and not m.ids.ja_usado(s["agendamento_id"]) \
                and ini <= sdate(s) <= fim \
                and s["status_id"] not in STATUS_FORA and (status_ids is None or s["status_id"] in status_ids):
            return s
    raise Conflito(f"Não há agendamento ainda não usado do cenário '{cenario}' na janela de {janela[0]} a {janela[1]} dias. "
                   "Os roteiros não repetem agendamentos que [[o_cliente]] já alterou. Use 'Esquecer agendamentos usados' "
                   "(se a conta de teste foi limpa) ou aumente --schedules e --days.")


def executar(m, roteiro_id, erp="feegow"):
    roteiro = next((r for r in _roteiros() if r["id"] == roteiro_id), None)
    if roteiro is None or erp not in roteiro.get("erps", TODOS_ERPS):
        raise Conflito(f"Roteiro não encontrado para este ERP: {roteiro_id}")
    alvos, usados, feito, contexto = {}, set(), [], {}
    conv_nome = {i["convenio_id"]: i["nome"] for i in m.insurances + m.hidden_insurances}
    for passo in roteiro["passos"]:
        if "escolher" in passo:
            s = _escolher(m, passo["cenario"], roteiro["janela_dias"], usados, passo.get("status_ids"))
            alvos[passo["escolher"]] = s["agendamento_id"]
            usados.add(s["agendamento_id"])
            feito.append(f"Escolhido o agendamento {s['agendamento_id']} (cenário {passo['cenario']})")
            continue
        if "criar" in passo:
            prof = next(p for p in m.professionals if p["ativo"])
            livre = None
            for dias in range(passo["em_dias"], passo["em_dias"] + 5):
                d = date.today() + timedelta(days=dias)
                for h in range(9, 18):
                    if d.weekday() < 5 and not m.slot_taken(prof["profissional_id"], d, f"{h:02d}:00:00"):
                        livre = (d, f"{h:02d}:00:00")
                        break
                if livre:
                    break
            novo = ops.criar_agendamento(m, {
                "profissional_id": prof["profissional_id"], "procedimento_id": m.procedures[0]["procedimento_id"],
                "unidade_id": prof["unidades"][0], "data": livre[0].isoformat(), "horario": livre[1],
                "valor": passo["valor"], "paciente": {"nome": "Paciente do roteiro"}})
            alvos[passo["criar"]] = novo["agendamento_id"]
            feito.append(passo["texto"] + f" (ID externo {novo['agendamento_id']})")
            continue
        sid = alvos[passo["alvo"]]
        s = m.schedules[sid]
        if passo["acao"] == "sincronizar_convenio":
            cid = s["convenio_id"]
            oculto = next((i for i in m.hidden_insurances if i["convenio_id"] == cid), None)
            if oculto:
                m.hidden_insurances.remove(oculto)
                m.insurances.append(oculto)
            contexto["valor_de_" + passo["alvo"]] = ops.valor_para_numero(s["valor_total_agendamento"])
            feito.append(f"{passo['texto']} (convênio {cid}, agendamento {sid})")
            continue
        params = {k: v for k, v in passo.items() if k not in ("acao", "alvo", "texto", "dias")}
        if params.get("convenio_id") == "@outro_convenio":
            params["convenio_id"] = next(i["convenio_id"] for i in m.insurances if i["convenio_id"] != s["convenio_id"])
            contexto["convenio_de_" + passo["alvo"]] = conv_nome[params["convenio_id"]]
        if params.get("procedimento_id") == "@outro_procedimento":
            atual = next(x for x in m.procedures if x["procedimento_id"] == s["procedimento_id"])
            novo = next(x for x in m.procedures if x["procedimento_id"] != atual["procedimento_id"]
                        and x["tipo_procedimento"] == atual["tipo_procedimento"])
            params["procedimento_id"] = novo["procedimento_id"]
            contexto["tabela_de_" + passo["alvo"]] = f"{novo['base'] / 100:.2f}"
        if passo["acao"] == "remarcar":
            nova = sdate(s) + timedelta(days=passo.get("dias", 1))
            params["data"] = nova.isoformat()
            contexto["data_de_" + passo["alvo"]] = f"{nova.isoformat()} {params['horario'][:5]}"
        ops.acao(m, sid, passo["acao"], **params)
        feito.append(f"{passo['texto']} (agendamento {sid})")
    m.ids.marcar_usados(a for a in alvos.values() if a < 910001)
    verificacoes = []
    for v in roteiro["verificacoes"]:
        if erp in v.get("pular_em", ()):
            continue
        esperado = v.get("esperado_em", {}).get(erp, v["esperado"])
        if isinstance(esperado, str) and esperado.startswith("@"):
            esperado = str(contexto.get(esperado[1:], ""))
        verificacoes.append({k: x for k, x in v.items() if k not in ("pular_em", "esperado_em")} | {"alvo_id": alvos[v["alvo"]], "esperado": esperado})
    return {"roteiro": roteiro["id"], "titulo": roteiro["titulo"], "passos": feito, "alvos": alvos,
            "ids_externos": sorted(set(alvos.values())), "verificacoes": verificacoes}


def consulta(ids, conta=None):
    """SQL para conferir no banco do cliente os agendamentos pelo id externo, ou None se o perfil não tem."""
    p = perfil.ativo()
    if p.consulta is None:
        return None
    return p.consulta(ids, conta if conta is not None else p.conta_padrao)


def _num(texto):
    try:
        return round(float(texto), 2)
    except (TypeError, ValueError):
        return None


def avaliar(verificacoes, linhas, antes=None):
    """linhas: resultado do banco (lista de dicts com id_externo, price, date, convenio...).
    antes: linhas lidas antes da carga (opcional), usadas por status_mudou."""
    por_id = {}
    for r in linhas:
        por_id.setdefault(str(r.get("id_externo")), []).append(r)
    antes_id = {str(r.get("id_externo")): r for r in (antes or [])}
    saida = []
    for v in verificacoes:
        rows = por_id.get(str(v["alvo_id"]), [])
        res = {"alvo": v["alvo"], "id_externo": v["alvo_id"], "campo": v["campo"], "esperado": v["esperado"],
               "explica": v["explica"]}
        if not rows:
            saida.append(dict(res, resultado="não chegou", obtido=""))
            continue
        r, campo, esp = rows[0], v["campo"], v["esperado"]
        if campo == "existe_unico":
            ok, obtido = len(rows) == 1, str(len(rows))
        elif campo == "status_mudou":
            ant = antes_id.get(str(v["alvo_id"]))
            if ant is None:
                saida.append(dict(res, resultado="sem referência", obtido=str(r.get("status")),
                                  explica=v["explica"] + " (informe o resultado de antes da carga para comparar)"))
                continue
            ok = str(ant.get("status")) != str(r.get("status"))
            obtido = f"{perfil.nome_status(ant.get('status'))} para {perfil.nome_status(r.get('status'))}"
        elif campo == "price":
            obtido = str(r.get("price") if r.get("price") not in (None, "") else "NULL")
            if esp == "NAO_NEGATIVO":
                ok = _num(obtido) is None or _num(obtido) > 0
            elif esp == "NAO_ACIMA_DO_LIMITE":
                ok = _num(obtido) is None or _num(obtido) <= 99999.99
            elif esp == "NAO_ZERO":
                ok = _num(obtido) != 0 and _num(obtido) is not None or obtido == "NULL"
            elif esp == "NULL":
                ok = obtido == "NULL"
            else:
                ok = _num(obtido) == _num(esp)
        elif campo == "status_cliente":
            obtido = perfil.nome_status(r.get("status"))
            ok = obtido == esp
        elif campo == "date":
            obtido = str(r.get("date", ""))[:16].replace("T", " ")
            ok = obtido == esp
        else:
            obtido = str(r.get(campo, ""))
            ok = obtido == esp
        saida.append(dict(res, resultado="passou" if ok else "falhou", obtido=obtido))
    return saida
