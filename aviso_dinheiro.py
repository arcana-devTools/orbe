"""Aviso ao dono. So quando entra dinheiro real. So no Telegram.

Dinheiro simulado nao dispara. Sem token ou chat, silencio.
"""
from __future__ import annotations

import json
import os
import urllib.request


def _cfg() -> tuple[str, str]:
    tok = os.environ.get("ORBE_TG_TOKEN", "").strip()
    chat = os.environ.get("ORBE_TG_CHAT", "").strip()
    if tok and chat:
        return tok, chat
    try:
        from autopilot import AUTOPILOT
        tok = tok or str(AUTOPILOT.cfg.get("bot_token") or "").strip()
        chat = chat or str(AUTOPILOT.cfg.get("chat_id") or "").strip()
    except Exception:
        pass
    return tok, chat


def avisar(venda: dict) -> bool:
    tok, chat = _cfg()
    if not tok or not chat or not isinstance(venda, dict):
        return False
    try:
        import vendas
        soma = float(vendas.totais(vendas.ler()).get("BRL") or 0)
    except Exception:
        soma = 0.0
    moeda = str(venda.get("moeda") or "")
    valor = venda.get("valor")
    loja = str(venda.get("loja") or "loja")
    simbolo = {"BRL": "R$", "USD": "US$", "EUR": "€"}.get(moeda, moeda)
    texto = f"Entrou dinheiro: {simbolo} {valor} na {loja}. Soma real em reais: R$ {soma:.2f}."
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    corpo = json.dumps({"chat_id": chat, "text": texto[:4000]}).encode()
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return 200 <= r.status < 300
    except Exception:
        return False
