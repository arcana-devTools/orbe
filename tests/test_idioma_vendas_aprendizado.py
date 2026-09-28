"""Itens 3 (inglês/Etsy), 4 (vendas reais) e 5 (aprendizado) — sem rede."""
import asyncio
import json

import acabamento as A
import aprendizado
import telegram_sim as T
import vendas

CORPO_EN = "\n".join(f"## Section {i}\n\n" + ("Use this page to plan your week and track the habits you want. " * 30)
                     for i in range(1, 9))


# ---------------------------------------------------------------- 3. inglês
def test_pdf_em_ingles_papel_carta(tmp_path):
    import pypdfium2 as pdfium

    n = A.gerar_pdf("Weekly Planner", "Plan your week", CORPO_EN, tmp_path / "p.pdf", "en")
    doc = pdfium.PdfDocument(str(tmp_path / "p.pdf"))
    w, h = doc[0].get_size()
    assert n >= 3 and abs(w - 612) < 3 and abs(h - 792) < 3        # US Letter em pontos
    texto = "".join(doc[i].get_textpage().get_text_range() for i in range(2))
    assert "What's inside" in texto and "Printable PDF" in texto


def test_preco_fmt_por_moeda():
    assert A.preco_fmt({"preco": 7, "moeda": "USD"}) == "US$ 7"
    assert A.preco_fmt({"preco_brl": 19}) == "R$ 19"                 # produto antigo


def test_idioma_errado_reprova_e_limpa_promessas_em_ingles():
    assert A._idioma_errado("Este planner é para você que quer organizar a sua semana com calma.", "en")
    assert not A._idioma_errado(CORPO_EN, "en")
    t = A._limpar_promessas("A fully editable PDF you will love. It is a text-only file. No refunds. Print it.")
    assert "editable" not in t and "text-only" not in t and "refund" not in t.lower() and "Print it." in t


def test_prompt_do_brief_em_ingles_leva_licoes(tmp_path, monkeypatch):
    import mercado

    monkeypatch.setattr(aprendizado, "licoes_prompt", lambda: "NÃO repita: (1) sumário confuso ")
    p = mercado.prompt_do_brief({"produto": "Budget Planner", "idioma": "en", "itens_obrigatorios": ["a"]})
    assert "INGLÊS americano" in p and "sumário confuso" in p


def test_idioma_reveza(tmp_path, monkeypatch):
    import mercado

    monkeypatch.setattr(mercado, "BRIEFS", tmp_path / "b.json")
    monkeypatch.setattr(mercado, "IDIOMAS", ["en", "pt"])
    assert mercado.proximo_idioma() == "en"
    mercado.salvar([{"id": "x"}])
    assert mercado.proximo_idioma() == "pt"


# ---------------------------------------------------------------- 4. vendas reais
def _produto(tmp, pid, **meta):
    (tmp / pid).mkdir(parents=True)
    (tmp / pid / "meta.json").write_text(json.dumps({"id": pid, "titulo": pid, "criado": 1, **meta}), encoding="utf-8")


def test_venda_nao_duplica_e_conta_no_produto(tmp_path, monkeypatch):
    monkeypatch.setattr(vendas, "VENDAS", tmp_path / "v.json")
    monkeypatch.setattr(A, "PRODUTOS", tmp_path)
    _produto(tmp_path, "p1", status="publicado")
    assert vendas.registrar("etsy", 6.99, "usd", "pedido-1", "p1")
    assert vendas.registrar("etsy", 6.99, "USD", "pedido-1", "p1") is None     # mesma prova
    assert vendas.registrar("etsy", 0, "USD", "pedido-2") is None               # valor inválido
    vendas.registrar("hotmart", 27, "BRL", "HP-9")
    assert vendas.totais(vendas.ler()) == {"USD": 6.99, "BRL": 27.0}
    assert json.loads((tmp_path / "p1" / "meta.json").read_text())["vendas"] == 1
    assert "US$ 6.99" in vendas.resumo_txt(0) and "R$ 27" in vendas.resumo_txt(0)


def test_resumo_sai_so_por_venda_real(tmp_path, monkeypatch):
    monkeypatch.setattr(vendas, "VENDAS", tmp_path / "v.json")
    monkeypatch.setattr(A, "PRODUTOS", tmp_path)
    monkeypatch.setattr(T, "_RESUMO", tmp_path / "r.json")
    monkeypatch.setattr(T, "_cfg", lambda: ("tok", "1"))
    monkeypatch.setattr(T, "_hora_brasilia", lambda: T.HORA_RESUMO)
    msgs = []

    async def tg(method, **kw):
        msgs.append(kw.get("text"))
        return {"ok": True}
    monkeypatch.setattr(T, "_tg", tg)
    assert asyncio.run(T.resumo_diario()) is False and not msgs                 # nada novo: silêncio
    vendas.registrar("etsy", 5, "USD", "o-1")
    assert asyncio.run(T.resumo_diario()) is True and "venda" in msgs[0]
    vendas.registrar("etsy", 5, "USD", "o-2")
    assert asyncio.run(T.resumo_diario()) is False                              # já teve resumo hoje


# ---------------------------------------------------------------- 5. aprendizado
def test_licoes_vem_dos_reprovados(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PRODUTOS", tmp_path)
    _produto(tmp_path, "r1", status="reprovado", critica={"problemas": ["Tabelas vazias sem exemplo", "crítico sem cota agora"]})
    _produto(tmp_path, "ok", status="aguardando_dono", critica={"problemas": ["nada"]})
    assert aprendizado.licoes() == ["Tabelas vazias sem exemplo"]
    assert "Tabelas vazias" in aprendizado.licoes_prompt()


def test_o_que_vende_vira_variacao_uma_vez(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PRODUTOS", tmp_path)
    monkeypatch.setattr(aprendizado, "APR", tmp_path / "apr.json")
    _produto(tmp_path, "p1", status="publicado", vendas=2, idioma="en", titulo="Budget Planner")
    q = aprendizado.tema_quente()
    assert q["pid"] == "p1" and q["idioma"] == "en" and q["inspiracao"] == "Budget Planner"
    aprendizado.marcar_variado("p1")
    assert aprendizado.tema_quente() is None


def test_encalhado_ganha_sugestao(tmp_path, monkeypatch):
    import llm_pool

    monkeypatch.setattr(A, "PRODUTOS", tmp_path)
    monkeypatch.setattr(aprendizado, "APR", tmp_path / "apr.json")
    _produto(tmp_path, "velho", status="publicado", publicado_em=1.0, vendas=0, preco=7, moeda="USD")
    _produto(tmp_path, "novo", status="publicado", publicado_em=9e12, vendas=0)

    async def fake(*a, **k):
        return json.dumps({"titulo": "Better Title", "tags": ["x"], "preco": 5, "motivo": "m"}), "f"
    monkeypatch.setattr(llm_pool, "chat", fake)
    assert asyncio.run(aprendizado.revisar_encalhados()) == 1
    m = json.loads((tmp_path / "velho" / "meta.json").read_text())
    assert m["ajustar"] and m["ajuste_sugerido"]["titulo"] == "Better Title"
    assert asyncio.run(aprendizado.revisar_encalhados()) == 0                   # não revisa 2x no mês
