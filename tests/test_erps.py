import unittest
from datetime import date, datetime, timedelta, timezone

from helpers import ComPerfilExemplo
from erp_fakes.model import sdate
from erp_fakes.testing import FakeErp, FakeErpError

BRT = timezone(timedelta(hours=-3))


def br(d):
    return d.strftime("%d/%m/%Y")


class NetpacsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeErp(erp="netpacs").start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def lista(self, **extra):
        hoje = date.today()
        return self.fake.get("/netris/api/atendimentos", dataInicial=br(hoje), dataFinal=br(hoje + timedelta(days=14)), **extra)

    def test_sem_chave_401_e_chave_errada_403(self):
        self.assertEqual(self.fake.request("GET", "/netris/api/unidades", token="")[0], 401)
        self.assertEqual(self.fake.request("GET", "/netris/api/unidades", token="errada")[0], 403)

    def test_dados_proprios_do_erp(self):
        self.assertTrue(all("NetPacs" in u["nome_fantasia"] for u in self.fake.model.units))
        self.assertEqual({u["unidade_id"] for u in self.fake.model.units}, {301, 302, 303})

    def test_carga_devolve_array_paginado_com_campos_obrigatorios(self):
        itens = self.lista(limit=100, page=1)
        self.assertEqual(len(itens), 100)
        for a in itens:
            for campo in ("idAtendimentoProcedimento", "data", "horaInicial", "nomeSituacao", "nomeFilial", "nomeProcedimento", "nomePaciente"):
                self.assertIsNotNone(a[campo], campo)
        total = sum(len(self.lista(limit=100, page=p)) for p in range(1, 30))
        esperado = sum(1 for s in self.fake.model.schedules.values()
                       if date.today() <= sdate(s) <= date.today() + timedelta(days=14))
        self.assertEqual(total, esperado)
        self.assertEqual(self.lista(limit=100, page=99), [])

    def test_data_e_hora_seguem_a_conversao_do_cliente(self):
        a = self.lista(limit=5)[0]
        s = self.fake.model.schedules[a["idAtendimentoProcedimento"]]
        dia = datetime.fromtimestamp((a["data"] + 3 * 3600 * 1000) / 1000, BRT).date()
        hora = datetime.fromtimestamp(a["horaInicial"] / 1000, BRT)
        self.assertEqual(dia, sdate(s))
        self.assertEqual(f"{hora:%H:%M}", s["horario"][:5])

    def test_valor_do_erp_vira_numero_em_reais(self):
        s = next(x for x in self.fake.model.schedules.values() if x["scenario"] == "particular_com_valor_erp")
        a = self.fake.get(f"/netris/api/atendimentos/{s['agendamento_id']}")
        self.assertIsInstance(a["valorProcedimento"], float)
        self.assertGreater(a["valorProcedimento"], 0)
        sem = next(x for x in self.fake.model.schedules.values() if x["scenario"] == "particular_sem_valor_erp")
        self.assertIsNone(self.fake.get(f"/netris/api/atendimentos/{sem['agendamento_id']}")["valorProcedimento"])

    def test_atendimento_inexistente_404(self):
        self.assertEqual(self.fake.request("GET", "/netris/api/atendimentos/1")[0], 404)

    def test_confirmar_e_cancelar(self):
        s = next(x for x in self.fake.model.schedules.values() if x["status_id"] == 1)
        sid = s["agendamento_id"]
        self.fake.patch(f"/netris/api/atendimentos/{sid}/alterar-situacao", {"idSituacao": "3"})
        self.assertEqual(self.fake.get(f"/netris/api/atendimentos/{sid}")["nomeSituacao"], "Confirmado")
        self.fake.patch(f"/netris/api/atendimentos/{sid}/cancelar", {"idMotivoSituacao": "1", "observacao": "teste"})
        a = self.fake.get(f"/netris/api/atendimentos/{sid}")
        self.assertTrue(a["cancelado"])
        self.assertTrue(a["nomeSituacao"].startswith("Cancelado"))

    def test_paciente_criar_devolve_id_como_texto_e_busca_por_cpf(self):
        r = self.fake.post("/netris/api/pacientes", {"nomePaciente": "Novo NetPacs", "cpf": "52998224725", "telefoneCelular": "554800000001",
                                                    "dataNascimentoPaciente": "10/02/1990", "sexoPaciente": "F"})
        self.assertIsInstance(r["idPaciente"], str)
        achou = self.fake.get("/netris/api/pacientes", cpf="eq:52998224725")
        self.assertEqual(achou[0]["id_paciente"], int(r["idPaciente"]))
        self.assertEqual(self.fake.get("/netris/api/pacientes", cpf="eq:00000000000"), [])

    def test_horarios_agendar_e_horario_ocupado(self):
        pac = next(iter(self.fake.model.patients))
        livres = self.fake.get("/netris/api/horarios", dataBusca=br(date.today()), listIdProcedimento="1001")
        self.assertIsInstance(livres[0], list)
        h = livres[0][0]
        corpo = [{"idConvenio": "1", "idPaciente": str(pac), "listHorarioDTO": [{
            "dataString": h["dataString"], "horaInicialString": h["horaInicialString"], "idMedico": str(h["idMedico"]),
            "idEscala": str(h["idEscala"]), "idSala": str(h["idSala"]), "duracaoProcedimento": "20", "idProcedimento": "1001"}]}]
        r = self.fake.post("/netris/api/horarios", corpo)
        sid = int(r["message"].split("ID: ")[1])
        self.assertEqual(self.fake.model.schedules[sid]["paciente_id"], pac)
        status, resp = self.fake.request("POST", "/netris/api/horarios", corpo)
        self.assertEqual(status, 409)
        self.assertIn("já foi ocupado", resp["message"])

    def test_preco_de_tabela(self):
        r = self.fake.get("/netris/api/consultarPreco", idProcedimento="1001", idPlanoConvenio="401", dataString=br(date.today()))
        self.assertGreater(r["valorTotal"], 0)

    def test_carga_vazia_devolve_array(self):
        self.fake.fault("/netris/api/atendimentos", "vazio")
        try:
            self.assertEqual(self.lista(), [])
        finally:
            self.fake.clear_faults()

    def test_diario_marca_o_erp(self):
        self.fake.get("/netris/api/unidades")
        self.assertEqual(self.fake.journal(caminho="/netris/api/unidades", erp="netpacs")[0]["erp"], "netpacs")


class TasyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeErp(erp="tasy").start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def test_jwt_obrigatorio_e_conferido(self):
        self.assertEqual(self.fake.request("GET", "/codestatus", token="")[0], 401)
        self.assertEqual(self.fake.request("GET", "/codestatus", token="Basic x.y.z")[0], 401)
        self.assertEqual(self.fake.request("GET", "/codestatus")[0], 200)

    def test_jwt_aceita_hs256_hs384_e_hs512_conforme_o_tamanho_da_chave(self):
        from erp_fakes.erp_tasy import jwt_valido
        from erp_fakes.testing import gera_jwt
        for n in (32, 48, 64, 80):
            chave = "k" * n
            self.assertTrue(jwt_valido(gera_jwt(chave), chave), n)
            self.assertFalse(jwt_valido(gera_jwt(chave), chave + "x"), n)

    def test_carga_de_consultas_tem_tudo_embutido(self):
        itens = self.fake.get("/schedules", exams="false", maxDays=7, id_agendamento="null", companyCustomIds="null")
        self.assertTrue(itens)
        for a in itens[:30]:
            for campo in ("id", "compId", "compName", "resourceId", "resourceName", "typeName", "clientId", "clientName", "status", "date"):
                self.assertIsNotNone(a[campo], campo)
        self.assertEqual(self.fake.get("/schedules", exams="true", maxDays=7), [])

    def test_max_days_e_id_agendamento(self):
        poucos = self.fake.get("/schedules", exams="false", maxDays=2)
        muitos = self.fake.get("/schedules", exams="false", maxDays=14)
        self.assertLess(len(poucos), len(muitos))
        alvo = muitos[0]["id"]
        um = self.fake.get("/schedules", exams="false", maxDays=360, id_agendamento=alvo, companyCustomIds="null")
        self.assertEqual([x["id"] for x in um], [alvo])

    def test_price_do_sd1320_vem_do_valor_do_erp_como_texto(self):
        s = next(x for x in self.fake.model.schedules.values() if x["scenario"] == "particular_com_valor_erp" and x["status_id"] != 16)
        a = self.fake.get("/schedules", exams="false", maxDays=360, id_agendamento=s["agendamento_id"], companyCustomIds="null")[0]
        self.assertEqual(a["price"], s["valor_total_agendamento"])
        sem = next(x for x in self.fake.model.schedules.values() if x["scenario"] == "particular_sem_valor_erp" and x["status_id"] != 16)
        b = self.fake.get("/schedules", exams="false", maxDays=360, id_agendamento=sem["agendamento_id"], companyCustomIds="null")[0]
        self.assertIsNone(b["price"])
        num = next(x for x in self.fake.model.schedules.values() if x["scenario"] == "valor_numerico_json" and x["status_id"] != 16)
        n = self.fake.get("/schedules", exams="false", maxDays=360, id_agendamento=num["agendamento_id"], companyCustomIds="null")[0]
        self.assertRegex(n["price"], r"^\d+\.\d{2}$")

    def test_confirmar_cancelar_e_respostas_em_texto(self):
        s = next(x for x in self.fake.model.schedules.values() if x["status_id"] == 1)
        sid = s["agendamento_id"]
        self.assertEqual(self.fake.post(f"/schedules/{sid}/confirm", system="WHATSAPP", desc="ok", exam="false"), "OK")
        self.assertEqual(self.fake.model.schedules[sid]["status_id"], 7)
        self.assertEqual(self.fake.delete(f"/schedules/{sid}/cancel", system="WHATSAPP", desc="x", exam="false"), "OK")
        self.assertEqual(self.fake.post(f"/schedules/{sid}/confirm"), "NOT_VALID_STATUS=C")
        self.assertEqual(self.fake.post("/schedules/1/confirm"), "NOT_FOUND")

    def test_sumido_vira_objeto_vazio_e_transferido_vira_texto(self):
        a, b = [x for x in self.fake.model.schedules.values() if x["status_id"] == 1][:2]
        self.fake.action(a["agendamento_id"], "sumir")
        self.assertEqual(self.fake.get(f"/schedules/{a['agendamento_id']}/confirmStatus", exam="false"), {})
        self.assertIsNone(self.fake.get(f"/schedules/{a['agendamento_id']}/transfer", agenda="1", exam="false"))
        b["status_id"] = 16
        self.assertIn("Transferido", self.fake.get(f"/schedules/{b['agendamento_id']}/transfer", agenda="1", exam="false"))
        ids = [x["id"] for x in self.fake.get("/schedules", exams="false", maxDays=30)]
        self.assertNotIn(str(b["agendamento_id"]), ids)

    def test_status_em_lote_recebe_texto(self):
        ids = [str(s["agendamento_id"]) for s in list(self.fake.model.schedules.values())[:3]]
        r = self.fake.post("/schedulesStatus/schedule", ",".join(ids))
        self.assertEqual(set(r), set(ids))
        self.assertTrue(all(v.endswith((";true", ";false")) for v in r.values()))

    def test_cliente_por_cpf_e_cadastro(self):
        p = next(iter(self.fake.model.patients.values()))
        c = self.fake.get("/client", CPF=p["documentos"]["cpf"], CD_USUARIO_CONVENIO="")
        self.assertEqual(c["ID_PACIENTE"], str(p["paciente_id"]))
        self.assertTrue(c["NM_PESSOA_FISICA_P"])
        self.assertEqual(self.fake.get("/client", CPF="00000000000", CD_USUARIO_CONVENIO=""), {})
        self.assertEqual(self.fake.post("/register_client", clientName="Novo Tasy", clientCPF="52998224725", clientBirthdate="634953600000",
                                        clientGender="F", clientPhone="554800000002"), "OK")
        self.assertTrue(self.fake.get("/client", CPF="52998224725", CD_USUARIO_CONVENIO="")["ID_PACIENTE"])

    def test_agendar_em_horario_livre_aparece_na_carga_com_o_mesmo_id(self):
        p = next(iter(self.fake.model.patients.values()))
        hs = self.fake.get("/free_hours", company=self.fake.model.units[0]["unidade_id"], expertiseId="null", agendaType="N",
                           crmDoctor="null", resourceCustomId="null")
        h = hs[0]
        r = self.fake.post("/register_schedule_with_client_data", nr_sequencia=h["hourId"], clientName=p["nome"], clientCPF=p["documentos"]["cpf"],
                           clientGender="F", clientPhone="1", paymentTypeCustomId="")
        self.assertEqual(r, "OK")
        achou = self.fake.get("/schedules", exams="false", maxDays=60, id_agendamento=h["hourId"], companyCustomIds="null")
        self.assertEqual(len(achou), 1)
        self.assertEqual(achou[0]["clientName"], p["nome"])
        self.assertEqual(achou[0]["date"], h["hour"])
        self.assertEqual(self.fake.post("/register_schedule_with_client_data", nr_sequencia=h["hourId"], clientName=p["nome"],
                                        clientCPF=p["documentos"]["cpf"], clientGender="F", clientPhone="1"), "OCCUPIED")

    def test_reagendar_move_para_o_horario_escolhido(self):
        s = next(x for x in self.fake.model.schedules.values() if x["status_id"] == 1 and sdate(x) >= date.today())
        unidade = s["unidade_id"]
        hs = self.fake.get("/free_hours", company=unidade, expertiseId="null", agendaType="N", crmDoctor="null", resourceCustomId="null")
        destino = hs[-1]
        self.assertEqual(self.fake.post("/reschedule", id=s["agendamento_id"], toId=destino["hourId"]), "OK")
        self.assertEqual(int(self.fake.get(f"/schedules/{s['agendamento_id']}/confirmStatus", exam="false")["dt_agenda"][:4]) > 2000, True)

    def test_preco_em_centavos_e_vazio_sem_preco(self):
        r = self.fake.get("/price", customPaymentTypeId=201, customScheduleTypeId="1001;0", customCompanyId=501)
        self.assertTrue(r["inCents"])
        self.assertGreater(r["price"], 0)
        self.assertEqual(self.fake.get("/price", customPaymentTypeId=201, customScheduleTypeId="9", customCompanyId=501), {})

    def test_cadastros_auxiliares_vazios(self):
        self.assertEqual(self.fake.post("/selectGeneric/AGENDAS", []), [])
        self.assertEqual(self.fake.get("/agenda/blocks", agendas="1"), {})
        self.assertEqual(self.fake.get("/professionals_available"), [])


