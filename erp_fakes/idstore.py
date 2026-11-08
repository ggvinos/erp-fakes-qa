import json
import threading
from pathlib import Path

# Ids de agendamentos e pacientes criados depois da carga inicial começam acima do que já foi usado em
# execuções anteriores, para [[o_cliente]] nunca confundir um registro novo com um antigo (ela guarda o id do ERP).
PISOS = {"schedule": 910001, "patient": 6001}


class IdStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._last = {}
        self._usados = []
        if self.path and self.path.exists():
            try:
                dados = json.loads(self.path.read_text())
                self._usados = list(dados.pop("roteiros_usados", []))
                self._last = dados
            except (OSError, ValueError):
                pass

    def next(self, kind, floor=0):
        with self._lock:
            n = max(self._last.get(kind, 0) + 1, floor, PISOS.get(kind, 0))
            self._last[kind] = n
            self._grava()
            return n

    def _grava(self):
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({**self._last, "roteiros_usados": self._usados}))
            except OSError:
                pass

    def ja_usado(self, ident):
        with self._lock:
            return ident in self._usados

    def total_usados(self):
        with self._lock:
            return len(self._usados)

    def limpar_usados(self):
        with self._lock:
            self._usados = []
            self._grava()

    def marcar_usados(self, idents):
        """Agendamentos já usados por roteiros: não são escolhidos de novo, porque [[o_cliente]] guardou o efeito."""
        with self._lock:
            self._usados = sorted(set(self._usados) | set(idents))
            self._grava()
