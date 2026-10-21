from propostas_leitura import ler_99, ler_workana


PAGINA = """
<option>Aguardando resposta</option>
<a href="/project/advertorial-em-ingles-789174">Advertorial em inglês para os EUA</a>
Enviada: 11/10/2026 | Oferta: R$ 220,00 |
"""


def test_uma_proposta_aguardando():
    itens = ler_99(PAGINA)
    assert len(itens) == 1
    assert itens[0]["status"] == "aguardando resposta"
    assert itens[0]["enviada"] == "11/10/2026"
    assert "220" in itens[0]["oferta"]


def test_lista_vazia():
    assert ler_99("Nenhuma proposta foi encontrada.") == []


def test_workana_vazio():
    doc = ler_workana('{"notifications":{"count":0,"latest":[]},"threads":{"count":0,"latest":[]}}')
    assert doc["notificacoes"] == 0
    assert doc["conversas"] == 0
