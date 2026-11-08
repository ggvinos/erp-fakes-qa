import http.client
import time
import unittest
import urllib.error
from datetime import date, datetime, timedelta

from helpers import ComPerfilExemplo
from erp_fakes import FakeErp, perfil
from erp_fakes.testing import FakeErpError
from erp_fakes.model import SCENARIOS, Model


def proximo_dia_util(dias=3):
    d = date.today() + timedelta(days=dias)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def hoje_mais(dias):
    return (date.today() + timedelta(days=dias)).strftime("%d-%m-%Y")


class FakeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeErp(patients=150, schedules=700).start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.fake.reset()
        self.fake.clear_faults()
        self.fake.post("/_admin/journal/limpar")
        self.fake.post("/_admin/config", {"paginacao_real": True})

    def horario_livre(self, prof, dia, a_partir=9):
        for h in range(a_partir, 18):
            hora = f"{h:02d}:00:00"
            if not self.fake.model.slot_taken(prof["profissional_id"], dia, hora):
                return hora
        self.fail("sem horário livre")

    def novo_paciente(self, cpf="11122233344"):
        return self.fake.post("/patient/create", {"nome_completo": "Teste Auto", "cpf": cpf, "data_nascimento": "1990-01-01",
                                                   "genero": "F", "telefone": "5548900000000"})["content"]["paciente_id"]

    def agendar(self, valor=0, dia=None, hora=None, prof=None):
        prof = prof or self.fake.model.professionals[0]
        dia = dia or proximo_dia_util()
        hora = hora or self.horario_livre(prof, dia)
        corpo = {"local_id": prof["unidades"][0], "paciente_id": self.novo_paciente(), "profissional_id": prof["profissional_id"],
                 "procedimento_id": 1001, "data": dia.strftime("%d-%m-%Y"), "horario": hora, "valor": valor, "plano": 0, "tabela_id": 1}
        return self.fake.post("/appoints/new-appoint", corpo)["content"]["agendamento_id"], prof, dia, hora


class AutenticacaoTest(FakeCase):
    def test_sem_chave_responde_401(self):
        status, corpo = self.fake.request("GET", "/appoints/status", token=None)
        self.assertEqual(status, 401)
        self.assertFalse(corpo["success"])

    def test_chave_errada_responde_403(self):
        self.assertEqual(self.fake.request("GET", "/appoints/status", token="x")[0], 403)

    def test_health_e_favicon_nao_exigem_chave(self):
        self.assertEqual(self.fake.request("GET", "/health", token=None)[0], 200)
        self.assertEqual(self.fake.request("GET", "/favicon.ico", token=None)[0], 204)

    def test_corpo_que_nao_e_json_responde_422(self):
        import urllib.request
        req = urllib.request.Request(self.fake.url + "/patient/create", data=b"nao e json", method="POST",
                                     headers={"x-access-token": self.fake.token})
        with self.assertRaises(urllib.error.HTTPError) as erro:
            urllib.request.urlopen(req)
        self.assertEqual(erro.exception.code, 422)
        erro.exception.close()


