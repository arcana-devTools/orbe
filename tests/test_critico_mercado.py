"""Crítico (portão de qualidade antes do Telegram) e pesquisador de mercado — sem rede."""
import asyncio
import json

import acabamento as A
import llm_pool
import mercado

CORPO_BOM = "\n".join(f"## Seção {i}\n\n" + ("conteúdo útil e concreto " * 80) for i in range(1, 9))
META = {"titulo": "Planner X", "subtitulo": "s", "paginas": 12, "preco_brl": 29}


def _ia(resposta):
    async def fake(*a, **k):
        if isinstance(resposta, Exception):
            raise resposta
        return json.dumps(resposta), "fake:modelo"
    return fake


def _rodar(monkeypatch, resposta, corpo=CORPO_BOM, meta=META):
    monkeypatch.setattr(llm_pool, "chat", _ia(resposta))
    dormir = asyncio.sleep
    monkeypatch.setattr(A.asyncio, "sleep", lambda *_: dormir(0))
    return asyncio.run(A.criticar(corpo, dict(meta), None))


def test_checagens_objetivas():
    assert A._checagens(CORPO_BOM, 12) == []
    ruins = A._checagens("## [Nome do Cliente]\n\ncurto", 3)
    assert any("páginas" in p for p in ruins) and any("curto" in p for p in ruins)
    assert any("[..]" in p for p in ruins)


def test_aprova_so_com_nota_de_venda_alta(monkeypatch):
    ok = {"utilidade": 9, "acabamento": 9, "vende": 8, "veredito": "aprovar", "preco_justo": 19}
    assert _rodar(monkeypatch, ok)["aprovado"]
    fraco = dict(ok, vende=7)                       # média 8.3, mas "vende" 7 → não chega ao dono
    assert not _rodar(monkeypatch, fraco)["aprovado"]


def test_defeito_objetivo_reprova_mesmo_com_ia_elogiando(monkeypatch):
    ok = {"utilidade": 10, "acabamento": 10, "vende": 10, "veredito": "aprovar"}
    assert not _rodar(monkeypatch, ok, meta=dict(META, paginas=4))["aprovado"]


def test_ia_sem_cota_nao_e_reprovacao(monkeypatch):
    c = _rodar(monkeypatch, RuntimeError("groq: 429"))
    assert c["indisponivel"] and not c["aprovado"]


def test_julgar_status_e_preco(tmp_path, monkeypatch):
    (tmp_path / "pagina_de_vendas.md").write_text("**Preço sugerido:** R$ 29\n", encoding="utf-8")

    async def crit(corpo, meta, brief):
        return {"aprovado": True, "media": 8.7, "preco_justo": 19, "notas": {}, "problemas": []}
    monkeypatch.setattr(A, "criticar", crit)
    m = asyncio.run(A._julgar(tmp_path, dict(META), CORPO_BOM, None))
    assert m["status"] == "aguardando_dono" and m["preco_brl"] == 19
    assert "R$ 19" in (tmp_path / "pagina_de_vendas.md").read_text(encoding="utf-8")

    async def sem_cota(corpo, meta, brief):
        return {"aprovado": False, "indisponivel": True, "media": 0, "notas": {}, "problemas": []}
    monkeypatch.setattr(A, "criticar", sem_cota)
    assert asyncio.run(A._julgar(tmp_path, dict(META), CORPO_BOM, None))["status"] == "aguardando_critica"


def test_limitacao_interna_some_do_produto():
    t = "Feito pra você. É um arquivo de texto puro. Não há imagens ou gráficos. Use todo mês."
    assert A._limpar_promessas(t) == "Feito pra você. Use todo mês."


def test_amostra_pega_inicio_meio_fim():
    corpo = "INICIO" + "x" * 10000 + "MEIO" + "y" * 10000 + "FIM"
    a = A._amostra(corpo)
    assert "INICIO" in a and "MEIO" in a and "FIM" in a and len(a) < 7000


def test_brief_valida_evidencia_e_viabilidade(tmp_path, monkeypatch):
    monkeypatch.setattr(mercado, "BRIEFS", tmp_path / "briefs.json")
    base = {"produto": "Planner", "publico": "p", "dor": "d", "diferencial": "adaptado ao Brasil",
            "itens_obrigatorios": ["a", "b", "c", "d", "vídeo de treino"], "preco_brl": 19,
            "evidencias": [{"url": "https://www.etsy.com/listing/1", "sinal": "570 vendas"}],
            "concorrentes_preco": "R$10-25", "confianca": 8}

    def rodar(d):
        async def fake(*a, **k):
            return json.dumps(d), "fake"
        monkeypatch.setattr(llm_pool, "chat", fake)
        return asyncio.run(mercado.pesquisar("finanças"))

    b = rodar(base)                                   # item de vídeo sai; sobram 4 → ainda vale
    assert b["status"] == "novo" and "vídeo" not in " ".join(b["itens_obrigatorios"])
    assert rodar(dict(base, itens_obrigatorios=["a", "b", "vídeo 1", "app"]))["status"] == "descartado"
    assert rodar(dict(base, itens_obrigatorios=list("abcde"), evidencias=[]))["status"] == "descartado"
    assert rodar(dict(base, itens_obrigatorios=list("abcde"),
                      diferencial="QR codes para vídeos"))["status"] == "descartado"
