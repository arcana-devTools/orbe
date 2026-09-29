"""Afiliados da Shopee — a colônia transforma URLs comuns em links de afiliado.

Regras (combinadas com o dono):
- Só usa o GERADOR OFICIAL do portal (POST /api/v3/link/conversion). Nada de
  montar link na mão, nada de compra, nada de mexer na conta.
- NUNCA resolve captcha: se o anti-robô pedir, o erro volta e um humano decide.
- Pouco acesso (só quando um livro está sendo montado) e sempre por IP residencial
  (WARP) quando houver ORBE_SOCKS — de datacenter o portal devolve 403/captcha.
- Sessão = cookie do dono, guardado no cofre (nunca no git).

Descoberto em 29/09/2026 lendo os bundles do portal:
  POST /api/v3/link/conversion  {"link": "...", "sub_ids": ["","","","",""],
                                 "sub_client_channel": "website"}
  → {"code":0,"data":{"link":"https://shp.ee/xxxx","long_link":"..."}}
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from secrets_vault import VAULT

BASE = "https://affiliate.shopee.com.br/api/v3"
CACHE = Path("data/afiliados_shopee.json")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")


class AfiliadoErro(Exception):
    pass


def _cabecalho() -> dict[str, str]:
    d = VAULT.get("shopee")
    if not d:
        raise AfiliadoErro("falta o cookie da Shopee no cofre (conta 'shopee')")
    e = d.get("extra") if isinstance(d, dict) else d.extra
    ck = e["cookie"]
    csrf = ""
    for p in ck.split(";"):
        if p.strip().startswith("csrftoken="):
            csrf = p.split("=", 1)[1].strip()
    return {"User-Agent": _UA, "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://affiliate.shopee.com.br/offer/custom_link",
            "Origin": "https://affiliate.shopee.com.br",
            "X-CSRFToken": csrf, "Cookie": ck}


def _cliente() -> httpx.Client:
    """ORBE_SOCKS = proxy socks5 (WARP). Sem ele, o portal costuma pedir captcha."""
    return httpx.Client(headers=_cabecalho(), timeout=40,
                        proxy=os.environ.get("ORBE_SOCKS") or None, follow_redirects=False)


def _cache() -> dict[str, Any]:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salva(c: dict[str, Any]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def estado() -> dict[str, Any]:
    """Mostra se a conta está aprovada como afiliada."""
    with _cliente() as c:
        r = c.get(f"{BASE}/user/status")
    try:
        j = r.json()
    except Exception:
        raise AfiliadoErro(f"resposta não-JSON ({r.status_code}): {r.text[:160]}")
    if j.get("error"):
        raise AfiliadoErro(f"portal pediu anti-robô (erro {j.get('error')})")
    return j.get("data") or j


def converter(url: str, sub_ids: list[str] | None = None) -> dict[str, str]:
    """Converte uma URL da Shopee em link de afiliado curto (shp.ee)."""
    url = url.strip()
    c = _cache()
    if url in c.get("links", {}):
        return c["links"][url]
    with _cliente() as cx:
        r = cx.post(f"{BASE}/link/conversion",
                    json={"link": url, "sub_ids": sub_ids or ["", "", "", "", ""],
                          "sub_client_channel": "website"})
    try:
        j = r.json()
    except Exception:
        raise AfiliadoErro(f"resposta não-JSON ({r.status_code}): {r.text[:160]}")
    if j.get("error"):
        raise AfiliadoErro(f"portal pediu anti-robô (erro {j.get('error')}) — tente de IP residencial")
    d = j.get("data") or {}
    if not d.get("link"):
        raise AfiliadoErro(f"portal não devolveu link: {str(j)[:200]}")
    c.setdefault("links", {})[url] = {"curto": d["link"], "longo": d.get("long_link", url),
                                      "em": time.time()}
    _salva(c)
    return c["links"][url]


def url_busca(palavras: str) -> str:
    """URL de busca na Shopee (aceita pelo conversor quando o produto específico falha)."""
    from urllib.parse import quote_plus

    return f"https://shopee.com.br/search?keyword={quote_plus(palavras)}"


def recursos(tema: str, n: int = 4) -> list[dict[str, str]]:
    """Devolve até n links de afiliado relacionados ao tema do livro.

    Tenta a lista oficial de ofertas; se o portal estiver pedindo anti-robô,
    cai para URLs de busca (que o conversor aceita) e nunca insiste.
    """
    saida: list[dict[str, str]] = []
    vistos: set[str] = set()
    with _cliente() as cx:
        try:
            r = cx.get(f"{BASE}/offer/product/list",
                       params={"keyword": tema, "list_type": 2, "page_limit": max(n * 3, 10),
                               "page_offset": 0, "client_type": 1, "sort_type": 1})
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            itens = ((j.get("data") or {}).get("list")) or []
        except Exception:
            itens = []
        for it in itens:
            link = it.get("product_link") or it.get("link")
            if not link or link in vistos:
                continue
            vistos.add(link)
            try:
                curto = converter(link)
            except AfiliadoErro:
                continue
            saida.append({"titulo": (it.get("product_name") or "").strip()[:70] or "Produto",
                          "curto": curto["curto"], "longo": curto["longo"]})
            if len(saida) >= n:
                break
    if len(saida) < n:                       # fallback honesto: link de busca do tema
        for palavras in (tema, " ".join(tema.split()[:2])):
            try:
                curto = converter(url_busca(palavras))
            except AfiliadoErro:
                continue
            saida.append({"titulo": f"Buscar {palavras} na Shopee", "curto": curto["curto"],
                          "longo": curto["longo"]})
            break
    return saida
