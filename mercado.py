"""🔎 PESQUISADOR DE MERCADO — só se produz o que JÁ vende.

Pesquisa na web DE VERDADE (Groq browser_search) o que está vendendo no Etsy /
Hotmart / Kiwify num nicho e devolve um BRIEF: produto, público, dor, itens
obrigatórios, diferencial, preço e EVIDÊNCIAS (URLs + sinal de venda).
Sem evidência verificável (URL) ou confiança < 6 → brief descartado.
data/briefs.json: [{id, tema, ..., status: novo|em_producao|usado|descartado}]
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

BRIEFS = Path("data/briefs.json")
_IMPOSSIVEL = re.compile(r"qr ?code|v[íi]deo|aplicativo|\bapp\b|[áa]udio|planilha|excel|google sheets|foto", re.I)


def ler() -> list[dict]:
    try:
        return json.loads(BRIEFS.read_text(encoding="utf-8"))
    except Exception:
        return []


def salvar(itens: list[dict]) -> None:
    BRIEFS.parent.mkdir(parents=True, exist_ok=True)
    BRIEFS.write_text(json.dumps(itens[-60:], ensure_ascii=False, indent=1), encoding="utf-8")
    __import__("state_backup").sujo()


def disponivel() -> dict | None:
    """Brief bom ainda não usado (o mais confiante primeiro)."""
    novos = [b for b in ler() if b.get("status") == "novo"]
    return max(novos, key=lambda b: b.get("confianca", 0)) if novos else None


def marcar(bid: str, status: str, **extra: Any) -> None:
    itens = ler()
    for b in itens:
        if b.get("id") == bid:
            b["status"] = status
            b.update(extra)
    salvar(itens)


def achar(bid: str) -> dict | None:
    return next((b for b in ler() if b.get("id") == bid), None)


async def pesquisar(tema: str, ja_feitos: list[str] | None = None) -> dict:
    import llm_pool

    evitar = "; ".join((ja_feitos or [])[-8:]) or "nenhum"
    sistema = ("Você é pesquisador de mercado de produtos digitais imprimíveis. Use a busca na web. "
               "Seja cético: só conta como evidência o que você VIU numa página (nº de vendas, avaliações, "
               "selo 'Bestseller', posição em ranking). Nunca invente URL ou número.")
    user = (f"Nicho: {tema}. Pesquise no Etsy (etsy.com) e na Hotmart/Kiwify quais PDFs imprimíveis "
            "(planners, checklists, fichas, modelos) desse nicho estão vendendo AGORA. Depois proponha UM "
            "produto em português para o público brasileiro, com demanda comprovada e um diferencial claro "
            "frente aos concorrentes. LIMITE: o produto é UM PDF só com texto, tabelas, checklists e espaços "
            "para preencher — nada de vídeo, QR code, app, áudio, imagens/fotos, planilha ou arquivo extra; "
            "o diferencial tem que caber nisso (ex.: mais completo, adaptado ao Brasil, níveis, exemplos prontos) "
            "e NÃO cite esse limite no diferencial (ele é interno). "
            f"Não repita estes já feitos: {evitar}.\n"
            'Responda SOMENTE com JSON: {"produto": "nome curto", "publico": "...", "dor": "...", '
            '"itens_obrigatorios": ["5 a 12 itens concretos do PDF"], "diferencial": "...", '
            '"preco_brl": inteiro na faixa BAIXA-MÉDIA dos concorrentes, "evidencias": [{"url": "https://...", "sinal": "o que prova venda"}], '
            '"concorrentes_preco": "faixa de preço vista", "confianca": 0-10}')
    txt, motor = await llm_pool.chat(sistema, user, max_tokens=3000, temperature=0.4, web=True)
    i, j = txt.find("{"), txt.rfind("}")
    d = json.loads(txt[i:j + 1]) if i >= 0 and j > i else {}
    evid = [e for e in d.get("evidencias", []) if isinstance(e, dict)
            and re.match(r"https?://[^\s]+\.[a-z]{2,}", str(e.get("url", "")))]
    brief = {
        "id": time.strftime("b%Y%m%d%H%M%S"), "tema": tema, "produto": str(d.get("produto", ""))[:90],
        "publico": d.get("publico", ""), "dor": d.get("dor", ""),
        "itens_obrigatorios": [str(x) for x in d.get("itens_obrigatorios", [])
                               if not _IMPOSSIVEL.search(str(x))][:12],
        "diferencial": d.get("diferencial", ""), "preco_brl": d.get("preco_brl", 0),
        "concorrentes_preco": d.get("concorrentes_preco", ""), "evidencias": evid[:6],
        "confianca": float(d.get("confianca", 0) or 0), "motor": motor, "criado": time.time(),
    }
    if _IMPOSSIVEL.search(str(brief["diferencial"])):
        brief["confianca"] = min(brief["confianca"], 5.0)   # diferencial que a máquina não entrega
    ok = brief["produto"] and len(brief["itens_obrigatorios"]) >= 4 and evid and brief["confianca"] >= 6
    brief["status"] = "novo" if ok else "descartado"
    if not ok:
        brief["motivo"] = "sem evidência verificável ou confiança baixa"
    itens = ler()
    itens.append(brief)
    salvar(itens)
    return brief


def prompt_do_brief(b: dict) -> str:
    from telegram_sim import REGRAS_PRODUTO

    itens = "\n".join(f"- {x}" for x in b.get("itens_obrigatorios", []))
    return (f"Produza o PDF imprimível \"{b['produto']}\" para: {b.get('publico')}. "
            f"Dor que resolve: {b.get('dor')}. Diferencial obrigatório frente aos concorrentes: "
            f"{b.get('diferencial')}.\nItens OBRIGATÓRIOS (cada um com conteúdo completo, pronto pra usar):\n"
            f"{itens}\nNível de qualidade: melhor que os concorrentes que vendem por "
            f"{b.get('concorrentes_preco') or 'R$ 15-40'}. Em português do Brasil. Nunca escreva no produto "
            "que ele é 'texto puro', 'sem imagens' ou similar — o PDF final é diagramado. " + REGRAS_PRODUTO)