class SeparacaoEntreErpsTest(unittest.TestCase):
    def test_cada_erp_tem_dados_e_falhas_proprios(self):
        with FakeErp(erp="netpacs") as n:
            n.fault("*", "status", 502)
            self.assertEqual(n.request("GET", "/netris/api/unidades")[0], 502)
            self.assertEqual(n.model.units[0]["unidade_id"], 301)
        with FakeErp(erp="feegow") as f:
            self.assertEqual(f.model.units[0]["unidade_id"], 101)
            self.assertEqual(f.request("GET", "/company/list-unity")[0], 200)


if __name__ == "__main__":
    unittest.main()


class RoteirosPorErpTest(ComPerfilExemplo, unittest.TestCase):
    def test_roteiro_de_preco_existe_nos_tres_erps(self):
        for erp in ("feegow", "netpacs", "tasy"):
            with FakeErp(erp=erp) as f:
                self.assertIn("preco-do-agendamento", [r["id"] for r in f.get("/_admin/roteiros")["roteiros"]], erp)

    def test_agendamento_some_tem_expectativa_propria_do_netpacs(self):
        with FakeErp(erp="netpacs", patients=300, schedules=1500) as n:
            ex = n.run_script("agendamento-some")
            self.assertEqual([v["esperado"] for v in ex["verificacoes"]], ["CANCELADO_PELA_CLINICA"])
        with FakeErp(erp="tasy", patients=300, schedules=1500) as t:
            ex = t.run_script("agendamento-some")
            self.assertEqual([v["esperado"] for v in ex["verificacoes"]], ["REMARCADO_PELA_CLINICA"])

    def test_status_da_clinica_no_tasy_nao_espera_data_alterada(self):
        with FakeErp(erp="tasy", patients=300, schedules=1500) as t:
            ex = t.run_script("status-da-clinica")
            self.assertNotIn("DATA_ALTERADA", [v["esperado"] for v in ex["verificacoes"]])


