import json
import re
import unittest

from erp_fakes.dados import celular_seguro
from erp_fakes.model import cpf_valido
from erp_fakes.testing import FakeErp, FakeErpError


class VolumeTest(unittest.TestCase):
    def test_acrescentar_cria_com_ids_novos_e_dados_seguros(self):
        with FakeErp(patients=50, schedules=80) as f:
            antes = {"pacientes": len(f.model.patients), "agendamentos": len(f.model.schedules), "profissionais": len(f.model.professionals)}
            r = f.post("/_admin/volume", {"modo": "acrescentar", "pacientes": 300, "profissionais": 5, "agendamentos": 200, "dias": 10, "semente": 7})
            self.assertEqual(r["criados"], {"pacientes": 300, "profissionais": 5, "agendamentos": 200})
            self.assertEqual(len(f.model.patients), antes["pacientes"] + 300)
            self.assertEqual(len(f.model.professionals), antes["profissionais"] + 5)
            self.assertEqual(len(f.model.schedules), antes["agendamentos"] + 200)
            novos = sorted(f.model.patients)[-300:]
            self.assertTrue(all(i >= 6001 for i in novos))
            for i in novos:
                p = f.model.patients[i]
                self.assertTrue(celular_seguro(p["celular"]))
                self.assertTrue(cpf_valido(p["documentos"]["cpf"]))
                self.assertTrue(p["email"].endswith("@teste.invalid"))
            self.assertEqual(len(set(f.model.schedules)), len(f.model.schedules))

    def test_limites_e_pedido_invalido(self):
        with FakeErp(patients=20, schedules=20) as f:
            self.assertEqual(f.request("POST", "/_admin/volume", {"modo": "acrescentar", "pacientes": 999999})[0], 422)
            self.assertEqual(f.request("POST", "/_admin/volume", {"modo": "outro"})[0], 422)

    def test_regerar_muda_o_tamanho_e_o_reset_mantem(self):
        with FakeErp(patients=30, schedules=40) as f:
            r = f.post("/_admin/volume", {"modo": "regerar", "pacientes": 120, "agendamentos": 300, "profissionais": 60, "unidades": 2, "dias": 7})
            self.assertEqual(r["totais"], {"unidades": 2, "profissionais": 60, "pacientes": 120, "agendamentos": 300})
            f.reset()
            self.assertEqual(len(f.model.professionals), 60)
            self.assertEqual(len(f.model.patients), 120)

    def test_volume_vale_para_netpacs_com_as_rotas_dele(self):
        with FakeErp(erp="netpacs", patients=30, schedules=40) as f:
            f.post("/_admin/volume", {"modo": "acrescentar", "pacientes": 100, "agendamentos": 500, "dias": 5})
            from datetime import date, timedelta
            hoje = date.today()
            total = 0
            for pag in range(1, 40):
                itens = f.get("/netris/api/atendimentos", dataInicial=hoje.strftime("%d/%m/%Y"),
                              dataFinal=(hoje + timedelta(days=5)).strftime("%d/%m/%Y"), limit=100, page=pag)
                total += len(itens)
                if len(itens) < 100:
                    break
            self.assertGreater(total, 100)


