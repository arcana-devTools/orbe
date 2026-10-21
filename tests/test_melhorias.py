from melhorias import caminho_seguro, plano, seguro


def test_recusa_segredo():
    assert seguro("melhora o log da falha")
    assert not seguro("cookie=" + "x" * 12)
    assert not seguro("github_pat_" + "a" * 20)
    assert seguro("nao colocar cookie no texto")
    assert seguro('PROIBIDO = ("cookie=", "github_pat_")')


def test_caminho():
    assert caminho_seguro("skills/melhorias/SKILL.md")
    assert not caminho_seguro("../cofre/vault.json")
    assert not caminho_seguro("/etc/passwd")


def test_plano_nao_dispara():
    itens = plano([{"repo": "arcana-devTools/orbe", "nome": "Renovar Arena", "quando": "2026-10-16T23:50:41Z"}])
    assert any("TikTok" in item for item in itens)
    assert any("Renovar Arena" in item for item in itens)
