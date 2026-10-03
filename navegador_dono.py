"""O Chrome do celular ja esta logado. A colonia trabalha por ele.

Nao pede conta. Nao digita senha. Nao aceita termo.
"""
from __future__ import annotations

import time

_ultimo = 0.0
_PASSOS = (
    ("https://app.hotmart.com/", ("Produtos", "Criar produto", "Novo produto", "Ferramentas")),
    ("https://afiliados.mercadolivre.com.br/", ("Gerar link", "Criar link", "Meus links", "Afiliados")),
)


def passo() -> dict:
    """Um passo no navegador do dono. No maximo a cada 3 min."""
    global _ultimo
    if time.time() - _ultimo < 180:
        return {"ok": True, "ja": True}
    try:
        import mao
        if not mao.online("celular"):
            return {"ok": False, "motivo": "celular fora"}
        if mao.versao_app() < 4:
            return {"ok": True, "ja": True}
    except Exception as exc:
        return {"ok": False, "motivo": type(exc).__name__}
    _ultimo = time.time()
    url, botoes = _PASSOS[int(time.time() // 180) % len(_PASSOS)]
    try:
        import mao
        mao.pedir("celular", "abrir_url", url)
        for texto in botoes:
            mao.pedir("celular", "clicar", texto, {"texto": texto})
    except Exception as exc:
        return {"ok": False, "motivo": type(exc).__name__}
    return {"ok": True, "url": url}