class CargaConformeDocumentacaoTest(FakeCase):
    def test_unidades_e_locais(self):
        c = self.fake.get("/company/list-unity")["content"]
        unidades = c["matriz"] + c["unidades"]
        self.assertEqual(len(unidades), 3)
        for k in ("unidade_id", "nome_fantasia", "cnpj", "endereco", "cep", "ExibirAgendamentoOnline"):
            self.assertIn(k, unidades[0])
        locais = self.fake.get("/company/list-local")["content"]
        self.assertEqual({x["unidade_id"] for x in locais}, {u["unidade_id"] for u in unidades})

    def test_convenios_planos_ans(self):
        ins = self.fake.get("/insurance/list")["content"]
        self.assertEqual(len(ins), 8)
        self.assertTrue(all(i["registro_ans"] and i["planos"] and "plano_id" in i["planos"][0] for i in ins))

    def test_especialidades_com_total(self):
        r = self.fake.get("/specialties/list")
        self.assertEqual(r["total"], 12)
        for k in ("especialidade_id", "nome", "consulta_id", "exibir_agendamento_online", "codigo_tiss"):
            self.assertIn(k, r["content"][0])

    def test_status_motivos_canais(self):
        self.assertIn(7, [s["id"] for s in self.fake.get("/appoints/status")["content"]])
        self.assertEqual([m["id"] for m in self.fake.get("/appoints/motives")["content"]], [1, 2, 3])
        self.assertTrue(self.fake.get("/appoints/list-channel")["content"])

    def test_tabelas_particulares(self):
        r = self.fake.get("/patient/list-privates")
        self.assertEqual(r["total"], 3)
        self.assertTrue(all("tabela_id" in t and "nome_tabela" in t for t in r["content"]))

    def test_procedimentos_listados_e_tipos(self):
        self.assertEqual([t["tipo"] for t in self.fake.get("/procedures/types")["content"]], ["Consulta", "Exame"])
        item = self.fake.get("/procedures/list")["content"][0]
        for k in ("procedimento_id", "nome", "tipo_procedimento", "preparo", "tempo", "valor", "especialidade_id", "permite_agendamento_online"):
            self.assertIn(k, item)
        so_exames = self.fake.get("/procedures/list", tipo_procedimento=2)["content"]
        self.assertTrue(so_exames and all(p["tipo_procedimento"] == 2 for p in so_exames))

    def test_preco_de_tabela_em_centavos_e_multiplicador(self):
        proc = self.fake.get("/procedures/list")["content"][0]
        t1 = self.fake.get("/procedures/list", procedimento_id=proc["procedimento_id"], tabela_id=1)["content"][0]["valor"]
        t3 = self.fake.get("/procedures/list", procedimento_id=proc["procedimento_id"], tabela_id=3)["content"][0]["valor"]
        self.assertEqual((t1, t3), (proc["valor"], int(proc["valor"] * 1.5)))

    def test_convenios_do_procedimento(self):
        self.assertEqual(self.fake.request("GET", "/procedures/insurance-procedures-list")[0], 400)
        r = self.fake.get("/procedures/insurance-procedures-list", procedimentoID=1001)["content"][0]
        self.assertIn("201", r["Convenios"])

    def test_profissionais_exigem_ativo(self):
        self.assertEqual(self.fake.request("GET", "/professional/list")[0], 422)
        prof = self.fake.get("/professional/list", ativo=1)["content"][0]
        for k in ("profissional_id", "nome", "conselho", "age_restriction", "especialidades"):
            self.assertIn(k, prof)

    def test_profissional_inativo_so_aparece_com_ativo_zero(self):
        pid = self.fake.get("/professional/list", ativo=1)["content"][0]["profissional_id"]
        self.fake.edit("profissionais", pid, ativo="false")
        self.assertNotIn(pid, [p["profissional_id"] for p in self.fake.get("/professional/list", ativo=1)["content"]])
        self.assertIn(pid, [p["profissional_id"] for p in self.fake.get("/professional/list", ativo=0)["content"]])

    def test_profissional_busca_e_convenios(self):
        pid = self.fake.get("/professional/list", ativo=1)["content"][0]["profissional_id"]
        info = self.fake.get("/professional/search", profissional_id=pid)["content"]
        self.assertIn("sexo", info["informacoes"][0])
        self.assertTrue(info["especialidades"])
        convenios = self.fake.get("/professional/insurance", profissional_id=pid)["content"]
        self.assertTrue(all("registro_ans" in c for c in convenios))
        status, corpo = self.fake.request("GET", "/professional/search?profissional_id=1")
        self.assertEqual((status, corpo["content"]), (409, "Profissional não encontrado."))

    def test_paciente_busca_formato_e_409(self):
        pid = next(iter(self.fake.model.patients))
        c = self.fake.get("/patient/search", paciente_id=pid)["content"]
        datetime.strptime(c["nascimento"], "%d-%m-%Y")
        self.assertIsInstance(c["email"], list)
        self.assertIsInstance(c["celulares"], list)
        self.assertIn("cpf", c["documentos"])
        status, corpo = self.fake.request("GET", "/patient/search?paciente_id=1")
        self.assertEqual((status, corpo["content"]), (409, "Paciente não existe"))

    def test_paciente_lista_filtra_por_cpf_e_pagina(self):
        p = next(iter(self.fake.model.patients.values()))
        r = self.fake.get("/patient/list", cpf=p["documentos"]["cpf"])
        self.assertEqual([x["patient_id"] for x in r["content"]], [p["paciente_id"]])
        pagina = self.fake.get("/patient/list", limit=10, offset=5)
        self.assertEqual((len(pagina["content"]), pagina["total"]), (10, 150))

    def test_paciente_criar_nao_duplica_e_valida(self):
        a = self.novo_paciente("99988877766")
        b = self.novo_paciente("99988877766")
        self.assertEqual(a, b)
        status, corpo = self.fake.request("POST", "/patient/create", {"nome_completo": "Sem Cpf"})
        self.assertEqual((status, "cpf" in corpo), (422, True))

    def test_paciente_editar_e_cpf_nao_muda(self):
        pid = self.novo_paciente("55544433322")
        self.assertEqual(self.fake.post("/patient/edit", {"paciente_id": pid, "nome_completo": "Outro Nome"})["content"], "Paciente atualizado")
        self.assertEqual(self.fake.get("/patient/search", paciente_id=pid)["content"]["nome"], "Outro Nome")
        self.assertEqual(self.fake.request("POST", "/patient/edit", {"paciente_id": pid, "cpf": "11111111111"})[0], 422)

    def test_agendamento_formato_e_filtros(self):
        fim = (date.today() + timedelta(days=30)).strftime("%d-%m-%Y")
        res = self.fake.get("/appoints/search", data_start=date.today().strftime("%d-%m-%Y"), data_end=fim)["content"]
        s = res[0]
        datetime.strptime(s["data"], "%d-%m-%Y")
        datetime.strptime(s["horario"], "%H:%M:%S")
        por_id = self.fake.get("/appoints/search", agendamento_id=s["agendamento_id"])["content"]
        self.assertEqual([x["agendamento_id"] for x in por_id], [s["agendamento_id"]])
        por_prof = self.fake.get("/appoints/search", profissional_id=s["profissional_id"], status_id=f"{s['status_id']},7")["content"]
        self.assertTrue(por_prof and all(x["profissional_id"] == s["profissional_id"] for x in por_prof))

    def test_data_aceita_os_dois_formatos(self):
        a = self.fake.get("/appoints/search", data_start=hoje_mais(0), data_end=hoje_mais(2))["content"]
        iso = lambda n: (date.today() + timedelta(days=n)).isoformat()
        b = self.fake.get("/appoints/search", data_start=iso(0), data_end=iso(2))["content"]
        self.assertEqual(len(a), len(b))

    def test_paginacao_de_list_procedures(self):
        args = dict(data_start=hoje_mais(0), data_end=hoje_mais(13), list_procedures=1)
        primeira = self.fake.get("/appoints/search", **args)["content"]
        self.assertEqual(len(primeira), 50)
        segunda = self.fake.get("/appoints/search", start=50, **args)["content"]
        self.assertTrue(segunda and segunda[0]["agendamento_id"] not in {x["agendamento_id"] for x in primeira})
        self.fake.post("/_admin/config", {"paginacao_real": False})
        self.assertGreater(len(self.fake.get("/appoints/search", **args)["content"]), 50)

    def test_multiplos_procedimentos_so_com_list_procedures(self):
        multi = self.fake.schedules("multiplos_procedimentos")[0]
        plain = self.fake.get("/appoints/search", agendamento_id=multi["agendamento_id"])["content"][0]
        full = self.fake.get("/appoints/search", agendamento_id=multi["agendamento_id"], list_procedures=1)["content"][0]
        self.assertNotIn("procedimentos", plain)
        self.assertGreater(len(full["procedimentos"]), 1)

    def test_planos_de_tabela_particular_paginados(self):
        r = self.fake.get("/financial2/external/private-table/list", unityId=0, page=1, perPage=5)
        self.assertEqual((len(r["data"]), r["count"]), (5, 20))


