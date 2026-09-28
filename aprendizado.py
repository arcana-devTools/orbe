"""📈 APRENDIZADO — a colônia melhora com o próprio histórico.

1. Lições do crítico: os problemas que ele apontou nos produtos REPROVADOS viram regra
   ("não repita") no pedido do próximo produto. Funciona já, sem loja.
2. O que vende vira variação: produto com venda real → próxima pesquisa de mercado busca
   um complemento/variação para o mesmo público.
3. Encalhado: publicado há 30+ dias sem venda → a IA sugere novo título, tags e preço
   (o publicador aplica quando a loja estiver conectada; o dono vê no resumo).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

APR = Path("data/aprendizado.json")
DIAS_ENCALHE = 30


def _ler() -> dict:
    try:
        return json.loads(APR.read_text(encoding="utf-8"))
    except Exception:
        return {"variados": [], "revisados": {}}


def _salvar(d: dict) -> None:
    APR.parent.mkdir(parents=True, exist_ok=True)
    APR.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


def _metas() -> list[dict]:
    import acabamento

    return acabamento._metas()


# ------------------------------------------------------------------ 1. lições do crítico
_GENERICO = re.compile(r"crítico sem cota|indispon", re.I)


def licoes(n: int = 6) -> list[str]:
    """Problemas mais recentes apontados pelo crítico (sem repetição)."""
    vistos, out = set(), []
    for m in reversed(_metas()):
        if m.get("status") != "reprovado":
            continue
        for p in (m.get("critica") or {}).get("problemas", []):
            p = re.sub(r"\s+", " ", str(p)).strip()
            chave = p.lower()[:50]
            if not p or _GENERICO.search(p) or chave in vistos:
                continue
            vistos.add(chave)
            out.append(p[:170])
            if len(out) >= n:
                return out
    return out


def licoes_prompt() -> str:
    ls = licoes()
    if not ls:
        return ""
    return ("Erros que o crítico JÁ apontou em produtos anteriores — NÃO repita: "
            + " ".join(f"({i}) {x}" for i, x in enumerate(ls, 1)) + " ")


# ------------------------------------------------------------------ 2. o que vende vira variação
def tema_quente() -> dict | None:
    """Produto com venda real que ainda não ganhou variação → inspira a próxima pesquisa."""
    d = _ler()
    for m in sorted(_metas(), key=lambda x: -int(x.get("vendas", 0))):
        if int(m.get("vendas", 0)) > 0 and m["id"] not in d["variados"]:
            tema = m.get("titulo", "")
            if m.get("brief"):
                try:
                    import mercado

                    b = mercado.achar(m["brief"]) or {}
                    tema = b.get("tema") or tema
                except Exception:
                    pass
            return {"pid": m["id"], "tema": tema, "inspiracao": m.get("titulo", ""),
                    "idioma": m.get("idioma") or "pt"}
    return None


def marcar_variado(pid: str) -> None:
    d = _ler()
    if pid not in d["variados"]:
        d["variados"].append(pid)
        _salvar(d)


# ------------------------------------------------------------------ 3. encalhados
def encalhados(agora: float | None = None) -> list[dict]:
    agora = agora or time.time()
    return [m for m in _metas()
            if m.get("status") == "publicado" and int(m.get("vendas", 0)) == 0
            and agora - float(m.get("publicado_em", agora)) > DIAS_ENCALHE * 86400]


async def revisar_encalhados(max_itens: int = 2) -> int:
    """Pede à IA um ajuste (título/tags/preço) pros encalhados. Devolve quantos revisou."""
    import acabamento
    import llm_pool

    d, n = _ler(), 0
    for m in encalhados():
        if time.time() - float(d["revisados"].get(m["id"], 0)) < DIAS_ENCALHE * 86400:
            continue
        en = (m.get("idioma") == "en")
        user = (f"Produto digital publicado há {DIAS_ENCALHE}+ dias SEM nenhuma venda "
                f"({'Etsy, compradores dos EUA, responda em inglês' if en else 'Brasil'}).\n"
                f"Título: {m.get('titulo')}\nSubtítulo: {m.get('subtitulo')}\nTags: {m.get('tags')}\n"
                f"Preço: {acabamento.preco_fmt(m)}\n"
                'JSON: {"titulo": "novo título mais buscável", "tags": ["até 13"], '
                '"preco": inteiro na mesma moeda, "motivo": "1 frase"}')
        try:
            txt, _ = await llm_pool.chat("Você é especialista em SEO de marketplace. Responda SOMENTE JSON.",
                                         user, max_tokens=800, temperature=0.4)
            sug = acabamento._json_da_ia(txt)
        except Exception:
            continue
        if not sug.get("titulo"):
            continue
        p = acabamento.PRODUTOS / m["id"] / "meta.json"
        m["ajuste_sugerido"] = {k: sug.get(k) for k in ("titulo", "tags", "preco", "motivo")}
        m["ajustar"] = True
        p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        d["revisados"][m["id"]] = time.time()
        n += 1
        if n >= max_itens:
            break
    if n:
        _salvar(d)
    return n


def resumo_txt() -> str:
    ls, aj = licoes(), [m for m in _metas() if m.get("ajustar")]
    partes = []
    if ls:
        partes.append(f"📈 {len(ls)} lição(ões) do crítico já entram nos próximos produtos")
    if aj:
        partes.append(f"🔧 {len(aj)} produto(s) encalhado(s) com ajuste sugerido")
    return "\n".join(partes)


def status() -> dict[str, Any]:
    return {"licoes": licoes(), "variados": _ler()["variados"],
            "encalhados": [m["id"] for m in encalhados()],
            "com_ajuste": [m["id"] for m in _metas() if m.get("ajustar")]}
