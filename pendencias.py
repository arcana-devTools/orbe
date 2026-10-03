"""🔧 Pendências humanas — o que SÓ o dono pode fazer (login, 2FA, aceitar termos).

Aparece no resumo das 19h, nunca como mensagem avulsa: a regra do dono é
contato mínimo. A colônia nunca digita senha, nunca resolve captcha e nunca
aceite contrato — isso é humano por definição.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def lista() -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    # Kiwify: a API pública não cria a própria credencial → precisa do painel
    try:
        import kiwify

        if not kiwify.estado().get("ok"):
            saida.append({
                "onde": "Kiwify",
                "como": "entrar em dashboard.kiwify.com.br pelo /desktop (1x)",
                "porque": "a Kiwify não deixa criar a API Key por fora do painel",
                "depois": "eu crio a chave, publico os produtos e ligo o webhook de vendas",
            })
    except Exception:
        pass
    # Mercado Livre e Hotmart: o Chrome do celular do dono ja esta logado.
    # Nao pedir conta de novo. A colonia usa esse navegador.
    return saida


def txt() -> str:
    itens = lista()
    if not itens:
        return ""
    linhas = ["🔧 Falta só você (1x cada, depois some daqui):"]
    for i in itens:
        linhas.append(f"  • {i['onde']}: {i['como']}")
    return "\n".join(linhas)