class CenariosTest(FakeCase):
    def test_todos_os_cenarios_aparecem(self):
        por = self.fake.scenarios()["por_cenario"]
        self.assertEqual(set(por), {n for n, _ in SCENARIOS})
        self.assertEqual(sum(por.values()), 700)

    def test_regras_dos_cenarios(self):
        listados = {i["convenio_id"] for i in self.fake.get("/insurance/list")["content"]}
        for s in self.fake.schedules("convenio_nao_sincronizado_com_valor"):
            self.assertNotIn(s["convenio_id"], listados)
            self.assertIsNotNone(s["valor_total_agendamento"])
        for s in self.fake.schedules("particular_sem_valor_erp"):
            self.assertIsNone(s["convenio_id"])
            self.assertIsNone(s["valor_total_agendamento"])
        for s in self.fake.schedules("convenio_com_valor_erp"):
            self.assertIn(s["convenio_id"], listados)
        self.assertTrue(all(s["valor_total_agendamento"] == "R$ 0,00" for s in self.fake.schedules("valor_zero")))

    def test_nomes_de_profissionais_sao_unicos(self):
        nomes = [p["nome"] for p in self.fake.model.professionals]
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_mesma_semente_gera_os_mesmos_dados(self):
        a, b = Model(7, 50, 100, 14, None, 5, 3), Model(7, 50, 100, 14, None, 5, 3)
        self.assertEqual([(s["scenario"], s["valor_total_agendamento"]) for s in a.schedules.values()],
                         [(s["scenario"], s["valor_total_agendamento"]) for s in b.schedules.values()])


class EscritasTest(FakeCase):
    def test_agendar_devolve_id_link_e_eventos(self):
        sid, _, dia, hora = self.agendar(valor=25000)
        got = self.fake.get("/appoints/search", agendamento_id=sid)["content"][0]
        self.assertEqual((got["data"], got["horario"], got["valor_total_agendamento"]), (dia.strftime("%d-%m-%Y"), hora, "R$ 250,00"))
        self.assertEqual(got["obs"], "cenario=criado_pelo_cliente")

    def test_agendar_resposta_segue_a_documentacao(self):
        prof = self.fake.model.professionals[0]
        dia = proximo_dia_util()
        corpo = {"local_id": prof["unidades"][0], "paciente_id": self.novo_paciente(), "profissional_id": prof["profissional_id"],
                 "procedimento_id": 1001, "data": dia.strftime("%d-%m-%Y"), "horario": self.horario_livre(prof, dia), "valor": 0, "plano": 0}
        c = self.fake.post("/appoints/new-appoint", corpo)["content"]
        self.assertEqual(set(c), {"agendamento_id", "link", "eventos"})

    def test_agendar_erros_documentados(self):
        sid, prof, dia, hora = self.agendar()
        base = {"local_id": prof["unidades"][0], "paciente_id": self.novo_paciente("22211100099"),
                "profissional_id": prof["profissional_id"], "procedimento_id": 1001, "data": dia.strftime("%d-%m-%Y"),
                "horario": hora, "valor": 0, "plano": 0}
        status, corpo = self.fake.request("POST", "/appoints/new-appoint", base)
        self.assertEqual((status, corpo["content"]), (409, "Horário ocupado"))
        status, corpo = self.fake.request("POST", "/appoints/new-appoint", dict(base, paciente_id=1))
        self.assertEqual((status, corpo["content"]), (409, "Paciente não encontrado"))
        status, _ = self.fake.request("POST", "/appoints/new-appoint", dict(base, data=hoje_mais(-2)))
        self.assertEqual(status, 422)

    def test_horario_ocupado_sai_da_lista_de_horarios(self):
        sid, prof, dia, hora = self.agendar()
        d = dia.strftime("%d-%m-%Y")
        unidade = prof["unidades"][0]
        r = self.fake.get("/appoints/available-schedule", unidade_id=unidade, data_start=d, data_end=d,
                          profissional_id=prof["profissional_id"], tipo="P", procedimento_id=1001)
        horas = r["content"]["profissional_id"][str(prof["profissional_id"])]["local_id"][str(unidade)][dia.isoformat()]
        self.assertNotIn(hora, horas)
        self.assertEqual(r["total"], sum(len(h) for p in r["content"]["profissional_id"].values()
                                         for l in p["local_id"].values() for h in l.values()))

    def test_horarios_exigem_tipo_e_datas(self):
        self.assertEqual(self.fake.request("GET", "/appoints/available-schedule?unidade_id=101")[0], 422)

    def test_cancelar_por_motivo(self):
        sid, *_ = self.agendar()
        self.assertEqual(self.fake.post("/appoints/cancel-appoint", agendamento_id=sid, motivo_id=1)["content"], "Agendamento cancelado")
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=sid)["content"][0]["status_id"], 11)
        sid2, *_ = self.agendar(hora="16:00:00", dia=proximo_dia_util(4))
        self.fake.post("/appoints/cancel-appoint", agendamento_id=sid2, motivo_id=3)
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=sid2)["content"][0]["status_id"], 15)
        self.assertEqual(self.fake.request("POST", "/appoints/cancel-appoint?agendamento_id=1")[1]["content"], "Agendamento não existe")

    def test_remarcar_mantem_o_id(self):
        sid, prof, *_ = self.agendar()
        nova = proximo_dia_util(6)
        hora = self.horario_livre(prof, nova, 14)
        self.fake.post("/appoints/reschedule", {"agendamento_id": sid, "motivo_id": 1, "data": nova.strftime("%d-%m-%Y"), "horario": hora})
        got = self.fake.get("/appoints/search", agendamento_id=sid)["content"][0]
        self.assertEqual((got["agendamento_id"], got["data"], got["horario"]), (sid, nova.strftime("%d-%m-%Y"), hora))
        status, corpo = self.fake.request("POST", "/appoints/reschedule", {"agendamento_id": 1, "data": hoje_mais(2), "horario": "10:00:00"})
        self.assertEqual((status, corpo["content"]), (409, "Agendamento não existe"))

    def test_confirmar_e_atualizar_status(self):
        sid, *_ = self.agendar()
        self.fake.post("/appoints/confirm", agendamento_id=sid)
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=sid)["content"][0]["status_id"], 7)
        self.assertEqual(self.fake.post("/appoints/statusUpdate", {"AgendamentoID": sid, "StatusID": 3, "Obs": "x"})["content"], {"msg": "Status atualizado"})
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=sid)["content"][0]["status_id"], 3)

    def test_bloqueios_no_formato_que_o_cliente_le(self):
        r = self.fake.post("/_admin/entities/bloqueios", {"description": "Almoço", "week_day": "2,3", "units": "101"})
        lista = self.fake.get("/lock/list", unidade_id=101)["content"]
        b = next(x for x in lista if x["id"] == r["id"])
        for k in ("id", "date_start", "date_end", "time_start", "time_end", "professional_id", "description", "week_day", "units"):
            self.assertIn(k, b)
        datetime.strptime(b["date_start"], "%Y-%m-%d")
        self.assertEqual((b["week_day"], b["units"]), (["2", "3"], ["101"]))