class RoteirosDePrecoTest(ComPerfilExemplo, unittest.TestCase):
    def test_formatos_de_valor_aplicam_os_textos_no_tasy_e_no_feegow(self):
        for erp in ("tasy", "feegow"):
            with FakeErp(erp=erp, patients=300, schedules=1500) as f:
                ex = f.run_script("formatos-de-valor")
                a, b = ex["alvos"]["a"], ex["alvos"]["b"]
                self.assertEqual(f.model.schedules[a]["valor_total_agendamento"], "1.500")
                self.assertEqual(f.model.schedules[b]["valor_total_agendamento"], "1.50")
                self.assertEqual(len(ex["verificacoes"]), 7)
                if erp == "tasy":
                    r = f.get("/schedules", exams="false", maxDays=360, id_agendamento=a, companyCustomIds="null")
                    self.assertEqual(r[0]["price"], "1.500")

    def test_avaliador_dos_limites(self):
        from erp_fakes import roteiros
        v = [{"alvo": "f", "alvo_id": 1, "campo": "price", "esperado": "NAO_NEGATIVO", "explica": ""},
             {"alvo": "g", "alvo_id": 2, "campo": "price", "esperado": "NAO_ACIMA_DO_LIMITE", "explica": ""}]
        ok = roteiros.avaliar(v, [{"id_externo": "1", "price": "NULL"}, {"id_externo": "2", "price": "45.00"}])
        self.assertEqual([x["resultado"] for x in ok], ["passou", "passou"])
        mal = roteiros.avaliar(v, [{"id_externo": "1", "price": "-50.00"}, {"id_externo": "2", "price": "100000.00"}])
        self.assertEqual([x["resultado"] for x in mal], ["falhou", "falhou"])

    def test_troca_de_procedimento_so_no_tasy_e_espera_o_preco_de_tabela_novo(self):
        with FakeErp(erp="feegow") as f:
            self.assertEqual(f.request("POST", "/_admin/roteiros/troca-de-procedimento/executar", {})[0], 409)
        with FakeErp(erp="tasy", patients=300, schedules=1500) as t:
            ex = t.run_script("troca-de-procedimento")
            s = t.model.schedules[ex["alvos"]["a"]]
            base = next(p["base"] for p in t.model.procedures if p["procedimento_id"] == s["procedimento_id"])
            self.assertEqual(ex["verificacoes"][0]["esperado"], f"{base / 100:.2f}")
            self.assertIsNone(s["valor_total_agendamento"])
