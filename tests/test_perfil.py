import base64
import hashlib
import hmac
import json
import re
import unittest
from pathlib import Path

from helpers import ComPerfilExemplo
from erp_fakes import FakeErp, perfil
from erp_fakes.erp_tasy import jwt_valido

RAIZ = Path(__file__).resolve().parent.parent / "erp_fakes"


def jwt_com_emissor(chave, emissor):
    def b64(x):
        return base64.urlsafe_b64encode(x).rstrip(b"=").decode()
    cab = b64(json.dumps({"alg": "HS256"}).encode())
    corpo = b64(json.dumps({"iss": emissor, "exp": 4102444800}).encode())
    return f"{cab}.{corpo}.{b64(hmac.new(chave.encode(), f'{cab}.{corpo}'.encode(), hashlib.sha256).digest())}"


class PerfilGenericoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        perfil.ativar("")
        cls.fake = FakeErp(patients=20, schedules=60).start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def test_vocabulario_neutro(self):
        self.assertEqual(perfil.aplicar("Carga [[do_cliente]] e [[O_cliente]]"), "Carga do sistema integrado e O sistema integrado")

    def test_sem_roteiros_nem_status_nem_consulta(self):
        self.assertEqual(self.fake.get("/_admin/roteiros")["roteiros"], [])
        self.assertEqual(self.fake.get("/_admin/status-cliente")["status"], [])
        self.assertIsNone(self.fake.post("/_admin/conferencia/consulta", {"ids": [1]})["consulta"])

    def test_respostas_da_api_nao_vazam_marcadores_nem_nome_de_empresa(self):
        docs = json.dumps(self.fake.get("/_admin/catalog"), ensure_ascii=False)
        self.assertNotIn("[[", docs)
        self.assertNotRegex(docs, r"(?i)nina")

    def test_perfil_inexistente(self):
        with self.assertRaises(ValueError):
            perfil.ativar("modulo_que_nao_existe_xyz")
        self.assertEqual(perfil.ativo().nome, "generico")

    def test_jwt_do_tasy_nao_exige_emissor_especifico(self):
        self.assertTrue(jwt_valido(jwt_com_emissor("k" * 32, "qualquer"), "k" * 32))


class PerfilExemploTest(ComPerfilExemplo, unittest.TestCase):
    def test_tem_roteiros_status_e_consulta(self):
        p = perfil.ativo()
        self.assertTrue(p.roteiros)
        self.assertEqual((perfil.nome_status(7), perfil.nome_status(29), perfil.nome_status(5)), ("CANCELADO_PELA_CLINICA", "DATA_ALTERADA", "5"))
        self.assertIn("a.id_externo IN ('10','11')", p.consulta(["10", "11"], 1))

    def test_emissor_do_jwt_pode_ser_exigido_pelo_perfil(self):
        antigo = perfil.ativo().emissor_jwt
        perfil.ativo().emissor_jwt = "meu-sistema"
        try:
            self.assertTrue(jwt_valido(jwt_com_emissor("k" * 32, "meu-sistema"), "k" * 32))
            self.assertFalse(jwt_valido(jwt_com_emissor("k" * 32, "outro"), "k" * 32))
        finally:
            perfil.ativo().emissor_jwt = antigo


class HigieneDoNucleoTest(unittest.TestCase):
    """O código não pode citar empresas, cards ou servidores internos."""
    PERMITIDO = set()

    def test_nucleo_sem_nomes_internos(self):
        achados = []
        for arq in list(RAIZ.rglob("*.py")) + [RAIZ / "app.html"]:
            if arq.name in self.PERMITIDO:
                continue
            for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"nina|SD-\d+|CLINICA_SIM|ssh |confirmationcall", linha, re.I):
                    achados.append(f"{arq.name}:{n}: {linha.strip()[:90]}")
        self.assertEqual(achados, [])


if __name__ == "__main__":
    unittest.main()