class AdministracaoTest(FakeCase):
    def test_editar_entidade_reflete_no_que_o_cliente_le(self):
        pid = self.fake.get("/professional/list", ativo=1)["content"][0]["profissional_id"]
        self.fake.edit("profissionais", pid, nome="Dr. Nome Novo")
        self.assertIn("Dr. Nome Novo", [p["nome"] for p in self.fake.get("/professional/list", ativo=1)["content"]])
        pac = next(iter(self.fake.model.patients))
        self.fake.edit("pacientes", pac, celular="5548911112222")
        self.assertEqual(self.fake.get("/patient/search", paciente_id=pac)["content"]["celulares"], ["5548911112222"])

    def test_criar_e_remover_convenio(self):
        novo = self.fake.post("/_admin/entities/convenios", {"nome": "Convênio Criado"})["id"]
        self.assertIn(novo, [i["convenio_id"] for i in self.fake.get("/insurance/list")["content"]])
        self.fake.post(f"/_admin/entities/convenios/{novo}/remover")
        self.assertNotIn(novo, [i["convenio_id"] for i in self.fake.get("/insurance/list")["content"]])

    def test_remover_convenio_deixa_agendamentos_apontando_para_convenio_desconhecido(self):
        s = self.fake.schedules("convenio_com_valor_erp")[0]
        self.fake.post(f"/_admin/entities/convenios/{s['convenio_id']}/remover")
        self.assertNotIn(s["convenio_id"], [i["convenio_id"] for i in self.fake.get("/insurance/list")["content"]])
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=s["agendamento_id"])["content"][0]["convenio_id"], s["convenio_id"])

    def test_remover_unidade_e_tipo_desconhecido_sao_recusados(self):
        self.assertEqual(self.fake.request("POST", "/_admin/entities/unidades/101/remover")[0], 422)
        self.assertEqual(self.fake.request("GET", "/_admin/entities/nada")[0], 422)

    def test_acoes_da_clinica(self):
        s = self.fake.schedules("particular_com_valor_erp")[0]
        sid = s["agendamento_id"]
        estado = lambda: self.fake.get("/appoints/search", agendamento_id=sid)["content"][0]
        for acao, status in (("confirmar", 7), ("cancelar", 11), ("desmarcar_profissional", 15), ("faltou", 6), ("atendido", 3)):
            self.fake.action(sid, acao)
            self.assertEqual(estado()["status_id"], status, acao)
        self.fake.action(sid, "definir_valor", valor="R$ 777,00")
        self.assertEqual(estado()["valor_total_agendamento"], "R$ 777,00")
        self.fake.action(sid, "trocar_convenio", convenio_id=203)
        self.assertEqual((estado()["convenio_id"], estado()["tabela_id"]), (203, None))
        self.fake.action(sid, "trocar_convenio", convenio_id="")
        self.assertEqual((estado()["convenio_id"], estado()["tabela_id"]), (None, 1))
        self.fake.action(sid, "remarcar", data=hoje_mais(5), horario="10:20:00")
        self.assertEqual((estado()["agendamento_id"], estado()["data"], estado()["horario"]), (sid, hoje_mais(5), "10:20:00"))
        self.fake.action(sid, "sumir")
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=sid)["content"], [])

    def test_criar_agendamento_pelo_painel(self):
        prof = self.fake.model.professionals[0]
        r = self.fake.post("/_admin/schedule", {"profissional_id": prof["profissional_id"], "procedimento_id": 1001,
                                                "unidade_id": prof["unidades"][0], "em_horas": 3, "valor": "R$ 120,00",
                                                "paciente": {"nome": "Paciente Painel", "celular": "5548999990001"}})
        self.assertEqual((r["valor_total_agendamento"], r["obs"]), ("R$ 120,00", "cenario=criado_no_painel"))
        pac = self.fake.get("/patient/search", paciente_id=r["paciente_id"])["content"]
        self.assertEqual(pac["nome"], "Paciente Painel")

    def test_alterar_valor_e_resetar(self):
        s = self.fake.schedules("particular_com_valor_erp")[0]
        self.fake.update_schedule(s["agendamento_id"], valor_total_agendamento="R$ 777,00")
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=s["agendamento_id"])["content"][0]["valor_total_agendamento"], "R$ 777,00")
        self.fake.reset()
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=s["agendamento_id"])["content"][0]["valor_total_agendamento"],
                         s["valor_total_agendamento"])

    def test_sincronizar_convenio_oculto(self):
        oculto = self.fake.scenarios()["convenios_ocultos"][0]["convenio_id"]
        self.assertNotIn(oculto, [i["convenio_id"] for i in self.fake.get("/insurance/list")["content"]])
        self.fake.sync_insurance(oculto)
        self.assertIn(oculto, [i["convenio_id"] for i in self.fake.get("/insurance/list")["content"]])


