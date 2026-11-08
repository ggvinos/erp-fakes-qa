"""Perfil de exemplo: roteiros, status e consulta SQL de um sistema integrado hipotético.

Serve de modelo para criar o seu: copie este arquivo, ajuste os roteiros, os nomes de status, a consulta ao banco
do sistema que você testa e o vocabulário, e ative com --perfil seu_pacote.seu_modulo.
"""
from ..perfil import Perfil

# Código de status gravado no banco do sistema testado e o nome que a avaliação dos roteiros compara.
# Pode ser esparso: códigos fora daqui aparecem como o próprio número.
STATUS = {
    0: ("CRIADO", "Criado"),
    7: ("CANCELADO_PELA_CLINICA", "Cancelado pela clínica"),
    8: ("CONFIRMADO_PELA_CLINICA", "Confirmado pela clínica"),
    9: ("REMARCADO_PELA_CLINICA", "Remarcado pela clínica"),
    29: ("DATA_ALTERADA", "Data alterada"),
}

DESTINO = {
    "unidades": "tabela unidades (id_externo = unidade_id)",
    "convenios": "tabela convenios (id_externo = convenio_id)",
    "profissionais": "tabela profissionais (id_externo = profissional_id)",
    "pacientes": "tabela pacientes (id_externo = paciente_id)",
    "agendamentos": "tabela agendamentos (id_externo = agendamento_id)",
}

