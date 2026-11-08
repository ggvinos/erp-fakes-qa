"""Utilidades comuns aos dialetos (Feegow, NetPacs, Tasy): datas no fuso de Brasília e catálogo de rotas."""
import re
from datetime import date, datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))


def hora_texto(h):
    return h[:5]


def epoch_ms(d, hhmm="00:00"):
    hh, mm = int(hhmm[:2]), int(hhmm[3:5])
    return int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=BRT).timestamp() * 1000)


def epoch_ms_hora(hhmm):
    """Hora do dia como instante em 01/01/1970 no fuso de Brasília (formato de horaInicial do NetPacs)."""
    return int((int(hhmm[:2]) * 3600 + int(hhmm[3:5]) * 60 + 3 * 3600) * 1000)


def ts_texto(d, hhmm, seg="00"):
    return f"{d.isoformat()} {hhmm[:5]}:{seg}.0"


def data_br(texto):
    return datetime.strptime(str(texto).split(" ")[0], "%d/%m/%Y").date()


def sexo_letra(sexo):
    return "F" if str(sexo).lower().startswith("f") else "M"


def digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


def rota(metodo, caminho, secao, resumo, parametros=(), erros=(), uso_cliente="", implementado=True):
    return {"metodo": metodo, "caminho": caminho, "secao": secao, "resumo": resumo, "parametros": list(parametros),
            "erros": list(erros), "uso_cliente": uso_cliente, "implementado": implementado, "na_documentacao": True}


def compila(tabela):
    """[(metodo, regex, nome_do_metodo)] a partir de [(metodo, caminho_com_{param}, nome)]."""
    out = []
    for metodo, caminho, nome in tabela:
        rx = re.sub(r"\{(\w+)\}", r"([^/]+)", caminho)
        out.append((metodo, re.compile(rx), nome))
    return out