class FalhasSimuladasTest(FakeCase):
    def test_status_http_com_limite_de_vezes(self):
        self.fake.fault("/appoints/status", "status", 503, times=2)
        self.assertEqual([self.fake.request("GET", "/appoints/status")[0] for _ in range(3)], [503, 503, 200])

    def test_resposta_vazia_e_quebrada(self):
        self.fake.fault("/specialties/list", "vazio")
        self.assertEqual(self.fake.request("GET", "/specialties/list")[1], {})
        self.fake.clear_faults()
        self.fake.fault("/specialties/list", "quebrado")
        status, corpo = self.fake.request("GET", "/specialties/list")
        self.assertEqual(status, 200)
        self.assertIsInstance(corpo, str)
        self.assertIn("<html>", corpo)

    def test_atraso(self):
        self.fake.fault("/insurance/list", "atraso", 400, times=1)
        t0 = time.perf_counter()
        status, _ = self.fake.request("GET", "/insurance/list")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(time.perf_counter() - t0, 0.4)

    def test_derrubar_conexao(self):
        self.fake.fault("/lock/list", "derrubar", times=1)
        with self.assertRaises((http.client.RemoteDisconnected, ConnectionError, urllib.error.URLError)):
            self.fake.request("GET", "/lock/list")
        self.assertEqual(self.fake.request("GET", "/lock/list")[0], 200)

    def test_prefixo_e_metodo_e_nao_afeta_administracao(self):
        self.fake.fault("/appoints/*", "status", 500)
        self.assertEqual(self.fake.request("GET", "/appoints/status")[0], 500)
        self.assertEqual(self.fake.request("GET", "/specialties/list")[0], 200)
        self.assertEqual(self.fake.request("GET", "/_admin/faults")[0], 200)

    def test_atalhos_de_gateway_ruim_502_existem_e_funcionam(self):
        atalhos = {a["nome"]: a for a in self.fake.get("/_admin/faults")["atalhos"]}
        self.assertEqual(atalhos["Gateway ruim (502)"]["valor"], 502)
        a = atalhos["Carga de agendamentos com 502"]
        self.fake.fault(a["rota"], a["tipo"], a["valor"], a["vezes"])
        self.assertEqual(self.fake.request("GET", "/appoints/search?agendamento_id=900001")[0], 502)
        self.assertEqual(self.fake.request("GET", "/appoints/status")[0], 200)

    def test_remover_regra(self):
        regra = self.fake.fault("*", "status", 503)
        self.assertEqual(self.fake.request("GET", "/appoints/status")[0], 503)
        self.fake.post("/_admin/faults/remover", {"id": regra["id"]})
        self.assertEqual(self.fake.request("GET", "/appoints/status")[0], 200)

    def test_tipo_desconhecido_e_recusado(self):
        self.assertEqual(self.fake.request("POST", "/_admin/faults", {"rota": "*", "tipo": "inventado"})[0], 422)


class DiarioTest(FakeCase):
    def test_registra_corpo_resposta_status_e_falha(self):
        self.fake.fault("/patient/list-privates", "status", 500, times=1)
        self.fake.request("POST", "/patient/create", {"nome_completo": "Diario", "cpf": "10101010101"})
        self.fake.request("GET", "/patient/list-privates")
        itens = self.fake.journal()
        criar = next(i for i in itens if i["caminho"] == "/patient/create")
        self.assertIn("Diario", criar["corpo"])
        self.assertIn("paciente_id", criar["resposta"])
        falha = next(i for i in itens if i["caminho"] == "/patient/list-privates")
        self.assertEqual((falha["status"], falha["falha"]), (500, "status 500"))

    def test_nao_registra_administracao_nem_health(self):
        self.fake.request("GET", "/health", token=None)
        self.fake.get("/_admin/scenarios")
        self.assertEqual(self.fake.journal(), [])

    def test_filtros_de_erro_e_caminho(self):
        self.fake.get("/appoints/status")
        self.fake.request("GET", "/appoints/status", token="errada")
        self.assertEqual([i["status"] for i in self.fake.journal(so_erros=1)], [403])
        self.assertEqual(len(self.fake.journal(caminho="status")), 2)

    def test_limpar(self):
        self.fake.get("/appoints/status")
        self.fake.post("/_admin/journal/limpar")
        self.assertEqual(self.fake.journal(), [])


