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
    # Mercado Livre: programa de afiliados, login só pelo celular/2FA do dono
    try:
        if not Path("data/ml_sessao.json").exists():
            saida.append({
                "onde": "Mercado Livre (afiliados)",
                "como": "entrar em afiliados.mercadolivre.com.br pelo /desktop (1x)",
                "porque": "login/2FA é só o dono",
                "depois": "a colônia gera os links de afiliado do ML sozinha",
            })
    except Exception:
        pass
    # Hotmart: só entra se o dono criar a conta e mandar as credenciais
    try:
        from secrets_vault import VAULT

        if not (VAULT.get("hotmart") or {}).get("extra", {}).get("client_id"):
            saida.append({
                "onde": "Hotmart",
                "como": "criar a conta de produtor e mandar as credenciais da API num .txt",
                "porque": "cadastro e termos são do dono",
                "depois": "entra no mesmo esquema da Kiwify",
            })
    except Exception:
        pass
    return saida


def txt() -> str:
    itens = lista()
    if not itens:
        return ""
    linhas = ["🔧 Falta só você (1x cada, depois some daqui):"]
    for i in itens:
        linhas.append(f"  • {i['onde']}: {i['como']}")
    return "\n".join(linhas)
