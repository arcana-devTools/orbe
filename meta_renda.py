"""Meta de renda real. A colonia so para quando o livro-caixa chegar aqui.

Dinheiro simulado da colonia nao conta.
"""
from __future__ import annotations

META_BRL = 50000.0


def progresso() -> dict:
    try:
        import vendas
        tot = vendas.totais(vendas.ler())
        brl = float(tot.get("BRL") or 0)
    except Exception:
        brl = 0.0
    return {
        "meta_brl": META_BRL,
        "real_brl": round(brl, 2),
        "falta_brl": round(max(0.0, META_BRL - brl), 2),
        "parar": brl >= META_BRL,
        "amazon": "conta criada pelo dono; login ainda nao esta no cofre",
        "kiwify": "conta ja ligada; venda cai nela",
        "shopee": "conta de afiliado ja aprovada; comissao cai nela",
    }
