"""💼 Freelas: filtro objetivo, normalização da vaga do Workana, honestidade do perfil e resumo das 19h."""
import asyncio

import acabamento as A
import freelas
import perfil_workana as P
import telegram_sim as T
import vendas


def _vaga(**kw):
    j = {"slug": "texto-blog", "title": '<a href="/job/x"><span>Artigos para blog de pet shop</span></a>',
         "description": "Preciso de 4 artigos de 800 palavras.", "budget": "R$ 260 - 500",
         "totalBids": "Propostas: 7", "postedDate": "há 2 horas", "isHourly": False,
         "hasVerifiedPaymentMethod": True,
         "skills": [{"anchorText": "Escrita de artigos"}]}
    j.update(kw)
    return freelas.normalizar(j)


def test_normaliza_vaga_do_workana():
    v = _vaga()
    assert v["titulo"] == "Artigos para blog de pet shop" and v["minimo"] == 260 and v["moeda"] == "BRL"
    assert v["propostas"] == 7 and v["pagamento_verificado"] and v["skills"] == ["Escrita de artigos"]
    assert freelas.filtro_objetivo(v) == ""


def test_filtro_barra_academico_hora_audio_e_lotada():
    assert "fora" in freelas.filtro_objetivo(_vaga(title="Revisão de TCC"))
    assert "hora" in freelas.filtro_objetivo(_vaga(isHourly="True"))
    assert "fora" in freelas.filtro_objetivo(_vaga(description="transcrição de áudio de 2h"))
    assert "concorrência" in freelas.filtro_objetivo(_vaga(totalBids="Propostas: 55"))
    assert "pouco" in freelas.filtro_objetivo(_vaga(budget="R$ 20 - 40"))
    assert "fora" in freelas.filtro_objetivo(_vaga(description="emitir opiniões e avaliações sobre produtos, escrita de reviews"))


def test_proposta_ja_escrita_cai_se_regra_nova_barrar():
    v = _vaga(description="escrita de reviews de produtos")
    v.update(status="aguardando_dono", proposta="x")
    freelas._salvar([v])
    assert freelas.pendentes() == [] and freelas.ler()[0]["status"] == "descartada"


def test_checagem_de_honestidade_do_perfil():
    assert P._limpo("aumenta as vendas em 70 %")
    assert P._limpo("ajustes ilimitados")
    assert P._limpo("tenho 5 anos de experiência")
    assert P._limpo("reservatório de 250 ml, entrega em 3 dias") == ""


def test_resumo_leva_proposta_de_freela(tmp_path, monkeypatch):
    monkeypatch.setattr(vendas, "VENDAS", tmp_path / "v.json")
    monkeypatch.setattr(A, "PRODUTOS", tmp_path)
    monkeypatch.setattr(T, "_RESUMO", tmp_path / "r.json")
    monkeypatch.setattr(T, "_cfg", lambda: ("tok", "1"))
    monkeypatch.setattr(T, "_hora_brasilia", lambda: T.HORA_RESUMO)
    msgs = []

    async def tg(method, **kw):
        msgs.append(kw)
        return {"ok": True}
    monkeypatch.setattr(T, "_tg", tg)
    v = _vaga()
    v.update(status="aguardando_dono", nota=8, proposta="Seu blog precisa de...", visto=1)
    freelas._salvar([v])
    assert asyncio.run(T.resumo_diario()) is True
    assert "proposta" in msgs[0]["text"] and "FREELA" in msgs[1]["text"]
    assert msgs[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "fok_texto-blog"
    assert freelas.pendentes() == []                                  # não repete amanhã
    assert "Aprovada" in asyncio.run(T._decidir_freela("texto-blog", True))
    assert freelas.ler()[0]["status"] == "aprovada"


def test_resumo_avisa_liberacao_uma_vez(tmp_path, monkeypatch):
    monkeypatch.setattr(vendas, "VENDAS", tmp_path / "v.json")
    monkeypatch.setattr(A, "PRODUTOS", tmp_path)
    monkeypatch.setattr(T, "_RESUMO", tmp_path / "r.json")
    monkeypatch.setattr(T, "_cfg", lambda: ("tok", "1"))
    monkeypatch.setattr(T, "_hora_brasilia", lambda: T.HORA_RESUMO)
    msgs = []

    async def tg(method, **kw):
        msgs.append(kw)
        return {"ok": True}
    monkeypatch.setattr(T, "_tg", tg)
    freelas._salvar_estado({"em_revisao": False, "liberado_em": 1})
    assert asyncio.run(T.resumo_diario()) is True and "LIBEROU" in msgs[0]["text"]
    assert freelas.estado().get("liberacao_avisada")
    assert asyncio.run(T.resumo_diario(forcar=True)) is False           # não repete


def test_99freelas_le_lista_e_resposta():
    import freelas99 as F

    li = ('<li class="with-flag result-item" data-id="787462" data-nome="Revis&atilde;o de livro"> '
          '<a href="/project/revisao-de-livro-787462?fs=t">x</a> <p class="item-text information"> Edição & Revisão | '
          'Iniciante | Publicado: | Propostas: <b>12</b> | Interessados: <b>20</b> </hgroup> '
          '<div class="item-text description" data-content="Revisar 40 páginas de romance."> </div></li></ul>')
    v = F._itens(li)[0]
    assert v["slug"] == "99-787462" and v["titulo"] == "Revisão de livro" and v["propostas"] == 12
    assert v["url"].endswith("/project/revisao-de-livro-787462") and not v["exclusivo"]
    assert F.resposta("%7B%22status%22%3A%7B%22id%22%3A1%7D%2C%22directResult%22%3Afalse%7D")["status"]["id"] == 1


def test_99freelas_aprovar_envia_de_verdade(monkeypatch):
    import freelas99 as F

    enviados = []

    async def enviar(v):
        enviados.append(v["slug"])
        return {"ok": True, "oferta": 80.0}
    monkeypatch.setattr(F, "enviar", enviar)
    v = _vaga(slug="99-1")
    v.update(plataforma="99freelas", status="aguardando_dono", proposta="x", id99=1)
    freelas._salvar([v])
    txt = asyncio.run(T._decidir_freela("99-1", True))
    assert "ENVIADA" in txt and enviados == ["99-1"] and freelas.ler()[0]["status"] == "enviada"
