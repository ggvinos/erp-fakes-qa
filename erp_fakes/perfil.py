"""Perfil: tudo o que depende do sistema que consome o ERP (nome, vocabulário, roteiros, consulta ao banco dele).

O núcleo é neutro. Um perfil é um módulo Python com uma variável PERFIL (instância de Perfil); escolha com
--perfil modulo.dotado ou ERP_FAKES_PERFIL. "exemplo" é atalho para erp_fakes.perfis.exemplo.
"""
import importlib
import os
import re
from dataclasses import dataclass, field


@dataclass
class Perfil:
    nome: str = "generico"
    cliente: str = "o sistema integrado"
    termos: dict = field(default_factory=lambda: {
        "o_cliente": "o sistema integrado", "O_cliente": "O sistema integrado", "do_cliente": "do sistema integrado",
        "no_cliente": "no sistema integrado", "pelo_cliente": "pelo sistema integrado", "ao_cliente": "ao sistema integrado",
        "cliente": "sistema integrado", "Cliente": "Sistema integrado",
        "fonte_netpacs": "Contrato inferido do comportamento de um cliente real. A API real do NetPacs não tem documentação pública.",
        "fonte_tasy": "Contrato inferido do comportamento de um cliente real e do agente tasy-api. Não há documentação pública.",
        "caminho_conta": "Configuração de integração do sistema,", "nota_emissor": "", "instrucao_carga": "Faça [[o_cliente]] carregar os dados do ERP.", "nota_tasy_conta": "A URL do agente e a chave vão na conta de integração do cliente."})
    canal: str = "Sistema"
    emissor_jwt: str | None = None
    # roteiros: lista de dicts (ver roteiros.py). Sem roteiros a aba some do painel.
    roteiros: list = field(default_factory=list)
    # status do cliente: lista [(nome, descricao)] pela posição do código, ou dict {codigo: (nome, descricao)}
    status: object = field(default_factory=list)
    # consulta(ids, conta) -> SQL para conferir no banco do cliente os agendamentos pelo id externo, ou None
    consulta: object = None
    conta_padrao: int | None = None
    instrucao_banco: str = ""
    # onde cada entidade cai no cliente: {chave: texto} geral e {erp: {chave: texto}} por ERP
    destino_entidades: dict = field(default_factory=dict)
    destino_entidades_erp: dict = field(default_factory=dict)
    # rótulos dos campos de conta por ERP: {erp: (rotulo_url, rotulo_chave)}
    campos_conta: dict = field(default_factory=dict)
    avisos_conta: dict = field(default_factory=dict)
    fonte_contrato: dict = field(default_factory=dict)


GENERICO = Perfil(nome="generico", destino_entidades={"ocultos": "não existe [[no_cliente]] até ser sincronizado"}, campos_conta={
    "feegow": ("URL base da API (termina em /v1/api)", "Token"), "netpacs": ("URL base (termina em /v2)", "API key"),
    "tasy": ("URL do agente", "Chave (32 caracteres ou mais)")})

_ativo = GENERICO
_PLACEHOLDER = re.compile(r"\[\[(\w+)\]\]")


def ativo():
    return _ativo


def ativar(nome):
    """Ativa o perfil pelo nome: vazio ou 'generico' volta ao neutro, 'exemplo' ou um módulo importável com PERFIL."""
    global _ativo
    nome = (nome or "").strip()
    if nome in ("", "generico"):
        _ativo = GENERICO
        return _ativo
    modulo = {"exemplo": "erp_fakes.perfis.exemplo"}.get(nome, nome)
    try:
        _ativo = importlib.import_module(modulo).PERFIL
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Perfil '{nome}' não encontrado ({e}). Use um módulo importável que defina PERFIL.") from e
    return _ativo


def ativar_do_ambiente():
    if os.environ.get("ERP_FAKES_PERFIL"):
        ativar(os.environ["ERP_FAKES_PERFIL"])
    return _ativo


def aplicar(texto):
    """Troca [[o_cliente]], [[do_cliente]] etc. pelas formas do cliente do perfil ativo."""
    termos = _ativo.termos
    for _ in range(3):
        novo = _PLACEHOLDER.sub(lambda m: termos.get(m.group(1), m.group(0)), texto)
        if novo == texto:
            break
        texto = novo
    return texto


def status_pares():
    """Status do perfil como lista de (codigo, nome, descricao)."""
    st = _ativo.status
    itens = sorted(st.items()) if isinstance(st, dict) else list(enumerate(st))
    return [(c, n, d) for c, (n, d) in itens]


def _status(codigo):
    st = _ativo.status
    try:
        return st[int(codigo)]
    except (ValueError, IndexError, TypeError, KeyError):
        return None


def nome_status(codigo):
    s = _status(codigo)
    return s[0] if s else str(codigo)


def descricao_status(codigo):
    s = _status(codigo)
    return s[1] if s else ""
