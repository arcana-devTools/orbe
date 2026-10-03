"""O Chrome do celular ja esta logado. A colonia trabalha por ele.

Nao pede conta. Nao digita senha. Nao aceita termo.
"""
from __future__ import annotations

import time

_ultimo = 0.0
_PASSOS = (
    ("https://app.hotmart.com/", ("Ferramentas", "Criar produto", "Home", "Entrar na Hotmart")),
    ("https://afiliados.mercadolivre.com.br/", ("Gerar link", "Criar link", "Meus links", "Afiliados")),
)


def passo() -> dict:
    """Desligado. Abria Hotmart ou Mercado Livre e a pagina ficava parada."""
    return {"ok": True, "parado": True}
