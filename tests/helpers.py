from erp_fakes import perfil


class ComPerfilExemplo:
    """Ativa o perfil de exemplo durante a classe de teste e volta ao neutro depois."""

    @classmethod
    def setUpClass(cls):
        perfil.ativar("exemplo")
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        perfil.ativar("")
