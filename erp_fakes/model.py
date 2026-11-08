import random
import re
from datetime import date, datetime, timedelta

FIRST_F = ["Ana", "Carla", "Eduarda", "Gabriela", "Isabela", "Karina", "Marina", "Olívia", "Rafaela", "Tatiana",
           "Yasmin", "Beatriz", "Diana", "Fernanda", "Helena"]
FIRST_M = ["Bruno", "Daniel", "Felipe", "Hugo", "João", "Lucas", "Nicolas", "Pedro", "Samuel", "Vinícius",
           "Arthur", "Caio", "Enzo", "Guilherme", "Igor"]
LAST = ["Almeida", "Barbosa", "Cardoso", "Dias", "Esteves", "Ferreira", "Gomes", "Henrique", "Lima", "Martins",
        "Nogueira", "Oliveira", "Pereira", "Queiroz", "Ribeiro", "Santos", "Teixeira", "Vieira", "Xavier", "Zanetti"]
SPECIALTIES = ["Clínica Geral", "Cardiologia", "Dermatologia", "Ortopedia", "Ginecologia", "Pediatria", "Neurologia",
               "Oftalmologia", "Endocrinologia", "Psiquiatria", "Urologia", "Nutrição"]
INSURANCES = ["Unimed Nacional", "Bradesco Saúde", "SulAmérica", "Amil", "Porto Seguro", "Hapvida", "Cassi", "Geap"]
PROC_TYPES = {1: "Consulta", 2: "Exame"}
CONSULT = ["Consulta", "Retorno", "Consulta Online", "Consulta Pré-operatória", "Consulta de Rotina"]
EXAMS = ["Hemograma", "Glicemia", "Ultrassonografia Abdominal", "Raio-X Tórax", "Eletrocardiograma", "Ecocardiograma",
         "Ressonância Joelho", "Tomografia Crânio", "Mamografia", "Densitometria", "Colonoscopia", "Endoscopia",
         "Papanicolau", "Audiometria", "Campimetria", "Teste Ergométrico", "Holter 24h", "MAPA 24h",
         "Ultrassom Pélvico", "Ultrassom Tireoide", "Colesterol Total", "TSH", "Vitamina D", "Urocultura",
         "Espirometria", "Biópsia de Pele", "Eletroneuromiografia", "Cintilografia", "Doppler Carotídeo"]
STATUSES = [(1, "Marcado - não confirmado"), (2, "Em atendimento"), (3, "Atendido"), (4, "Aguardando"),
            (5, "Chamado"), (6, "Não compareceu"), (7, "Marcado - confirmado"), (11, "Desmarcado pelo paciente"),
            (15, "Desmarcado pelo profissional"), (16, "Remarcado")]
STATUS_WEIGHTS = {1: 62, 7: 22, 11: 6, 15: 2, 16: 3, 3: 3, 6: 2}

SCENARIOS = [
    ("particular_com_valor_erp", 22), ("particular_sem_valor_erp", 20), ("convenio_com_valor_erp", 18),
    ("convenio_sem_valor_erp", 14), ("convenio_nao_sincronizado_com_valor", 3), ("valor_zero", 2),
    ("valor_acima_do_limite", 1), ("formatos_de_valor", 5), ("multiplos_procedimentos", 6),
    ("tabela_cartao_desconto", 5), ("valor_numerico_json", 2), ("valor_negativo", 1), ("particular_sem_preco_tabela", 1),
]
VALUE_FORMATS = ["R$ {br}", "{br}", "{us}", "R$ {us_thousand}", "{int}", "R$ {int},00"]


def _dv(digitos):
    soma = sum(int(d) * peso for d, peso in zip(digitos, range(len(digitos) + 1, 1, -1)))
    resto = (soma * 10) % 11
    return 0 if resto == 10 else resto


def cpf_valido(cpf):
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    return _dv(cpf[:9]) == int(cpf[9]) and _dv(cpf[:10]) == int(cpf[10])


def cpf_ficticio(onze_digitos):
    """CPF fictício com dígitos verificadores corretos, para [[o_cliente]] aceitar o paciente."""
    base = onze_digitos[:9]
    if len(set(base)) == 1:
        base = base[:8] + str((int(base[8]) + 1) % 10)
    return base + str(_dv(base)) + str(_dv(base + str(_dv(base))))


