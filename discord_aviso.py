"""Aviso ao dono. So quando entra dinheiro real. So no Discord.

Sem webhook, silencio. Dinheiro simulado nao dispara.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


def _url() -> str:
    u = os.environ.get("ORBE_DISCORD_WEBHOOK", "").strip()
    if not u:
        try:
            from secrets_vault import VAULT
            extra = ((VAULT.get("discord") or {}).get("extra") or {})
            u = str(extra.get("webhook") or extra.get("url") or "").strip()
        except Exception:
            u = ""
    if not u:
        arq = Path("data/discord_webhook.txt")
        if arq.exists():
            linha = arq.read_text(encoding="utf-8").strip().splitlines()
            u = linha[0].strip() if linha else ""
    if u.startswith("https://discord.com/api/webhooks/") or u.startswith("https://discordapp.com/api/webhooks/"):
        return u
    return ""


def avisar(venda: dict) -> bool:
    url = _url()
    if not url or not isinstance(venda, dict):
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
    corpo = json.dumps({"content": texto[:1800]}).encode()
    req = urllib.request.Request(
        url, data=corpo, headers={"Content-Type": "application/json", "User-Agent": "orbe"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return 200 <= r.status < 300
    except Exception:
        return False