ROTEIROS = [
    {
        "id": "preco-do-agendamento",
        "erps": ["feegow", "netpacs", "tasy"],
        "titulo": "Preço do agendamento",
        "card": "",
        "descricao": "Valor do ERP alterado, removido e trocado de convênio, convênio sincronizado depois, valor inválido "
                     "e agendamento novo criado no ERP. Confere o preço gravado n[[o_cliente]].",
        "janela_dias": [1, 3],
        "passos": [
            {"escolher": "a", "cenario": "particular_com_valor_erp"},
            {"acao": "definir_valor", "alvo": "a", "valor": "R$ 777,00",
             "texto": "O ERP passa a informar R$ 777,00 em um particular"},
            {"escolher": "b", "cenario": "convenio_com_valor_erp"},
            {"acao": "definir_valor", "alvo": "b", "valor": "",
             "texto": "O ERP deixa de informar valor em um agendamento de convênio"},
            {"escolher": "c", "cenario": "convenio_com_valor_erp"},
            {"acao": "trocar_convenio", "alvo": "c", "convenio_id": "@outro_convenio",
             "texto": "O agendamento troca de convênio no ERP"},
            {"acao": "definir_valor", "alvo": "c", "valor": "R$ 321,00",
             "texto": "O ERP informa R$ 321,00 para o novo convênio"},
            {"escolher": "d", "cenario": "convenio_nao_sincronizado_com_valor"},
            {"acao": "sincronizar_convenio", "alvo": "d",
             "texto": "O convênio que [[o_cliente]] ainda não conhecia passa a existir no ERP"},
            {"escolher": "e", "cenario": "valor_zero"},
            {"criar": "f", "valor": "R$ 400,00", "em_dias": 2,
             "texto": "Um particular novo é criado no ERP com R$ 400,00"},
        ],
        "verificacoes": [
            {"alvo": "a", "campo": "price", "esperado": "777.00", "explica": "Valor alterado no ERP chega n[[o_cliente]]"},
            {"alvo": "b", "campo": "price", "esperado": "NULL", "explica": "Convênio sem valor no ERP fica sem preço"},
            {"alvo": "c", "campo": "price", "esperado": "321.00", "explica": "Troca de convênio recalcula o preço"},
            {"alvo": "c", "campo": "convenio", "esperado": "@convenio_de_c", "pular_em": ["tasy"],
             "explica": "O convênio novo é o gravado n[[o_cliente]] (no Tasy a conciliação não troca convênio)"},
            {"alvo": "d", "campo": "price", "esperado": "@valor_de_d", "pular_em": ["tasy"],
             "explica": "Convênio sincronizado depois recebe o preço do ERP"},
            {"alvo": "e", "campo": "price", "esperado": "NAO_ZERO",
             "explica": "Valor zero do ERP não é gravado (fica vazio ou vem de regra ou tabela)"},
            {"alvo": "f", "campo": "price", "esperado": "400.00", "explica": "Agendamento novo chega com o preço do ERP"},
        ],
    },
    {
        "id": "status-da-clinica",
        "titulo": "Ações da clínica no ERP",
        "card": "",
        "descricao": "Cancelar, confirmar, remarcar (mesmo id) e sumir do ERP. Confere se [[o_cliente]] acompanha: a data muda na "
                     "remarcação e o registro continua o mesmo.",
        "janela_dias": [1, 2],
        "passos": [
            {"escolher": "a", "cenario": "particular_com_valor_erp"},
            {"acao": "remarcar", "alvo": "a", "dias": 1, "horario": "10:20:00",
             "texto": "O ERP remarca o agendamento, mantendo o mesmo id"},
            {"escolher": "b", "cenario": "particular_com_valor_erp", "status_ids": [1]},
            {"acao": "cancelar", "alvo": "b", "texto": "O paciente cancela no ERP"},
            {"escolher": "c", "cenario": "particular_com_valor_erp", "status_ids": [1]},
            {"acao": "confirmar", "alvo": "c", "texto": "A clínica confirma no ERP"},
        ],
        "verificacoes": [
            {"alvo": "a", "campo": "date", "esperado": "@data_de_a", "explica": "Remarcação muda a data sem criar registro novo"},
            {"alvo": "a", "campo": "existe_unico", "esperado": "1", "explica": "Continua um único registro com esse ID externo"},
            {"alvo": "a", "campo": "status_cliente", "esperado": "DATA_ALTERADA", "pular_em": ["netpacs", "tasy"],
             "explica": "Remarcação no ERP deixa o status Data alterada (observado só no Feegow)"},
            {"alvo": "b", "campo": "status_cliente", "esperado": "CANCELADO_PELA_CLINICA", "explica": "Cancelamento no ERP vira Cancelado pela clínica"},
            {"alvo": "b", "campo": "status_mudou", "esperado": "1", "explica": "O status mudou em relação ao de antes da carga"},
            {"alvo": "c", "campo": "status_cliente", "esperado": "CONFIRMADO_PELA_CLINICA", "explica": "Confirmação no ERP vira Confirmado pela clínica"},
            {"alvo": "c", "campo": "status_mudou", "esperado": "1", "explica": "O status mudou em relação ao de antes da carga"},
        ],
    },
]

ROTEIROS.append({
    "id": "agendamento-some",
    "titulo": "Agendamento some do ERP",
    "card": "",
    "descricao": "O ERP deixa de devolver um agendamento. Confere o que [[o_cliente]] faz com ele: neste exemplo, marca como remarcado pela clínica.",
    "janela_dias": [1, 2],
    "passos": [
        {"escolher": "a", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "sumir", "alvo": "a", "texto": "O agendamento deixa de existir no ERP"},
    ],
    "verificacoes": [
        {"alvo": "a", "campo": "status_cliente", "esperado": "REMARCADO_PELA_CLINICA", "esperado_em": {"netpacs": "CANCELADO_PELA_CLINICA"},
         "explica": "Agendamento que some do ERP vira Remarcado pela clínica n[[o_cliente]] (no NetPacs, pelo contrato, vira Cancelado pela clínica)"},
    ],
})