def br(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def sdate(s):
    return s["abs_date"] if "abs_date" in s else date.today() + timedelta(days=s["day_offset"])


from .idstore import IdStore


class Conflito(Exception):
    pass


class Model:
    def __init__(self, seed, patients, schedules, days, phone, phone_count, units, ids=None, marca="Fake", unit_base=101, profissionais=40):
        self.seed, self.days = seed, days
        self.ids = ids or IdStore()
        rnd = random.Random(seed)
        self.units = [{"unidade_id": unit_base + i, "nome_fantasia": n, "telefone_1": f"(48) 0000-00{i}0",
                       "bairro": b, "endereco": f"Rua das Flores", "numero": str(100 + i * 50), "cep": f"8810{i}-000",
                       "razao_social": f"{n} Ltda", "cnpj": f"12.345.678/000{i + 1}-9{i}", "cidade": "Florianópolis",
                       "estado": "SC", "ExibirAgendamentoOnline": "1"}
                      for i, (n, b) in enumerate([(f"Clínica {marca} Palhoça", "Pagani"), (f"Clínica {marca} Florianópolis", "Centro"),
                                                  (f"Clínica {marca} São José", "Kobrasol"), (f"Clínica {marca} Biguaçu", "Centro")][:units])]
        self.specialties = [{"especialidade_id": 1 + i, "nome": n, "consulta_id": 1001, "consulta_online_id": 1003,
                             "exibir_agendamento_online": 1, "codigo_tiss": f"225{i:02d}"} for i, n in enumerate(SPECIALTIES)]
        self.insurances = []
        pid = 401
        for i, n in enumerate(INSURANCES):
            plans = [{"plano_id": pid + j, "plano": f"{n} {p}"} for j, p in enumerate(["Básico", "Plus", "Premium"][: 2 + i % 2])]
            pid += 5
            self.insurances.append({"convenio_id": 201 + i, "nome": n, "registro_ans": f"34{i:04d}", "planos": plans})
        self.hidden_insurances = [{"convenio_id": 290 + i, "nome": f"Convênio Não Sincronizado {i + 1}",
                                   "registro_ans": f"39{i:04d}", "planos": []} for i in range(3)]
        self.tables = [{"tabela_id": 1, "nome_tabela": "Particular", "ExibirAgendamentoOnline": "1", "mult": 1.0},
                       {"tabela_id": 2, "nome_tabela": "Cartão de Todos", "ExibirAgendamentoOnline": "1", "mult": 0.6},
                       {"tabela_id": 3, "nome_tabela": "Particular Premium", "ExibirAgendamentoOnline": "1", "mult": 1.5}]
        self.procedures = []
        for i, n in enumerate(CONSULT + EXAMS):
            is_consult = i < len(CONSULT)
            base = rnd.choice([18000, 22000, 25000, 30000, 38000]) if is_consult else rnd.choice([4500, 8000, 12000, 25000, 48000, 95000])
            self.procedures.append({"procedimento_id": 1001 + i, "nome": n, "tipo_procedimento": 1 if is_consult else 2,
                                    "preparo": None if is_consult else "Jejum de 8 horas.", "base": base})
        self.no_price_table2 = {p["procedimento_id"] for p in rnd.sample(self.procedures, 3)}
        self.professionals = []
        for i in range(profissionais):
            specs = rnd.sample(self.specialties, 1 + i % 2)
            ins = rnd.sample(self.insurances, 3 + i % 4)
            self.professionals.append({
                "profissional_id": 2001 + i, "nome": f"{'Dr.' if i % 2 else 'Dra.'} {rnd.choice(FIRST_M if i % 2 else FIRST_F)} {rnd.choice(LAST)}",
                "especialidades": specs, "convenios": ins, "sexo": "Masculino" if i % 2 else "Feminino",
                "unidades": rnd.sample([u["unidade_id"] for u in self.units], 1 + i % len(self.units)), "ativo": True})
        seen, k = set(), 0
        for prof in self.professionals:
            while prof["nome"] in seen:
                prof["nome"] += " " + LAST[k % len(LAST)]
                k += 1
            seen.add(prof["nome"])
        self.blocks = []
        self.patients = {}
        for i in range(patients):
            n = 5001 + i
            male = rnd.random() < .45
            nome = f"{rnd.choice(FIRST_M if male else FIRST_F)} {rnd.choice(LAST)} {rnd.choice(LAST)}"
            real = phone and i < phone_count
            cel = phone if real else f"554800{n:07d}"[:13]
            self.patients[n] = {
                "paciente_id": n, "nome": nome, "nome_social": None, "sexo": "Masculino" if male else "Feminino",
                "nascimento": f"{rnd.randint(1948, 2018)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
                "celulares": [cel], "celular": cel, "email": f"paciente{n}@teste.invalid",
                "documentos": {"cpf": cpf_ficticio("".join(str(rnd.randint(0, 9)) for _ in range(11)))}}
        self.schedules = {}
        names = [s for s, _ in SCENARIOS]
        weights = [w for _, w in SCENARIOS]
        for i in range(schedules):
            self._make_schedule(i, rnd, rnd.choices(names, weights)[0])

    def _make_schedule(self, i, rnd, scenario, sid=None, pids=None):
        unit = rnd.choice(self.units)
        pros = [p for p in self.professionals if unit["unidade_id"] in p["unidades"]]
        prof = rnd.choice(pros)
        spec = rnd.choice(prof["especialidades"])
        proc = rnd.choice(self.procedures)
        priv_scn = {"particular_com_valor_erp", "particular_sem_valor_erp", "tabela_cartao_desconto", "valor_zero",
                    "valor_acima_do_limite", "formatos_de_valor", "valor_numerico_json", "valor_negativo",
                    "particular_sem_preco_tabela"}
        convenio_id = plano_id = tabela_id = None
        if scenario == "convenio_nao_sincronizado_com_valor":
            convenio_id = rnd.choice(self.hidden_insurances)["convenio_id"]
        elif scenario in ("convenio_com_valor_erp", "convenio_sem_valor_erp") or (scenario in ("multiplos_procedimentos", "formatos_de_valor") and i % 2):
            ins = rnd.choice(prof["convenios"])
            convenio_id = ins["convenio_id"]
            plano_id = rnd.choice(ins["planos"])["plano_id"]
        if convenio_id is None:
            tabela_id = 2 if scenario == "tabela_cartao_desconto" else rnd.choice([1, 1, 3])
        value = round(proc["base"] / 100 * rnd.choice([1, 1, 1.1, 0.9]), 2)
        valor = None
        if scenario in ("particular_com_valor_erp", "convenio_com_valor_erp", "convenio_nao_sincronizado_com_valor", "tabela_cartao_desconto"):
            valor = f"R$ {br(value)}"
        elif scenario == "valor_zero":
            valor = "R$ 0,00"
        elif scenario == "valor_acima_do_limite":
            valor = "R$ 100.000,00"
        elif scenario == "valor_negativo":
            valor = "R$ -50,00"
        elif scenario == "valor_numerico_json":
            valor = value
        elif scenario == "formatos_de_valor":
            fmt = VALUE_FORMATS[i % len(VALUE_FORMATS)]
            valor = fmt.format(br=br(value), us=f"{value:.2f}", us_thousand=f"{value:,.2f}", int=int(value))
        elif scenario == "multiplos_procedimentos":
            valor = f"R$ {br(value * 2)}"
        procs = [{"procedimentoID": proc["procedimento_id"], "valor": value}]
        if scenario == "multiplos_procedimentos":
            other = rnd.choice([p for p in self.procedures if p is not proc])
            procs.append({"procedimentoID": other["procedimento_id"], "valor": round(other["base"] / 100, 2)})
        if scenario == "particular_sem_preco_tabela":
            proc = self.procedures[[p["procedimento_id"] for p in self.procedures].index(next(iter(self.no_price_table2)))]
            tabela_id = 2
            procs = [{"procedimentoID": proc["procedimento_id"], "valor": 0}]
        status = rnd.choices(list(STATUS_WEIGHTS), list(STATUS_WEIGHTS.values()))[0]
        sid = sid if sid is not None else 900001 + i
        pid = rnd.choice(pids if pids is not None else list(self.patients))
        self.schedules[sid] = {
            "agendamento_id": sid, "day_offset": rnd.randint(0, self.days - 1),
            "horario": f"{rnd.randint(7, 17):02d}:{rnd.choice([0, 20, 40]):02d}:00",
            "unidade_id": unit["unidade_id"], "profissional_id": prof["profissional_id"],
            "procedimento_id": proc["procedimento_id"], "paciente_id": pid, "status_id": status,
            "convenio_id": convenio_id, "plano_id": plano_id, "tabela_id": tabela_id,
            "especialidade_id": spec["especialidade_id"], "valor_total_agendamento": valor,
            "procedimentos": procs, "scenario": scenario}

    def add_patient(self, body):
        n = self.ids.next("patient", max(self.patients) + 1 if self.patients else 0)
        cel = body.get("celular") or body.get("telefone") or f"554800{n:07d}"[:13]
        self.patients[n] = {
            "paciente_id": n, "nome": body.get("nome_completo") or f"Paciente {n}", "nome_social": None,
            "sexo": "Feminino" if body.get("genero") == "F" else "Masculino",
            "nascimento": body.get("data_nascimento"), "celulares": [cel], "celular": cel,
            "email": body.get("email"), "documentos": {"cpf": body.get("cpf")}}
        return n

    def add_schedule(self, body, forced_id=None):
        sid = forced_id or self.ids.next("schedule", max(self.schedules) + 1 if self.schedules else 0)
        raw = str(body["data"]).split(" ")[0]
        d = next(datetime.strptime(raw, f).date() for f in ("%d-%m-%Y", "%Y-%m-%d") if re.fullmatch(
            r"\d{2}-\d{2}-\d{4}" if f == "%d-%m-%Y" else r"\d{4}-\d{2}-\d{2}", raw))
        hh = str(body["horario"])
        hh = hh if hh.count(":") == 2 else hh + ":00"
        if int(body["paciente_id"]) not in self.patients:
            raise Conflito("Paciente não encontrado")
        if d < date.today():
            raise ValueError("A data não pode ser retroativa")
        prof = next(p for p in self.professionals if p["profissional_id"] == int(body["profissional_id"]))
        if self.slot_taken(prof["profissional_id"], d, hh):
            raise Conflito("Horário ocupado")
        local = int(body.get("local_id") or 0)
        unit = local if local in [u["unidade_id"] for u in self.units] else prof["unidades"][0]
        cents = body.get("valor")
        valor = f"R$ {br(cents / 100)}" if isinstance(cents, (int, float)) and cents > 0 else None
        conv = body.get("convenio_id")
        self.schedules[sid] = {
            "agendamento_id": sid, "abs_date": d, "day_offset": 0, "horario": hh, "unidade_id": unit,
            "profissional_id": prof["profissional_id"], "procedimento_id": int(body["procedimento_id"]),
            "paciente_id": int(body["paciente_id"]), "status_id": 1,
            "convenio_id": int(conv) if conv not in (None, "") else None,
            "plano_id": int(body["convenioplano"]) if body.get("convenioplano") else None,
            "tabela_id": int(body["tabela_id"]) if body.get("tabela_id") else None,
            "especialidade_id": int(body["especialidade_id"]) if body.get("especialidade_id") else None,
            "valor_total_agendamento": valor,
            "procedimentos": [{"procedimentoID": int(body["procedimento_id"]), "valor": (cents or 0) / 100}],
            "scenario": "criado_pelo_cliente"}
        return sid

    def free_slots(self, prof, unit, first, last):
        if unit not in prof["unidades"]:
            return {}
        taken = {(sdate(s), s["horario"][:5]) for s in self.schedules.values()
                 if s["profissional_id"] == prof["profissional_id"] and s["status_id"] not in (11, 15, 16)}
        now = datetime.now() + timedelta(minutes=30)
        out, d = {}, first
        while d <= last:
            if d.weekday() < 5:
                hours = []
                for h in range(8, 18):
                    for mi in (0, 20, 40):
                        t = f"{h:02d}:{mi:02d}"
                        if (d, t) not in taken and datetime.combine(d, datetime.strptime(t, "%H:%M").time()) > now:
                            hours.append(t + ":00")
                if hours:
                    out[d.isoformat()] = hours
            d += timedelta(days=1)
        return out

    def slot_taken(self, profissional_id, d, horario, ignore_id=None):
        return any(s["profissional_id"] == profissional_id and sdate(s) == d and s["horario"] == horario
                   and s["status_id"] not in (11, 15, 16) and s["agendamento_id"] != ignore_id
                   for s in self.schedules.values())

    def schedule_json(self, s, list_procedures):
        p = self.patients.get(s["paciente_id"]) or {"nome": f"Paciente {s['paciente_id']}", "celular": None}
        d = sdate(s)
        out = {k: v for k, v in s.items() if k not in ("day_offset", "abs_date", "scenario", "procedimentos")}
        out.update({"data": d.strftime("%d-%m-%Y"), "nome_paciente": p["nome"], "celular": p["celular"],
                    "obs": f"cenario={s['scenario']}"})
        if list_procedures:
            out["procedimentos"] = s["procedimentos"]
        return out
