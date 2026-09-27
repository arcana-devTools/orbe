"""🧵 ACABADOR — agente da colônia que transforma rascunho em PRODUTO vendável.

Fluxo (roda sozinho dentro da colônia, sem ninguém clicar):
 1. pega o rascunho mais novo de uma MISSÃO aprovada (data/resultados/*missao_*.md)
 2. limpeza determinística: tira emojis, a "página de vendas" do rascunho,
    promessas falsas ("PDF editável/preenchível", garantias, "sem reembolso")
 3. IA (llm_pool) escreve SÓ título, subtítulo, preço e página de vendas HONESTA
    a partir do sumário real do conteúdo (chamada pequena → cabe no plano grátis)
 4. monta HTML bonito (capa + sumário + páginas numeradas) → PDF (WeasyPrint)
 5. anexa bloco fixo "o que você recebe" (nº real de páginas) + reembolso 7 dias (CDC art. 49)
 6. manda o PDF no Telegram do dono com botões ✅ aprovar / 🔁 refazer
Saída: data/produtos/<id>/{produto.pdf, produto.md, pagina_de_vendas.md, meta.json}
Limites: ORBE_PRODUTOS_POR_DIA (3), ≥ ORBE_PRODUTO_GAP_H (2h) entre produtos,
e pausa se já há 3 esperando o dono (não lota o Telegram).
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import os
import re
import time
from pathlib import Path
from typing import Any

PRODUTOS = Path("data/produtos")
RESULTADOS = Path("data/resultados")
REEMBOLSO = ("Você pode pedir reembolso integral em até 7 dias após a compra, sem precisar "
             "justificar (direito de arrependimento — art. 49 do Código de Defesa do Consumidor).")

# ------------------------------------------------------------------ limpeza
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF"
    "\u2B50\u2B55\u2934\u2935\u3030\u303D\u3297\u3299\uFE0F\u20E3\u200D]")
_MANTER = {"\u2610", "\u2611", "\u2612", "\u2713", "\u2714"}   # ☐ ☑ ☒ ✓ ✔ (úteis em checklist)
_BASTIDOR = re.compile(r"gumroad|p[áa]gina de vendas|\(ou docx\)|pronto para usar no|"
                       r"que (você|o comprador) receber[áa]|texto que ser[áa]|inserido no pdf|\.?docx\b|microsoft word", re.I)
_SECOES_FORA = re.compile(r"p[áa]gina de vendas|garantia|pol[íi]tica de reembolso|reembolso", re.I)
_PROMESSAS = [
    (re.compile(r"preenchimento digital", re.I), "anotação num leitor de PDF"),
    (re.compile(r"(seu |no seu )?editor de texto( preferido)?", re.I), "um leitor de PDF"),
    (re.compile(r"(todos\s+)?com\s+campos\s+(edit[áa]veis|preench[íi]veis)", re.I), "com espaços para preencher à mão"),
    (re.compile(r"\b(recursos|modelos|templates|arquivos)\s+(edit[áa]veis|preench[íi]veis)", re.I), r"\1 prontos para imprimir"),
    (re.compile(r"\(?\s*PDF\s+(edit[áa]vel|preench[íi]vel)\s*\)?", re.I), "(para imprimir)"),
    (re.compile(r"formato\s+edit[áa]vel(\s*\([^)]*\))?", re.I), "formato para imprimir"),
    (re.compile(r"[^.\n]*clic\w*\s+n[oa]s?\s+campos?[^.\n]*\.?", re.I), " Basta imprimir (ou anotar num leitor de PDF) e preencher."),
    (re.compile(r"campos\s+(edit[áa]veis|preench[íi]veis)", re.I), "espaços para preencher"),
    (re.compile(r"\b(edit[áa]ve(l|is)|preench[íi]ve(l|is))\b", re.I), "para imprimir"),
    (re.compile(r"n[ãa]o h[áa] (pol[íi]tica de )?reembolso[^.\n]*\.?", re.I), ""),
]


# limite técnico interno ("só texto") não é argumento de venda: some do produto
_LIMITACAO = re.compile(r"[^.\n]*\b(texto puro|100\s?% (em )?texto|sem imagens|n[ãa]o (h[áa]|cont[ée]m|possui|tem) "
                        r"(imagens|gr[áa]ficos|v[íi]deos|recursos interativos))\b[^.\n]*\.\s?", re.I)


def _limpar_promessas(txt: str) -> str:
    txt = _LIMITACAO.sub(" ", txt)
    txt = re.sub(r"(?m)^ (?=\w)", "", txt)
    for rx, novo in _PROMESSAS:
        txt = rx.sub(novo, txt)
    return re.sub(r"  +", " ", txt)


def _sem_emoji(txt: str) -> str:
    txt = re.sub(r"(\d)\uFE0F?\u20E3", r"\1", txt)          # 1️⃣ → 1
    return "".join(ch if ch in _MANTER else _EMOJI.sub("", ch) for ch in txt)


def _corpo_do_rascunho(md: str) -> str:
    """Tira cabeçalho do arquivo (até o 1º '---'), seções de venda/garantia e o título do rascunho."""
    partes = md.split("\n---\n", 1)
    md = partes[1] if len(partes) == 2 and md.lstrip().startswith("# ") else md
    linhas, saida, pulando_nivel = md.splitlines(), [], 0
    for ln in linhas:
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            nivel, titulo = len(m.group(1)), m.group(2)
            if pulando_nivel and nivel <= pulando_nivel:
                pulando_nivel = 0
            if not pulando_nivel and _SECOES_FORA.search(titulo):
                pulando_nivel = nivel
                continue
        if pulando_nivel:
            continue
        if m and re.search(r"conte[úu]do completo|texto que ser[áa]|inserido no pdf", m.group(2), re.I):
            continue
        saida.append(ln)
    corpo = "\n".join(saida)
    corpo = re.sub(r"^\s*#\s+.*\n", "", corpo.lstrip(), count=1)   # título do rascunho sai (vira capa)
    corpo = "\n".join(ln for ln in corpo.splitlines() if not _BASTIDOR.search(ln))
    corpo = _limpar_promessas(corpo)
    corpo = re.sub(r"^(#{1,6})\s+\*\*(.+?)\*\*\s*$", r"\1 \2", corpo, flags=re.M)
    corpo = re.sub(r"^(#{1,6}\s.*?)\s*\((para imprimir|formato para imprimir)\)", r"\1", corpo, flags=re.M)
    corpo = re.sub(r"^(\s*[-*]\s+)\[ \]\s*", r"\1☐ ", corpo, flags=re.M)
    corpo = re.sub(r"\n(\s*-{3,}\s*\n)+", "\n\n", corpo)                 # separadores soltos
    corpo = re.sub(r"\n{3,}", "\n\n", _sem_emoji(corpo))
    return corpo.strip()


def _titulos(corpo: str) -> list[str]:
    return [re.sub(r"[*_`]", "", m.group(2)).strip()
            for m in re.finditer(r"^(##)\s+(.+)$", corpo, re.M)][:30]


# ------------------------------------------------------------------ PDF
CSS = """
@page { size: A4; margin: 22mm 20mm 20mm 20mm;
        @bottom-center { content: counter(page) " / " counter(pages); font-size: 9pt; color: #888; } }
@page capa { margin: 0; @bottom-center { content: none; } }
body { font-family: 'DejaVu Sans', 'Liberation Sans', sans-serif; font-size: 10.5pt; line-height: 1.5; color: #222; }
.capa { page: capa; height: 297mm; background: linear-gradient(160deg, #1f3b73 0%, #3a6ea5 60%, #7fb2e5 100%);
        color: white; padding: 70mm 22mm 0 22mm; box-sizing: border-box; page-break-after: always; }
.capa h1 { font-size: 30pt; line-height: 1.15; margin: 0 0 8mm 0; border: none; color: white; }
.capa .sub { font-size: 14pt; opacity: .92; }
.capa .rod { position: absolute; bottom: 20mm; font-size: 10pt; opacity: .8; }
.sumario { page-break-after: always; } .sumario li { margin: 2px 0; }
h1, h2 { color: #1f3b73; } h2 { border-bottom: 2px solid #3a6ea5; padding-bottom: 3px; margin-top: 18px;
        page-break-after: avoid; } h3 { color: #3a6ea5; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #b9c7da; padding: 5px 7px; vertical-align: top; } th { background: #e8eef7; }
li { margin: 3px 0; } blockquote { border-left: 4px solid #3a6ea5; margin: 8px 0; padding: 4px 12px; background: #f3f6fb; }
code { background: #f1f1f1; padding: 0 3px; } .termos { font-size: 9pt; color: #555; margin-top: 24px;
        border-top: 1px solid #ccc; padding-top: 8px; }
"""


def gerar_pdf(titulo: str, subtitulo: str, corpo_md: str, destino: Path) -> int:
    """Monta capa + sumário + conteúdo e grava o PDF. Devolve nº de páginas."""
    import markdown
    from weasyprint import HTML

    corpo_html = markdown.markdown(corpo_md, extensions=["tables", "sane_lists"])
    sumario = "".join(f"<li>{_html.escape(re.sub(r'^\d+[.)]?\s*', '', t))}</li>" for t in _titulos(corpo_md))
    doc = f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<section class="capa"><h1>{_html.escape(titulo)}</h1><div class="sub">{_html.escape(subtitulo)}</div>
<div class="rod">Produto digital em PDF · uso pessoal</div></section>
<section class="sumario"><h2>O que tem aqui</h2><ol>{sumario}</ol></section>
{corpo_html}
<div class="termos">Uso pessoal. Não é permitido revender ou redistribuir este arquivo. {REEMBOLSO}</div>
</body></html>"""
    render = HTML(string=doc).render()
    destino.parent.mkdir(parents=True, exist_ok=True)
    render.write_pdf(str(destino))
    return len(render.pages)


# ------------------------------------------------------------------ IA (chamada pequena)
def _json_da_ia(txt: str) -> dict:
    i, j = txt.find("{"), txt.rfind("}")
    return json.loads(txt[i:j + 1]) if i >= 0 and j > i else {}


async def _embalagem(corpo: str) -> tuple[dict, str]:
    import llm_pool

    amostra = corpo[:2500]
    sistema = ("Você é redator de páginas de venda HONESTAS para produtos digitais no Brasil. "
               "Nunca prometa renda, resultados, bônus, garantias ou algo que não esteja no sumário. "
               "ATENÇÃO: o PDF NÃO é editável e NÃO tem campos preenchíveis — é para imprimir ou anotar. "
               "Sem emojis. Responda SOMENTE com JSON válido.")
    user = ("Sumário REAL do PDF:\n- " + "\n- ".join(_titulos(corpo)) +
            f"\n\nTrecho do conteúdo:\n{amostra}\n\n"
            'Devolva JSON: {"titulo": "até 60 caracteres", "subtitulo": "até 90 caracteres", '
            '"preco_brl": inteiro entre 12 e 39, "para_quem": "1 frase", '
            '"pagina_de_vendas": "markdown, 120-220 palavras: dor do comprador, o que o PDF resolve, '
            'lista do que tem dentro (só itens do sumário), para quem NÃO é"}')
    for tentativa in range(3):          # IA às vezes devolve JSON quebrado: tenta de novo
        txt, motor = await llm_pool.chat(sistema, user, max_tokens=2500, temperature=0.6 - 0.2 * tentativa)
        try:
            d = _json_da_ia(txt)
        except Exception:
            d = {}
        if d.get("titulo") and d.get("pagina_de_vendas"):
            return d, motor
    raise RuntimeError("IA não devolveu a embalagem em JSON (3 tentativas)")


# ------------------------------------------------------------------ seleção e limites
def _metas() -> list[dict]:
    out = []
    for p in PRODUTOS.glob("*/meta.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return sorted(out, key=lambda m: m.get("criado", 0))


def pode_produzir() -> tuple[bool, str]:
    metas = _metas()
    agora = time.time()
    por_dia = int(os.environ.get("ORBE_PRODUTOS_POR_DIA", "3") or 3)
    gap = float(os.environ.get("ORBE_PRODUTO_GAP_H", "2") or 2) * 3600
    enviados = [m for m in metas if m.get("status") != "reprovado"]
    if sum(1 for m in metas if m.get("status") == "aguardando_dono") >= 3:
        return False, "3 produtos esperando o dono aprovar"
    if sum(1 for m in enviados if agora - m.get("criado", 0) < 86400) >= por_dia:
        return False, f"limite de {por_dia} produtos/dia"
    if enviados and agora - enviados[-1].get("criado", 0) < gap:
        return False, "intervalo mínimo entre produtos"
    if sum(1 for m in metas if agora - m.get("criado", 0) < 86400) >= 12:
        return False, "limite de 12 tentativas/dia"
    if metas and agora - metas[-1].get("criado", 0) < 1200:
        return False, "intervalo entre tentativas (20 min)"
    return True, ""


def proximo_rascunho() -> Path | None:
    usados = {m.get("origem") for m in _metas()}
    cands = sorted(RESULTADOS.glob("*missao_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in cands:
        txt = p.read_text(encoding="utf-8")
        if p.name not in usados and len(txt.split()) >= 800 and re.search(r"^- brief:\s*\S+", txt, re.M):
            return p
    return None


# ------------------------------------------------------------------ o trabalho
def _brief_do_rascunho(md: str) -> dict | None:
    m = re.search(r"^- brief:\s*(\S+)", md, re.M)
    if not m:
        return None
    import mercado

    return mercado.achar(m.group(1))


async def produzir(rascunho: Path, agente: str = "") -> dict[str, Any]:
    bruto = rascunho.read_text(encoding="utf-8")
    brief = _brief_do_rascunho(bruto)
    corpo = _corpo_do_rascunho(bruto)
    if len(corpo.split()) < 500:
        raise RuntimeError("rascunho curto demais depois da limpeza")
    emb, motor = await _embalagem(corpo)
    titulo = _limpar_promessas(_sem_emoji(str(emb["titulo"])))[:80].strip()
    subtitulo = _limpar_promessas(_sem_emoji(str(emb.get("subtitulo", ""))))[:120].strip()
    emb["pagina_de_vendas"] = _limpar_promessas(_sem_emoji(str(emb["pagina_de_vendas"])))
    try:
        preco = max(12, min(39, int(emb.get("preco_brl", 19))))
    except Exception:
        preco = 19
    pid = time.strftime("%Y%m%d-%H%M%S") + "-" + re.sub(r"[^a-z0-9]+", "-", titulo.lower())[:40].strip("-")
    pasta = PRODUTOS / pid
    paginas = gerar_pdf(titulo, subtitulo, corpo, pasta / "produto.pdf")
    # IA às vezes inventa "15 páginas": vale o número REAL do PDF
    _pg = re.compile(r"\b\d+\s+p[áa]ginas\b", re.I)
    if _pg.search(subtitulo) or _pg.search(corpo):
        subtitulo = _pg.sub(f"{paginas} páginas", subtitulo)
        corpo = _pg.sub(f"{paginas} páginas", corpo)
        paginas = gerar_pdf(titulo, subtitulo, corpo, pasta / "produto.pdf")
    emb["pagina_de_vendas"] = _pg.sub(f"{paginas} páginas", str(emb["pagina_de_vendas"]))
    venda = (f"# {titulo}\n\n**{subtitulo}**\n\n{_sem_emoji(str(emb['pagina_de_vendas'])).strip()}\n\n"
             f"## O que você recebe\n- 1 arquivo PDF com {paginas} páginas (para ler na tela ou imprimir)\n"
             f"- Entrega imediata por download após a compra\n\n"
             f"## Reembolso\n{REEMBOLSO}\n\n**Preço sugerido:** R$ {preco}\n")
    (pasta / "produto.md").write_text(f"# {titulo}\n\n{corpo}\n", encoding="utf-8")
    (pasta / "pagina_de_vendas.md").write_text(venda, encoding="utf-8")
    meta = {"id": pid, "titulo": titulo, "subtitulo": subtitulo, "preco_brl": preco,
            "paginas": paginas, "palavras": len(corpo.split()), "origem": rascunho.name,
            "motor": motor, "agente": agente, "criado": time.time(), "status": "aguardando_dono",
            "brief": brief.get("id") if brief else "",
            "evidencias": (brief or {}).get("evidencias", [])[:3]}
    return await _julgar(pasta, meta, corpo, brief)


async def _julgar(pasta: Path, meta: dict, corpo: str, brief: dict | None) -> dict:
    """Passa pelo crítico e decide: aguardando_dono | reprovado | aguardando_critica (IA sem cota)."""
    meta["critica"] = await criticar(corpo, meta, brief)
    if meta["critica"].get("indisponivel"):
        meta["status"] = "aguardando_critica"      # não avaliado ≠ ruim: tenta de novo depois
    else:
        meta["status"] = "aguardando_dono" if meta["critica"]["aprovado"] else "reprovado"
        pj = meta["critica"].get("preco_justo_brl")
        if pj and pj < int(meta.get("preco_brl", pj)):          # preço segue o mercado, nunca sobe
            antigo = int(meta["preco_brl"])
            meta["preco_brl"] = pj
            pv = pasta / "pagina_de_vendas.md"
            if pv.exists():
                pv.write_text(pv.read_text(encoding="utf-8").replace(f"R$ {antigo}", f"R$ {pj}"), encoding="utf-8")
    (pasta / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if brief and meta["status"] != "aguardando_critica":
        import mercado

        tent = int(brief.get("tentativas", 0)) + 1
        mercado.marcar(brief["id"], "usado" if meta["status"] != "reprovado" else "novo", tentativas=tent)
        if meta["status"] == "reprovado" and tent >= 2:
            mercado.marcar(brief["id"], "descartado", motivo="reprovado 2x pelo crítico")
    __import__("state_backup").sujo()
    return meta


def pendente_critica() -> str | None:
    for m in _metas():
        if m.get("status") == "aguardando_critica":
            return m["id"]
    return None


async def recriticar(pid: str) -> dict:
    """(Re)avalia um produto já pronto — usado pra fila 'aguardando_critica' e pra produtos antigos."""
    pasta = PRODUTOS / pid
    meta = json.loads((pasta / "meta.json").read_text(encoding="utf-8"))
    corpo = re.sub(r"^#\s+.*\n", "", (pasta / "produto.md").read_text(encoding="utf-8"), count=1)
    brief = None
    if meta.get("brief"):
        import mercado

        brief = mercado.achar(meta["brief"])
    return await _julgar(pasta, meta, corpo, brief)


NOTA_MINIMA = 8.0


def _amostra(corpo: str, n: int = 2000) -> str:
    """O crítico vê começo, meio e fim (tabelas costumam estar no meio/fim), sem estourar a cota."""
    if len(corpo) <= 3 * n:
        return corpo
    m = len(corpo) // 2
    return f"{corpo[:n]}\n[...]\n{corpo[m - n // 2:m + n // 2]}\n[...]\n{corpo[-n:]}"


def _checagens(corpo: str, paginas: int) -> list[str]:
    """Defeitos objetivos que reprovam sem nem perguntar à IA."""
    prob = []
    tit = _titulos(corpo)
    if paginas < 8:
        prob.append(f"só {paginas} páginas")
    if len(corpo.split()) < 1500:
        prob.append("conteúdo curto (< 1500 palavras)")
    if len(tit) > 20:
        prob.append(f"sumário bagunçado ({len(tit)} seções principais)")
    if any(re.search(r"\[[^\]]{2,40}\]", t) for t in tit):
        prob.append("títulos com marcadores [..] vazando no sumário")
    if len(re.findall(r"\[(Nome|Data|Valor|Empresa|Cargo)[^\]]*\]", corpo)) > 25:
        prob.append("excesso de campos-modelo [..] sem conteúdo real")
    return prob


async def criticar(corpo: str, meta: dict, brief: dict | None) -> dict:
    """🧐 CRÍTICO: comprador exigente + editor de marketplace. Só nota alta passa."""
    import llm_pool

    objetivos = _checagens(corpo, int(meta.get("paginas", 0)))
    ctx = ""
    if brief:
        ctx = (f"\nPesquisa de mercado: produto '{brief.get('produto')}', público {brief.get('publico')}, "
               f"diferencial exigido: {brief.get('diferencial')}, itens obrigatórios: "
               f"{'; '.join(brief.get('itens_obrigatorios', []))}. Concorrentes: {brief.get('concorrentes_preco')}.")
    sistema = ("Você é um comprador EXIGENTE e um editor de marketplace (Etsy/Hotmart). Avalie com rigor: "
               "você só pagaria se fosse claramente útil, completo e melhor que o grátis da internet. "
               "Responda SOMENTE JSON.")
    user = (f"Produto: {meta['titulo']} — {meta.get('subtitulo', '')} ({meta.get('paginas')} págs, "
            f"R$ {meta.get('preco_brl')}).{ctx}\nSumário: {'; '.join(_titulos(corpo))}\n"
            "(O PDF final já sai diagramado: capa, sumário, tipografia e tabelas formatadas — avalie o CONTEÚDO.)\n"
            f"Trechos do início, meio e fim:\n{_amostra(corpo)}\n\n"
            'JSON: {"utilidade": 0-10, "acabamento": 0-10, "vende": 0-10, '
            '"cumpre_pesquisa": 0-10, "preco_justo_brl": inteiro (competitivo frente aos concorrentes), '
            '"problemas": ["até 5, específicos"], "veredito": "aprovar|reprovar"}')
    d, erro = None, ""
    for tentativa in range(3):
        try:
            txt, _ = await llm_pool.chat(sistema, user, max_tokens=1500, temperature=0.2)
            d = _json_da_ia(txt)
            break
        except Exception as exc:   # cota por minuto logo após a embalagem / JSON quebrado
            erro = str(exc)[:120]
            if tentativa < 2:
                await asyncio.sleep(45)
    if d is None:
        return {"aprovado": False, "indisponivel": True, "media": 0.0, "notas": {},
                "problemas": objetivos + [f"crítico sem cota agora ({erro[:60]}) — reavalia depois"]}
    notas = [float(d.get(k, 0) or 0) for k in ("utilidade", "acabamento", "vende")]
    if brief:
        notas.append(float(d.get("cumpre_pesquisa", 0) or 0))
    media = round(sum(notas) / len(notas), 1) if notas else 0.0
    vende = float(d.get("vende", 0) or 0)
    aprovado = (not objetivos and d.get("veredito") == "aprovar" and media >= NOTA_MINIMA
                and min(notas) >= 7 and vende >= 8)       # o dono só quer o que VENDE
    try:
        preco_justo = max(9, min(39, int(float(d.get("preco_justo_brl") or 0)))) if d.get("preco_justo_brl") else None
    except (TypeError, ValueError):
        preco_justo = None
    return {"aprovado": aprovado, "media": media, "preco_justo_brl": preco_justo,
            "notas": {k: d.get(k) for k in ("utilidade", "acabamento", "vende", "cumpre_pesquisa")},
            "problemas": objetivos + [str(x) for x in d.get("problemas", [])][:5]}


def garantir_pdf(pid: str) -> Path | None:
    """PDF não viaja no backup (pesado): se sumiu (Render reiniciou), refaz do produto.md."""
    pasta = PRODUTOS / pid
    pdf = pasta / "produto.pdf"
    if pdf.exists():
        return pdf
    try:
        meta = json.loads((pasta / "meta.json").read_text(encoding="utf-8"))
        md = (pasta / "produto.md").read_text(encoding="utf-8")
        corpo = re.sub(r"^#\s+.*\n", "", md, count=1)
        gerar_pdf(meta["titulo"], meta.get("subtitulo", ""), corpo, pdf)
        return pdf
    except Exception:
        return None


def marcar(pid: str, status: str) -> dict | None:
    p = PRODUTOS / pid / "meta.json"
    if not p.exists():
        return None
    meta = json.loads(p.read_text(encoding="utf-8"))
    meta["status"] = status
    meta[f"{status}_em"] = time.time()
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    __import__("state_backup").sujo()
    return meta


def achar(chave: str) -> str | None:
    """Botão do Telegram leva só o começo do id (limite de 64 bytes)."""
    for p in PRODUTOS.glob(f"{chave}*/meta.json"):
        return p.parent.name
    return None
