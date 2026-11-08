import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from erp_fakes import tunel_bin


class ArquivoReleaseTest(unittest.TestCase):
    def test_mapeia_sistemas(self):
        self.assertEqual(tunel_bin.arquivo_release("Linux", "x86_64"), "cloudflared-linux-amd64")
        self.assertEqual(tunel_bin.arquivo_release("Linux", "aarch64"), "cloudflared-linux-arm64")
        self.assertEqual(tunel_bin.arquivo_release("Darwin", "arm64"), "cloudflared-darwin-arm64.tgz")
        self.assertEqual(tunel_bin.arquivo_release("Windows", "AMD64"), "cloudflared-windows-amd64.exe")

    def test_sem_build(self):
        self.assertIsNone(tunel_bin.arquivo_release("Linux", "riscv64"))
        self.assertIsNone(tunel_bin.arquivo_release("FreeBSD", "x86_64"))


class InstalarTest(unittest.TestCase):
    def test_instala_binario_direto(self):
        def baixar(url, saida):
            self.assertTrue(url.endswith("cloudflared-linux-amd64"))
            Path(saida).write_bytes(b"#!/bin/sh\n")

        with tempfile.TemporaryDirectory() as d, mock.patch.object(tunel_bin, "arquivo_release", return_value="cloudflared-linux-amd64"):
            destino = Path(d) / "bin" / "cloudflared"
            self.assertEqual(tunel_bin.instalar(destino, baixar), str(destino))
            self.assertEqual(destino.read_bytes(), b"#!/bin/sh\n")
            self.assertTrue(destino.stat().st_mode & 0o100)
            self.assertFalse(destino.with_name("cloudflared.parcial").exists())

    def test_instala_de_tgz(self):
        def baixar(url, saida):
            with tempfile.TemporaryDirectory() as t:
                conteudo = Path(t) / "cloudflared"
                conteudo.write_bytes(b"binario")
                with tarfile.open(saida, "w:gz") as tar:
                    tar.add(conteudo, arcname="cloudflared")

        with tempfile.TemporaryDirectory() as d, mock.patch.object(tunel_bin, "arquivo_release", return_value="cloudflared-darwin-arm64.tgz"):
            destino = Path(d) / "cloudflared"
            tunel_bin.instalar(destino, baixar)
            self.assertEqual(destino.read_bytes(), b"binario")

    def test_plataforma_sem_build_levanta_erro_claro(self):
        with mock.patch.object(tunel_bin, "arquivo_release", return_value=None), self.assertRaises(RuntimeError):
            tunel_bin.instalar("/tmp/x/cloudflared", lambda u, s: None)


class LocalizarTest(unittest.TestCase):
    def test_explicito_inexistente(self):
        self.assertIsNone(tunel_bin.localizar("/nao/existe/cloudflared-xyz"))

    def test_explicito_existente(self):
        with tempfile.NamedTemporaryFile() as f:
            self.assertEqual(tunel_bin.localizar(f.name), f.name)

    def test_garantir_nao_pergunta_sem_terminal(self):
        with mock.patch.object(tunel_bin, "localizar", return_value=None), mock.patch("sys.stdin.isatty", return_value=False):
            self.assertIsNone(tunel_bin.garantir())


if __name__ == "__main__":
    unittest.main()
