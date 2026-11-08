import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

BIN_DIR = Path.home() / ".local" / "share" / "erp-fakes" / "bin"
BASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
WINDOWS = os.name == "nt"
NOME = "cloudflared.exe" if WINDOWS else "cloudflared"

ARQUITETURAS = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm", "i386": "386", "i686": "386"}


def arquivo_release(sistema=None, maquina=None):
    """Nome do arquivo do release do cloudflared para o sistema, ou None se não houver build."""
    sistema = (sistema or platform.system()).lower()
    arq = ARQUITETURAS.get((maquina or platform.machine()).lower())
    if not arq:
        return None
    if sistema == "linux":
        return f"cloudflared-linux-{arq}"
    if sistema == "darwin":
        return f"cloudflared-darwin-{arq}.tgz" if arq in ("amd64", "arm64") else None
    if sistema == "windows":
        return f"cloudflared-windows-{arq}.exe" if arq in ("amd64", "386") else None
    return None


def localizar(explicito=None):
    """Caminho do cloudflared já instalado, ou None."""
    if explicito:
        return explicito if Path(explicito).exists() or shutil.which(explicito) else None
    candidatos = [shutil.which("cloudflared"), BIN_DIR / NOME, Path.home() / ".local" / "bin" / NOME]
    for c in candidatos:
        if c and Path(c).exists():
            return str(c)
    return None


def instalar(destino=None, baixar=None):
    """Baixa o cloudflared oficial (Cloudflare, GitHub releases) para a pasta do programa e devolve o caminho."""
    arq = arquivo_release()
    if not arq:
        raise RuntimeError(f"Sem build do cloudflared para {platform.system()} {platform.machine()}. Instale manualmente: https://github.com/cloudflare/cloudflared/releases")
    destino = Path(destino) if destino else BIN_DIR / NOME
    destino.parent.mkdir(parents=True, exist_ok=True)
    baixar = baixar or _baixar
    with tempfile.TemporaryDirectory() as tmp:
        bruto = Path(tmp) / arq
        baixar(BASE + arq, bruto)
        if arq.endswith(".tgz"):
            with tarfile.open(bruto) as t:
                membro = next((m for m in t.getmembers() if m.isfile() and Path(m.name).name == "cloudflared"), None)
                if not membro:
                    raise RuntimeError("Arquivo baixado não contém o cloudflared")
                with t.extractfile(membro) as src, open(Path(tmp) / "cloudflared", "wb") as dst:
                    shutil.copyfileobj(src, dst)
            bruto = Path(tmp) / "cloudflared"
        parcial = destino.with_name(destino.name + ".parcial")
        shutil.copyfile(bruto, parcial)
        parcial.chmod(parcial.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(parcial, destino)
    return str(destino)


def _baixar(url, saida):
    with urllib.request.urlopen(url, timeout=60) as r, open(saida, "wb") as f:
        shutil.copyfileobj(r, f)


def garantir(explicito=None, perguntar=True):
    """Localiza o cloudflared; se faltar e houver terminal interativo, oferece baixar. None se não houver."""
    achado = localizar(explicito)
    if achado or explicito:
        return achado
    if perguntar and sys.stdin.isatty() and sys.stdout.isatty():
        resp = input("cloudflared não encontrado (é ele que cria o endereço público). Baixar agora de github.com/cloudflare/cloudflared? [S/n] ").strip().lower()
        if resp in ("", "s", "sim", "y", "yes"):
            try:
                caminho = instalar()
                print(f"cloudflared instalado em {caminho}")
                return caminho
            except Exception as e:
                print(f"Não consegui baixar: {e}")
    return None
