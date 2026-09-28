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
    assert "Aprovada" in T._decidir_freela("texto-blog", True)
    assert freelas.ler()[0]["status"] == "aprovada"