class CatalogoTest(ComPerfilExemplo, FakeCase):
    def test_toda_rota_marcada_como_implementada_responde(self):
        catalogo = self.fake.get("/_admin/catalog")
        for r in catalogo["rotas"]:
            status, corpo = self.fake.request(r["metodo"], r["caminho"], {} if r["metodo"] == "POST" else None)
            nao_implementada = isinstance(corpo, dict) and "rota não implementada" in str(corpo.get("content", ""))
            self.assertEqual(not nao_implementada, r["implementado"], f"{r['metodo']} {r['caminho']}")

    def test_marca_rotas_que_o_cliente_usa_fora_da_documentacao(self):
        por_caminho = {r["caminho"]: r for r in self.fake.get("/_admin/catalog")["rotas"]}
        self.assertFalse(por_caminho["/appoints/confirm"]["na_documentacao"])
        self.assertTrue(por_caminho["/appoints/new-appoint"]["na_documentacao"])
        self.assertTrue(por_caminho["/appoints/new-appoint"]["uso_cliente"])


class DadosFicticiosSegurosTest(FakeCase):
    def test_todo_cpf_gerado_passa_na_validacao(self):
        from erp_fakes.model import cpf_valido
        cpfs = [p["documentos"]["cpf"] for p in self.fake.model.patients.values()]
        self.assertEqual([c for c in cpfs if not cpf_valido(c)], [])
        self.assertEqual(len(set(cpfs)), len(cpfs))

    def test_telefones_gerados_nunca_sao_celulares_validos(self):
        cels = [p["celular"] for p in self.fake.model.patients.values()]
        self.assertTrue(all(c.startswith("554800") for c in cels))

    def test_cpf_de_paciente_criado_pelo_painel_tambem_e_valido(self):
        from erp_fakes.model import cpf_valido
        prof = self.fake.model.professionals[0]
        r = None
        for horas in range(40, 400):
            try:
                r = self.fake.post("/_admin/schedule", {"profissional_id": prof["profissional_id"], "procedimento_id": 1001,
                                                        "em_horas": horas, "paciente": {"nome": "Sem Cpf"}})
                break
            except FakeErpError as e:
                if e.status != 409:
                    raise
        self.assertIsNotNone(r)
        cpf = self.fake.get("/patient/search", paciente_id=r["paciente_id"])["content"]["documentos"]["cpf"]
        self.assertTrue(cpf_valido(cpf))
        novo = self.fake.post("/_admin/entities/pacientes", {})["id"]
        self.assertTrue(cpf_valido(self.fake.model.patients[novo]["documentos"]["cpf"]))

    def test_validador_reconhece_cpf_real_de_exemplo_publico(self):
        from erp_fakes.model import cpf_valido
        self.assertTrue(cpf_valido("52998224725"))
        self.assertFalse(cpf_valido("52998224726"))
        self.assertFalse(cpf_valido("11111111111"))

    def test_telefones_sao_impossiveis_e_emails_usam_dominio_reservado(self):
        for p in self.fake.model.patients.values():
            self.assertTrue(p["celular"].startswith("554800"), p["celular"])
            self.assertTrue(p["email"].endswith(".invalid"))
        for u in self.fake.model.units:
            self.assertTrue(u["telefone_1"].startswith("(48) 0000"), u["telefone_1"])