ROTEIROS.append({
    "id": "formatos-de-valor",
    "erps": ["feegow", "tasy"],
    "titulo": "Formatos de valor do ERP",
    "card": "",
    "descricao": "O ERP envia o valor como texto em formatos diferentes. Confere como [[o_cliente]] interpreta ponto de milhar e decimal, "
                 "e que valor zero, negativo ou acima de 99.999,99 não é gravado.",
    "janela_dias": [1, 3],
    "passos": [
        {"escolher": "a", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "a", "valor": "1.500", "texto": "O ERP envia \"1.500\" (ponto de milhar)"},
        {"escolher": "b", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "b", "valor": "1.50", "texto": "O ERP envia \"1.50\" (ponto decimal)"},
        {"escolher": "c", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "c", "valor": "R$ 1.234,56", "texto": "O ERP envia \"R$ 1.234,56\""},
        {"escolher": "d", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "d", "valor": "80,5", "texto": "O ERP envia \"80,5\" (vírgula decimal)"},
        {"escolher": "e", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "e", "valor": "0", "texto": "O ERP envia zero"},
        {"escolher": "f", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "f", "valor": "-50,00", "texto": "O ERP envia valor negativo"},
        {"escolher": "g", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "g", "valor": "R$ 100.000,00", "texto": "O ERP envia valor acima de 99.999,99"},
    ],
    "verificacoes": [
        {"alvo": "a", "campo": "price", "esperado": "1500.00", "explica": "\"1.500\" é milhar: R$ 1.500,00"},
        {"alvo": "b", "campo": "price", "esperado": "1.50", "explica": "\"1.50\" é decimal: R$ 1,50"},
        {"alvo": "c", "campo": "price", "esperado": "1234.56", "explica": "Formato brasileiro com R$ é lido corretamente"},
        {"alvo": "d", "campo": "price", "esperado": "80.50", "explica": "Vírgula como decimal"},
        {"alvo": "e", "campo": "price", "esperado": "NAO_ZERO", "explica": "Zero não é gravado (vem de regra, de tabela ou fica vazio)"},
        {"alvo": "f", "campo": "price", "esperado": "NAO_NEGATIVO", "explica": "Negativo não é gravado"},
        {"alvo": "g", "campo": "price", "esperado": "NAO_ACIMA_DO_LIMITE", "explica": "Acima de 99.999,99 não é gravado e a carga não cai"},
    ],
})

ROTEIROS.append({
    "id": "troca-de-procedimento",
    "erps": ["tasy"],
    "titulo": "Troca de procedimento recalcula o preço, Tasy",
    "card": "",
    "descricao": "O ERP deixa de informar valor e troca o procedimento do agendamento. Confere que o preço antigo é descartado "
                 "e que [[o_cliente]] usa o preço de tabela do procedimento novo (o /price do fake devolve o valor base).",
    "janela_dias": [1, 3],
    "passos": [
        {"escolher": "a", "cenario": "particular_com_valor_erp", "status_ids": [1]},
        {"acao": "definir_valor", "alvo": "a", "valor": "", "texto": "O ERP deixa de informar valor"},
        {"acao": "trocar_procedimento", "alvo": "a", "procedimento_id": "@outro_procedimento",
         "texto": "O agendamento troca de procedimento no ERP"},
    ],
    "verificacoes": [
        {"alvo": "a", "campo": "price", "esperado": "@tabela_de_a",
         "explica": "O preço antigo some e vale o preço de tabela do procedimento novo"},
    ],
})


def consulta(ids, conta):
    """SQL para conferir no banco do sistema testado os agendamentos pelo id externo. Troque pelas suas tabelas."""
    lista = ",".join(f"'{i}'" for i in ids)
    return ("SELECT a.id_externo, a.id AS id_cliente, a.data AS date, a.preco AS price, a.status, p.nome AS convenio\n"
            "FROM agendamentos a\nLEFT JOIN convenios p ON p.id = a.convenio_id\n"
            f"WHERE a.conta = {conta} AND a.id_externo IN ({lista})\nORDER BY a.id_externo;")


PERFIL = Perfil(
    nome="exemplo",
    roteiros=ROTEIROS,
    status=STATUS,
    consulta=consulta,
    conta_padrao=1,
    instrucao_banco="No banco do sistema integrado",
    destino_entidades=DESTINO,
    termos={**Perfil().termos, "instrucao_carga": "Dispare a carga de agendamentos no sistema integrado e aguarde terminar."},
)
