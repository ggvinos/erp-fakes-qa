import itertools
import threading

TIPOS = {
    "atraso": {"rotulo": "Demorar para responder", "unidade": "ms", "padrao": 3000,
               "ajuda": "Espera N milissegundos e depois responde normalmente"},
    "status": {"rotulo": "Responder com erro HTTP", "unidade": "código", "padrao": 500,
               "ajuda": "Responde com o código informado (401, 403, 409, 422, 500, 503...)"},
    "vazio": {"rotulo": "Responder vazio", "unidade": "", "padrao": None,
              "ajuda": "Responde 200 com JSON vazio {}, sem os campos que [[o_cliente]] espera"},
    "quebrado": {"rotulo": "Responder texto quebrado", "unidade": "", "padrao": None,
                 "ajuda": "Responde 200 com HTML no lugar de JSON"},
    "derrubar": {"rotulo": "Derrubar a conexão", "unidade": "", "padrao": None,
                 "ajuda": "Fecha a conexão sem responder"},
    "timeout": {"rotulo": "Estourar o tempo limite", "unidade": "s", "padrao": 15,
                "ajuda": "Espera N segundos antes de responder, mais que o limite [[do_cliente]]"},
}

PRESETS = [
    {"nome": "ERP lento na carga", "rota": "/appoints/search", "tipo": "atraso", "valor": 9000, "vezes": None},
    {"nome": "Gateway ruim (502)", "rota": "*", "tipo": "status", "valor": 502, "vezes": None},
    {"nome": "Carga de agendamentos com 502", "rota": "/appoints/search", "tipo": "status", "valor": 502, "vezes": None},
    {"nome": "ERP fora do ar (503)", "rota": "*", "tipo": "status", "valor": 503, "vezes": None},
    {"nome": "Chave inativa (403)", "rota": "*", "tipo": "status", "valor": 403, "vezes": None},
    {"nome": "Horário ocupado ao agendar (409)", "rota": "/appoints/new-appoint", "tipo": "status", "valor": 409, "vezes": 1},
    {"nome": "Carga de agendamentos vazia", "rota": "/appoints/search", "tipo": "vazio", "valor": None, "vezes": None},
    {"nome": "Horários livres quebrados", "rota": "/appoints/available-schedule", "tipo": "quebrado", "valor": None, "vezes": None},
    {"nome": "Agendar derruba a conexão", "rota": "/appoints/new-appoint", "tipo": "derrubar", "valor": None, "vezes": 1},
]


PRESETS_POR_ERP = {
    "feegow": PRESETS,
    "netpacs": [
        {"nome": "ERP lento na carga", "rota": "/netris/api/atendimentos", "tipo": "atraso", "valor": 9000, "vezes": None},
        {"nome": "Gateway ruim (502)", "rota": "*", "tipo": "status", "valor": 502, "vezes": None},
        {"nome": "Carga de atendimentos com 502", "rota": "/netris/api/atendimentos", "tipo": "status", "valor": 502, "vezes": None},
        {"nome": "ERP fora do ar (503)", "rota": "*", "tipo": "status", "valor": 503, "vezes": None},
        {"nome": "Chave inválida (403)", "rota": "*", "tipo": "status", "valor": 403, "vezes": None},
        {"nome": "Resposta vazia na carga (cuidado: [[o_cliente]] cancela tudo)", "rota": "/netris/api/atendimentos", "tipo": "vazio", "valor": None, "vezes": None},
        {"nome": "Carga quebrada (HTML no lugar de JSON)", "rota": "/netris/api/atendimentos", "tipo": "quebrado", "valor": None, "vezes": None},
        {"nome": "Horário ocupado ao agendar (409)", "rota": "/netris/api/horarios", "tipo": "status", "valor": 409, "vezes": 1, "metodo": "POST"},
        {"nome": "Confirmar falha (500)", "rota": "/netris/api/atendimentos/*", "tipo": "status", "valor": 500, "vezes": None, "metodo": "PATCH"},
    ],
    "tasy": [
        {"nome": "Agente lento na carga", "rota": "/schedules", "tipo": "atraso", "valor": 9000, "vezes": None},
        {"nome": "Gateway ruim (502)", "rota": "*", "tipo": "status", "valor": 502, "vezes": None},
        {"nome": "Carga de agendamentos com 502", "rota": "/schedules", "tipo": "status", "valor": 502, "vezes": None},
        {"nome": "Agente fora do ar (503)", "rota": "*", "tipo": "status", "valor": 503, "vezes": None},
        {"nome": "Chave inválida (401)", "rota": "*", "tipo": "status", "valor": 401, "vezes": None},
        {"nome": "Carga vazia ([[o_cliente]] confere cada sumido)", "rota": "/schedules", "tipo": "vazio", "valor": None, "vezes": None},
        {"nome": "Carga quebrada (HTML no lugar de JSON)", "rota": "/schedules", "tipo": "quebrado", "valor": None, "vezes": None},
        {"nome": "Confirmar falha (500)", "rota": "/schedules/*", "tipo": "status", "valor": 500, "vezes": None, "metodo": "POST"},
    ],
}


class FaultEngine:
    def __init__(self):
        self._rules, self._ids, self._lock = [], itertools.count(1), threading.Lock()

    def add(self, rota, tipo, valor=None, vezes=None, metodo=None):
        if tipo not in TIPOS:
            raise ValueError(f"tipo de falha desconhecido: {tipo}")
        if valor in (None, ""):
            valor = TIPOS[tipo]["padrao"]
        rule = {"id": next(self._ids), "rota": rota or "*", "metodo": metodo or None, "tipo": tipo,
                "valor": int(valor) if valor is not None else None,
                "restantes": int(vezes) if vezes not in (None, "") else None, "disparos": 0}
        with self._lock:
            self._rules.append(rule)
        return rule

    def remove(self, rule_id):
        with self._lock:
            self._rules = [r for r in self._rules if r["id"] != int(rule_id)]

    def clear(self):
        with self._lock:
            self._rules = []

    def list(self):
        with self._lock:
            return [dict(r) for r in self._rules]

    @staticmethod
    def _casa(padrao, caminho):
        if padrao in ("*", "", None):
            return True
        if padrao.endswith("*"):
            return caminho.startswith(padrao[:-1])
        return caminho == padrao

    def pick(self, metodo, caminho):
        with self._lock:
            for r in self._rules:
                if r["restantes"] == 0 or (r["metodo"] and r["metodo"] != metodo) or not self._casa(r["rota"], caminho):
                    continue
                r["disparos"] += 1
                if r["restantes"] is not None:
                    r["restantes"] -= 1
                return dict(r)
        return None