class RoteirosTest(ComPerfilExemplo, FakeCase):
    def setUp(self):
        super().setUp()
        self.fake.forget_used_targets()

    def test_lista_os_roteiros(self):
        ids = [r["id"] for r in self.fake.get("/_admin/roteiros")["roteiros"]]
        self.assertIn("preco-do-agendamento", ids)
        self.assertIn("status-da-clinica", ids)

    def test_roteiro_de_preco_muda_o_erp_como_descrito(self):
        ex = self.fake.run_script("preco-do-agendamento")
        a, b, c, d, e, f = (ex["alvos"][k] for k in "abcdef")
        busca = lambda i: self.fake.get("/appoints/search", agendamento_id=i)["content"][0]
        self.assertEqual(busca(a)["valor_total_agendamento"], "R$ 777,00")
        self.assertIsNone(busca(b)["valor_total_agendamento"])
        self.assertEqual(busca(c)["valor_total_agendamento"], "R$ 321,00")
        listados = {i["convenio_id"] for i in self.fake.get("/insurance/list")["content"]}
        self.assertIn(busca(d)["convenio_id"], listados)
        self.assertEqual(busca(f)["valor_total_agendamento"], "R$ 400,00")
        self.assertEqual(set(ex["ids_externos"]), {a, b, c, d, e, f})
        self.assertIn("AND a.id_externo IN", ex["consulta"])
        self.assertIn("a.conta = 1", ex["consulta"])

    def linhas_certas(self, ex):
        linhas = {}
        for v in ex["verificacoes"]:
            linha = linhas.setdefault(str(v["alvo_id"]), {"id_externo": str(v["alvo_id"]), "date": "2026-01-01 10:00:00"})
            if v["campo"] == "price":
                linha["price"] = {"NULL": "NULL", "NAO_ZERO": "50.00"}.get(v["esperado"], v["esperado"])
            elif v["campo"] == "convenio":
                linha["convenio"] = v["esperado"]
        return list(linhas.values())

    def test_avaliacao_passa_quando_o_cliente_gravou_o_esperado(self):
        ex = self.fake.run_script("preco-do-agendamento")
        res = self.fake.evaluate(ex["verificacoes"], self.linhas_certas(ex))
        self.assertEqual({r["resultado"] for r in res}, {"passou"}, res)

    def test_avaliacao_aponta_falha_e_nao_chegou(self):
        ex = self.fake.run_script("preco-do-agendamento")
        linhas = self.linhas_certas(ex)
        alvo_a = ex["alvos"]["a"]
        for l in linhas:
            if l["id_externo"] == str(alvo_a):
                l["price"] = "162.00"
        alvo_f = str(ex["alvos"]["f"])
        linhas = [l for l in linhas if l["id_externo"] != alvo_f]
        res = {r["alvo"]: r["resultado"] for r in self.fake.evaluate(ex["verificacoes"], linhas) if r["campo"] == "price"}
        self.assertEqual((res["a"], res["f"], res["b"]), ("falhou", "não chegou", "passou"))

    def test_valor_zero_gravado_como_zero_falha(self):
        ex = self.fake.run_script("preco-do-agendamento")
        e = ex["alvos"]["e"]
        verif = [v for v in ex["verificacoes"] if v["alvo"] == "e"]
        self.assertEqual(self.fake.evaluate(verif, [{"id_externo": str(e), "price": "0.00"}])[0]["resultado"], "falhou")
        self.assertEqual(self.fake.evaluate(verif, [{"id_externo": str(e), "price": "NULL"}])[0]["resultado"], "passou")

    def test_roteiro_de_status_e_remarcacao(self):
        ex = self.fake.run_script("status-da-clinica")
        busca = lambda i: self.fake.get("/appoints/search", agendamento_id=i)["content"][0]
        self.assertEqual(busca(ex["alvos"]["b"])["status_id"], 11)
        self.assertEqual(busca(ex["alvos"]["c"])["status_id"], 7)
        esperado = next(v["esperado"] for v in ex["verificacoes"] if v["campo"] == "date")
        a = busca(ex["alvos"]["a"])
        d = datetime.strptime(a["data"], "%d-%m-%Y").date().isoformat()
        self.assertEqual(f"{d} {a['horario'][:5]}", esperado)
        # status numéricos do exemplo: 29 DATA_ALTERADA, 7 CANCELADO_PELA_CLINICA, 8 CONFIRMADO_PELA_CLINICA
        linhas = [{"id_externo": str(ex["alvos"]["a"]), "date": esperado + ":00", "status": "29"},
                  {"id_externo": str(ex["alvos"]["b"]), "date": "x", "status": "7"},
                  {"id_externo": str(ex["alvos"]["c"]), "date": "x", "status": "8"}]
        antes = [{"id_externo": str(ex["alvos"][k]), "status": "0"} for k in "abc"]
        res = {(r["alvo"], r["campo"]): r["resultado"] for r in self.fake.evaluate(ex["verificacoes"], linhas, antes)}
        self.assertEqual(set(res.values()), {"passou"}, res)
        errado = [dict(l, status="0") for l in linhas]
        res = {(r["alvo"], r["campo"]): r["resultado"] for r in self.fake.evaluate(ex["verificacoes"], errado, antes)}
        self.assertEqual(res[("b", "status_cliente")], "falhou")
        self.assertEqual(res[("b", "status_mudou")], "falhou")

    def test_roteiro_so_escolhe_agendamento_ainda_nao_confirmado_para_confirmar(self):
        ex = self.fake.run_script("status-da-clinica")
        for k in "bc":
            self.assertEqual(self.fake.model.schedules[ex["alvos"][k]]["status_id"] in (11, 7), True)

    def test_nomes_dos_status_do_perfil(self):
        self.assertEqual((perfil.nome_status(7), perfil.nome_status(8), perfil.nome_status(29)), ("CANCELADO_PELA_CLINICA", "CONFIRMADO_PELA_CLINICA", "DATA_ALTERADA"))
        self.assertEqual(perfil.nome_status(9999), "9999")
        self.assertEqual(self.fake.get("/_admin/status-cliente")["status"][0]["nome"], "CRIADO")

    def test_roteiro_de_agendamento_que_some(self):
        ex = self.fake.run_script("agendamento-some")
        a = ex["alvos"]["a"]
        self.assertEqual(self.fake.get("/appoints/search", agendamento_id=a)["content"], [])
        res = self.fake.evaluate(ex["verificacoes"], [{"id_externo": str(a), "status": "9"}])
        self.assertEqual(res[0]["resultado"], "passou")
        res = self.fake.evaluate(ex["verificacoes"], [{"id_externo": str(a), "status": "7"}])
        self.assertEqual((res[0]["resultado"], res[0]["obtido"]), ("falhou", "CANCELADO_PELA_CLINICA"))

    def test_status_mudou_sem_referencia_nao_e_falha(self):
        ex = self.fake.run_script("status-da-clinica")
        linhas = [{"id_externo": str(ex["alvos"]["b"]), "status": "11"}]
        res = self.fake.evaluate([v for v in ex["verificacoes"] if v["campo"] == "status_mudou" and v["alvo"] == "b"], linhas)
        self.assertEqual(res[0]["resultado"], "sem referência")

    def test_roteiro_nao_repete_agendamento_ja_usado_nem_depois_do_reset(self):
        primeira = self.fake.run_script("preco-do-agendamento")["alvos"]
        self.fake.reset()
        segunda = self.fake.run_script("preco-do-agendamento")["alvos"]
        antigos = {v for k, v in primeira.items() if k != "f"}
        novos = {v for k, v in segunda.items() if k != "f"}
        self.assertFalse(antigos & novos, "o roteiro reaproveitou agendamentos que o cliente já alterou")

    def test_esquecer_agendamentos_usados(self):
        self.fake.run_script("preco-do-agendamento")
        self.assertGreater(self.fake.get("/_admin/roteiros")["usados"], 0)
        self.fake.forget_used_targets()
        self.assertEqual(self.fake.get("/_admin/roteiros")["usados"], 0)

    def test_roteiro_desconhecido(self):
        self.assertEqual(self.fake.request("POST", "/_admin/roteiros/nao-existe/executar", {})[0], 409)


