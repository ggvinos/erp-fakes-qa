from collections import Counter

from . import perfil
from .model import PROC_TYPES, sdate


def describe_model(m, erp="feegow"):
    plans = [dict(p, convenio_id=i["convenio_id"]) for i in m.insurances for p in i["planos"]]
    tables = [{k: v for k, v in t.items() if k != "mult"} | {"multiplicador_de_preco": t["mult"]} for t in m.tables]
    profs = [{"profissional_id": p["profissional_id"], "nome": p["nome"], "sexo": p["sexo"],
              "unidades": p["unidades"], "especialidades": [e["especialidade_id"] for e in p["especialidades"]],
              "convenios": [c["convenio_id"] for c in p["convenios"]]} for p in m.professionals]
    procs = [{k: v for k, v in p.items() if k != "base"} | {"valor_base_centavos": p["base"]} for p in m.procedures]
    schedules = [{k: v for k, v in s.items() if k not in ("procedimentos",)} for s in list(m.schedules.values())]
    for s in schedules:
        s["data"] = sdate(s).isoformat()
        s.pop("abs_date", None)
    per_unit = Counter(s["unidade_id"] for s in schedules)
    with_conv = sum(1 for s in schedules if s["convenio_id"] is not None)
    ents = [
        ("unidades", "Unidade", m.units),
        ("especialidades", "Especialidade", m.specialties),
        ("convenios", "Convênio", [{k: v for k, v in i.items() if k != "planos"} for i in m.insurances]),
        ("planos", "Plano do convênio", plans),
        ("tabelas", "Tabela particular", tables),
        ("ocultos", "Convênio não sincronizado", [{k: v for k, v in i.items() if k != "planos"} for i in m.hidden_insurances]),
        ("tipos", "Tipo de procedimento", [{"id": i, "tipo": n} for i, n in PROC_TYPES.items()]),
        ("procedimentos", "Procedimento", procs),
        ("profissionais", "Profissional", profs),
        ("pacientes", "Paciente", list(m.patients.values())),
        ("agendamentos", "Agendamento", schedules),
        ("bloqueios", "Bloqueio de agenda", m.blocks),
    ]
    entities = []
    p = perfil.ativo()
    for key, nome, rows in ents:
        destino = p.destino_entidades_erp.get(erp, {}).get(key) or p.destino_entidades.get(key, "")
        cols = list(rows[0].keys()) if rows else []
        entities.append({"chave": key, "nome": nome, "destino": destino, "total": len(rows), "colunas": cols,
                         "exemplos": rows[:4]})
    relations = [
        ("profissionais", "unidades", sum(len(p["unidades"]) for p in profs), "onde o profissional atende"),
        ("profissionais", "especialidades", sum(len(p["especialidades"]) for p in profs), "especialidades do profissional"),
        ("profissionais", "convenios", sum(len(p["convenios"]) for p in profs), "convênios aceitos"),
        ("convenios", "planos", len(plans), "planos de cada convênio"),
        ("procedimentos", "tipos", len(procs), "Consulta ou Exame"),
        ("agendamentos", "unidades", len(schedules), "unidade do atendimento"),
        ("agendamentos", "profissionais", len(schedules), "profissional"),
        ("agendamentos", "procedimentos", len(schedules), "procedimento"),
        ("agendamentos", "pacientes", len(schedules), "paciente"),
        ("agendamentos", "convenios", with_conv, "vazio = particular"),
        ("agendamentos", "tabelas", len(schedules) - with_conv, "só em particular"),
        ("agendamentos", "especialidades", sum(1 for s in schedules if s["especialidade_id"]), "especialidade"),
        ("bloqueios", "profissionais", len(m.blocks), "profissional bloqueado"),
    ]
    return {"entidades": entities,
            "relacoes": [{"de": a, "para": b, "tipo": c, "qtde": d, "obs": e} for a, b, c, d, e in relations],
            "agendamentos_por_cenario": Counter(s["scenario"] for s in schedules),
            "agendamentos_por_unidade": per_unit}
