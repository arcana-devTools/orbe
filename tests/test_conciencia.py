"""O laço não pode ficar preso avisando o mesmo produto já notificado."""
import conciencia


def _base(**kw):
    p = {
        "vivos": 1, "ia": True, "kiwify_ok": True, "webhook_ok": True,
        "sessao_kiwify": False, "kiwify_login": True, "humano_aqui": False,
        "aprovados_sem_kit": 0, "aguardando_dono": 1, "aguardando_sem_aviso": 0,
        "pendencias": [], "briefs_novos": 0, "produtos": 7,
    }
    p.update(kw)
    return p


def test_produto_ja_avisado_nao_trava_o_laco():
    d = conciencia.decidir(_base())
    assert d["acao"] != "avisar"
    assert d["acao"] == "observar"


def test_produto_novo_ainda_avisa():
    d = conciencia.decidir(_base(aguardando_sem_aviso=1))
    assert d["acao"] == "avisar"


def test_faixa_livre_nao_e_adulto():
    import uiclap
    assert uiclap.IDADE_LIVRE == 1
    assert "idade: 7" not in uiclap.script_favorito("https://exemplo")
    assert "idade: 1" in uiclap.script_favorito("https://exemplo")
