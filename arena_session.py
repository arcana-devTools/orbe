"""Sessão auto-renovável da Arena (descoberto em 25/09/2026).

MECANISMO PROVADO: qualquer GET autenticado (ex.: /api/me) com o cookie
chunked arena-auth-prod-v1.0/v1.1 faz o servidor responder com Set-Cookie
NOVOS: access renovado (+1h), refresh_token ROTACIONADO e Max-Age 400 dias.
Salvando o par de volta, a sessão se perpetua — sem colar cookie novo.

Uso:
    await arena_session.renovar(ctx)          # renova + salva em data/
    await arena_session.renovar_e_injetar()   # renova usando/reaproveitando o perfil
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

DATA = Path("data")
ARQ = DATA / "owner_cookies.txt"
URL_ME = "https://arena.ai/api/me"

_NOME0 = "arena-auth-prod-v1.0"
_NOME1 = "arena-auth-prod-v1.1"


def _ler_arquivo() -> dict[str, str]:
    if not ARQ.exists():
        return {}
    pares = {}
    for linha in ARQ.read_text().splitlines():
        if "=" in linha:
            nome, _, valor = linha.partition("=")
            pares[nome.strip()] = valor.strip()
    return pares


def _exp_do_access(c0: str) -> int | None:
    """Decodifica o chunk v1.0+v1.1 e devolve o expires_at do access token."""
    try:
        pares = _ler_arquivo()
        c0 = c0 or pares.get(_NOME0, "")
        c1 = pares.get(_NOME1, "")
        corpo = (c0[7:] if c0.startswith("base64-") else c0) + c1
        corpo += "=" * (-len(corpo) % 4)
        dados = json.loads(base64.b64decode(corpo))
        return int(dados.get("expires_at", 0)) or None
    except Exception:
        return None


def _salvar(c0: str, c1: str) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = ARQ.with_suffix(".tmp")
    tmp.write_text(f"{_NOME0}={c0}\n{_NOME1}={c1}\n")
    tmp.replace(ARQ)


async def renovar(ctx) -> dict:
    """Faz GET /api/me no contexto do navegador e salva os cookies renovados.

    O browser aplica os Set-Cookie do servidor no próprio contexto; depois é
    só ler de volta e persistir. Idempotente e barato (1 request).
    """
    try:
        resp = await ctx.request.get(URL_ME, timeout=20000)
        await ctx.request.get(URL_ME, timeout=20000) if resp.status != 200 else None
        cookies = await ctx.cookies(["https://arena.ai"])
        pares = {c["name"]: c["value"] for c in cookies if c["name"] in (_NOME0, _NOME1)}
        if resp.status == 200 and _NOME0 in pares:
            antes = _exp_do_access("")
            _salvar(pares[_NOME0], pares.get(_NOME1, ""))
            novo_exp = _exp_do_access(pares[_NOME0])
            renovou = (antes is None) or (novo_exp is not None and novo_exp > antes)
            return {"ok": True, "renovou": renovou, "exp_antes": antes, "exp_novo": novo_exp}
        return {"ok": False, "status": resp.status, "tinha_cookie": bool(pares)}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


async def renovar_e_injetar(perfil: str = "arena-teste") -> dict:
    """Renova a sessão usando o perfil persistente e devolve o estado.

    Se o cookie em data/ estiver mais novo que o do perfil, injeta antes.
    """
    from browser import MANAGER

    await MANAGER.start()
    try:
        ctx = await MANAGER.context_for(perfil)
        existentes = {c["name"]: c["value"] for c in await ctx.cookies(["https://arena.ai"])
                      if c["name"] in (_NOME0, _NOME1)}
        arq = _ler_arquivo()
        if _NOME0 in arq and arq.get(_NOME0) != existentes.get(_NOME0):
            exp_ms = int(time.time()) + 180 * 24 * 3600
            base = {"domain": ".arena.ai", "path": "/", "secure": True,
                    "httpOnly": True, "sameSite": "Lax", "expires": exp_ms}
            await ctx.clear_cookies()
            await ctx.add_cookies([
                {**base, "name": "arena-auth-prod-v1", "value": ""},
                {**base, "name": _NOME0, "value": arq[_NOME0]},
                {**base, "name": _NOME1, "value": arq.get(_NOME1, "")},
            ])
        res = await renovar(ctx)
        res["perfil"] = perfil
        return res
    finally:
        await MANAGER.stop()