class IdsNovosTest(FakeCase):
    def test_ids_criados_nunca_se_repetem_nem_depois_do_reset(self):
        antes, *_ = self.agendar()
        pac_antes = self.novo_paciente("70707070707")
        self.fake.reset()
        depois, *_ = self.agendar(dia=proximo_dia_util(5))
        pac_depois = self.novo_paciente("80808080808")
        self.assertGreater(depois, antes)
        self.assertGreater(pac_depois, pac_antes)

    def test_ids_novos_ficam_acima_dos_ids_da_carga_inicial(self):
        sid, *_ = self.agendar()
        self.assertGreater(sid, max(s["agendamento_id"] for s in self.fake.schedules() if s["obs"] != "cenario=criado_pelo_cliente"))
        self.assertGreaterEqual(self.novo_paciente("90909090909"), 6001)

    def test_ids_persistem_entre_execucoes(self):
        import tempfile
        from pathlib import Path
        from erp_fakes.idstore import IdStore
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "ids.json"
            a = IdStore(arq).next("schedule")
            b = IdStore(arq).next("schedule")
            self.assertEqual(b, a + 1)


class TunelExistenteTest(unittest.TestCase):
    def test_opcao_aproveita_tunel_aberto_por_outro_processo(self):
        import subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as home:
            ajuda = subprocess.run([sys.executable, "-m", "erp_fakes", "--help"], capture_output=True, text=True,
                                   env={"HOME": home, "PATH": "/usr/bin:/bin"}, timeout=30).stdout
        self.assertIn("--existing-tunnel", ajuda)


class AvisosDoLauncherTest(ComPerfilExemplo, unittest.TestCase):
    def setUp(self):
        from erp_fakes import launcher
        self.launcher = launcher
        self.agora = time.time()
        launcher.tunnel.update(status="conectado", url="https://abc-def.trycloudflare.com", error=None)
        launcher.state.update(token="t", ack_url=None)

    def chamada(self, status=200, host="abc-def.trycloudflare.com", segundos_atras=1, falha=None):
        return {"tunel": True, "host": host, "status": status, "t": self.agora - segundos_atras, "falha": falha}

    def titulos(self, journal):
        return [perfil.aplicar(a["titulo"]) for a in self.launcher.alerts(journal)]

    def test_url_nova_pede_atualizacao_na_conta(self):
        self.assertIn("URL desatualizada na conta", self.titulos([]))

    def test_chamada_pela_url_atual_confirma_sozinha(self):
        self.assertEqual(self.titulos([self.chamada()]), ["Tudo certo"])

    def test_chave_recusada_na_ultima_chamada_avisa_e_some_depois_de_acerto(self):
        self.assertIn("Token diferente na conta", self.titulos([self.chamada(403)]))
        self.assertNotIn("Token diferente na conta", self.titulos([self.chamada(403), self.chamada(200)]))

    def test_tunel_caido(self):
        self.launcher.tunnel["status"] = "caiu"
        self.assertIn("Túnel fora do ar", self.titulos([]))

    def test_falha_simulada_ativa_e_lembrada(self):
        self.assertIn("Falha simulada ativa", self.titulos([self.chamada(503, falha="status 503")]))

    def test_carga_em_andamento_so_com_atividade_recente_e_intensa(self):
        agora = time.time()
        ativa = [self.chamada(segundos_atras=i) for i in range(1, 9)]
        self.assertTrue(self.launcher.carga_em_andamento(ativa, agora))
        self.assertIn("Carga do sistema integrado em andamento", self.titulos(ativa))
        parada = [self.chamada(segundos_atras=60 + i) for i in range(1, 9)]
        self.assertFalse(self.launcher.carga_em_andamento(parada, agora))
        poucas = [self.chamada(segundos_atras=2)]
        self.assertFalse(self.launcher.carga_em_andamento(poucas, agora))

    def test_sem_chamadas_ha_muito_tempo(self):
        self.launcher.state["ack_url"] = self.launcher.tunnel["url"]
        self.assertIn("Sem chamadas do sistema integrado há mais de 15 minutos", self.titulos([self.chamada(segundos_atras=1200)]))


if __name__ == "__main__":
    unittest.main()


class HorariosNaTelaTest(FakeCase):
    def test_grade_mostra_livres_e_ocupados(self):
        m = self.fake.model
        prof = next(p for p in m.professionals if p["unidades"])
        r = self.fake.get("/_admin/horarios", profissional_id=prof["profissional_id"], unidade_id=prof["unidades"][0], dias=7)
        self.assertTrue(r["atende_na_unidade"])
        self.assertTrue(any(d["livres"] for d in r["dias"]))
        self.assertTrue(all(len(h) == 5 for d in r["dias"] for h in d["livres"]))

    def test_profissional_inexistente_da_409(self):
        self.assertEqual(self.fake.request("GET", "/_admin/horarios?profissional_id=1&unidade_id=101")[0], 409)