class ImportacaoTest(unittest.TestCase):
    def setUp(self):
        self.f = FakeErp(patients=40, schedules=60).start()

    def tearDown(self):
        self.f.stop()

    def importa(self, texto, **kw):
        return self.f.post("/_admin/importar", {"texto": texto, **kw})

    def test_simular_nao_altera_nada(self):
        antes = len(self.f.model.patients)
        r = self.importa(json.dumps({"pacientes": [{"nome": "Maria Teste", "celular": "5548000000999"}]}), simular=True)
        self.assertEqual(r["criados"]["pacientes"], 1)
        self.assertTrue(r["simulado"])
        self.assertEqual(len(self.f.model.patients), antes)

    def test_importar_de_verdade_cria_paciente_seguro(self):
        r = self.importa(json.dumps({"pacientes": [{"nome": "Maria Teste", "cpf": "", "celular": ""}]}), simular=False)
        self.assertEqual(r["total_erros"], 0)
        p = next(x for x in self.f.model.patients.values() if x["nome"] == "Maria Teste")
        self.assertTrue(celular_seguro(p["celular"]))
        self.assertTrue(cpf_valido(p["documentos"]["cpf"]))

    def test_telefone_real_e_recusado_salvo_permissao(self):
        corpo = json.dumps({"pacientes": [{"nome": "Com Telefone", "celular": "5561999998888"}]})
        r = self.importa(corpo, simular=True)
        self.assertEqual(r["criados"]["pacientes"], 0)
        self.assertIn("padrão seguro", r["erros"][0]["mensagem"])
        r = self.importa(corpo, simular=True, permitir_telefone_real=True)
        self.assertEqual(r["criados"]["pacientes"], 1)

    def test_csv_com_vinculos_por_nome(self):
        self.importa("nome_fantasia,cidade\nClínica Importada Norte,Joinville", formato="csv", entidade="unidades", simular=False)
        self.importa("nome\nReumatologia", formato="csv", entidade="especialidades", simular=False)
        self.importa("nome,planos\nConvênio Importado,Básico|Plus", formato="csv", entidade="convenios", simular=False)
        r = self.importa("nome;sexo;unidades;especialidades;convenios\nDra. Importada;F;Clínica Importada Norte;Reumatologia;Convênio Importado",
                         formato="csv", entidade="profissionais", simular=False)
        self.assertEqual(r["total_erros"], 0, r)
        prof = next(p for p in self.f.model.professionals if p["nome"] == "Dra. Importada")
        self.assertEqual(prof["especialidades"][0]["nome"], "Reumatologia")
        self.assertEqual(prof["convenios"][0]["nome"], "Convênio Importado")
        conv = next(i for i in self.f.model.insurances if i["nome"] == "Convênio Importado")
        self.assertEqual([pl["plano"] for pl in conv["planos"]], ["Convênio Importado Básico", "Convênio Importado Plus"])

    def test_erros_por_linha_com_mensagem_clara(self):
        corpo = json.dumps({"pacientes": [{"nome": ""}, {"nome": "Ok"}, {"nome": "Cpf Curto", "cpf": "123"}],
                            "profissionais": [{"nome": "Sem Unidade", "unidades": "Unidade Que Nao Existe"}]})
        r = self.importa(corpo, simular=True)
        msgs = {(e["entidade"], e["linha"]): e["mensagem"] for e in r["erros"]}
        self.assertIn("obrigatórios", msgs[("pacientes", 1)])
        self.assertIn("11 dígitos", msgs[("pacientes", 3)])
        self.assertIn("Unidade não encontrado", msgs[("profissionais", 1)].replace("Unidade não encontrada", "Unidade não encontrado"))
        self.assertEqual(r["criados"]["pacientes"], 1)

    def test_formato_invalido(self):
        self.assertEqual(self.f.request("POST", "/_admin/importar", {"texto": "{quebrado"})[0], 422)
        self.assertEqual(self.f.request("POST", "/_admin/importar", {"texto": '{"coisas": []}'})[0], 422)
        self.assertEqual(self.f.request("POST", "/_admin/importar", {"texto": "a,b\n1,2", "formato": "csv"})[0], 422)

    def test_agendamento_importado_vira_registro_com_cenario_importado(self):
        prof = self.f.model.professionals[0]
        pac = next(iter(self.f.model.patients))
        proc = self.f.model.procedures[0]
        from datetime import date, timedelta
        d = (date.today() + timedelta(days=20)).isoformat()
        r = self.importa(json.dumps({"agendamentos": [{"paciente": pac, "profissional": prof["profissional_id"], "procedimento": proc["nome"],
                                                        "data": d, "horario": "10:20", "valor": "R$ 250,00"}]}), simular=False)
        self.assertEqual(r["total_erros"], 0, r)
        s = next(x for x in self.f.model.schedules.values() if x["scenario"] == "importado")
        self.assertEqual(s["valor_total_agendamento"], "R$ 250,00")
        r2 = self.importa(json.dumps({"agendamentos": [{"paciente": pac, "profissional": prof["profissional_id"], "procedimento": proc["nome"],
                                                         "data": d, "horario": "10:20"}]}), simular=True)
        self.assertIn("ocupado", r2["erros"][0]["mensagem"])

    def test_exportar_e_importar_substituindo_reproduz_os_dados(self):
        exportado = self.f.get("/_admin/exportar")
        self.assertEqual(exportado["formato"], "erp-fakes/1")
        with FakeErp(patients=5, schedules=5) as g:
            r = g.post("/_admin/importar", {"texto": json.dumps(exportado), "modo": "substituir", "simular": False})
            for ent in ("unidades", "especialidades", "convenios", "procedimentos", "profissionais", "pacientes"):
                self.assertEqual(r["criados"][ent], len(exportado[ent]), ent)
            esperados = {e["mensagem"] for e in r["erros"]}
            self.assertTrue(all("ocupado" in m or "Convênio não encontrado" in m for m in esperados), esperados)
            self.assertEqual(r["criados"]["agendamentos"] + r["total_erros"], len(exportado["agendamentos"]))
            self.assertEqual(sorted(g.model.patients), sorted(self.f.model.patients))

    def test_modelos_trazem_prompt_com_as_regras_de_seguranca(self):
        m = self.f.get("/_admin/modelos")
        self.assertIn("554800", m["prompt"])
        self.assertIn("@teste.invalid", m["prompt"])
        self.assertEqual(set(m["entidades"]), {"unidades", "especialidades", "convenios", "procedimentos", "profissionais", "pacientes", "agendamentos"})
        for ent, info in m["entidades"].items():
            self.assertTrue(info["csv"].splitlines()[0].startswith("id,"), ent)
            r = self.importa(info["csv"], formato="csv", entidade=ent, simular=True)
            self.assertIsNotNone(r["criados"])


if __name__ == "__main__":
    unittest.main()
