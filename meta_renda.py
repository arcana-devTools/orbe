"""Meta de renda real. A colonia so para quando a SOMA de todas as plataformas chegar aqui.

Nao e 50 mil numa plataforma so. Canal, loja ou outro caminho e escolha da colonia.
Dinheiro simulado nao conta.
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
        "regra": "trabalhar ate a soma real bater 50 mil; 24h sem descanso e sem filtro; celular com acesso total; Telegram so as 7h e as 18h",
        "amazon": "conta criada pelo dono; login ainda nao esta no cofre",
        "kiwify": "conta ja ligada; venda cai nela",
        "shopee": "conta de afiliado ja aprovada; comissao cai nela",
    }
