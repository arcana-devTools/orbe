"""Kiwify — API pública (vendas reais, saldo, produtos, afiliados, webhook).

O que a API faz e o que NÃO faz:
- FAZ: listar vendas, saldos, saques, produtos, afiliados e criar webhooks.
- NÃO FAZ: criar produto. Produto se cria no painel (navegador) — a colônia
  publica por lá quando a sessão estiver salva, do mesmo jeito que no UICLAP.

Credenciais — painel Kiwify → Apps → API → Criar API Key (marque TODOS os endpoints):
  ORBE_KIWIFY_ACCOUNT_ID    = "ID da conta"      (cabeçalho x-kiwify-account-id)
  ORBE_KIWIFY_CLIENT_ID     = "ID do cliente"
  ORBE_KIWIFY_CLIENT_SECRET = "Segredo da conta"
Fallback: cofre (data/secrets/vault.json, conta "kiwify" → extra).

Autenticação: POST https://public-api.kiwify.com/v1/oauth/token
  (application/x-www-form-urlencoded: client_id + client_secret)
  → access_token válido por 24 h (a gente guarda em data/kiwify_token.json).
Valores de dinheiro vêm em CENTAVOS — este módulo devolve em reais.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from secrets_vault import VAULT

BASE = "https://public-api.kiwify.com/v1"
TOKEN_CACHE = Path("data/kiwify_token.json")
TIMEOUT = 25.0


class KiwifyErro(Exception):
    pass


# ------------------------------------------------------------------ credenciais
def cred() -> dict[str, str] | None:
    """Credenciais da API: env primeiro, cofre depois."""
    d = {
        "account_id": os.environ.get("ORBE_KIWIFY_ACCOUNT_ID", "").strip(),
        "client_id": os.environ.get("ORBE_KIWIFY_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("ORBE_KIWIFY_CLIENT_SECRET", "").strip(),
    }
    if not all(d.values()):
        v = VAULT.get("kiwify") or {}
        ex = v.get("extra") or {}
        d = {
            "account_id": d["account_id"] or str(ex.get("account_id", "")),
            "client_id": d["client_id"] or str(ex.get("client_id", "")),
            "client_secret": d["client_secret"] or str(ex.get("client_secret", "")),
        }
    if not all(d.values()):
        return None
    return d


def estado() -> dict[str, Any]:
    """Pra saúde da colônia: dá pra falar com a Kiwify ou falta o quê?"""
    c = cred()
    if not c:
        return {"ok": False, "motivo": "sem credenciais (Apps → API → Criar API Key)"}
    try:
        t = token()
    except Exception as exc:
        return {"ok": False, "motivo": str(exc)[:120]}
    return {"ok": True, "motivo": "token OAuth válido", "token": t[:12] + "..."}


# --------------------------------------------------------------------- token
def token(forcar: bool = False) -> str:
    c = cred()
    if not c:
        raise KiwifyErro("sem credenciais da Kiwify")
    try:
        cache = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    if not forcar and cache.get("token") and float(cache.get("exp", 0)) > time.time() + 60:
        return str(cache["token"])
    r = httpx.post(
        f"{BASE}/oauth/token",
        data={"client_id": c["client_id"], "client_secret": c["client_secret"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise KiwifyErro(f"oauth HTTP {r.status_code}: {r.text[:160]}")
    d = r.json()
    if not d.get("access_token"):
        raise KiwifyErro(f"oauth sem token: {str(d)[:160]}")
    exp = time.time() + float(d.get("expires_in", 86400) or 86400)
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(json.dumps({"token": d["access_token"], "exp": exp}), encoding="utf-8")
    return str(d["access_token"])


def _cabecalho() -> dict[str, str]:
    c = cred()
    if not c:
        raise KiwifyErro("sem credenciais da Kiwify")
    return {
        "Authorization": f"Bearer {token()}",
        "x-kiwify-account-id": c["account_id"],
        "Accept": "application/json",
    }


def api(caminho: str, **params: Any) -> dict[str, Any]:
    """GET na API pública. Reautentica uma vez se o token tiver vencido."""
    p = {k: v for k, v in params.items() if v is not None}
    r = httpx.get(f"{BASE}/{caminho.lstrip('/')}", headers=_cabecalho(), params=p, timeout=TIMEOUT)
    if r.status_code in (401, 403):          # token vencido: gera outro e tenta de novo
        token(forcar=True)
        r = httpx.get(f"{BASE}/{caminho.lstrip('/')}", headers=_cabecalho(), params=p, timeout=TIMEOUT)
    if r.status_code != 200:
        raise KiwifyErro(f"{caminho} HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except Exception:
        raise KiwifyErro(f"{caminho} respondeu algo que não é JSON: {r.text[:120]}")


def _linhas(d: dict) -> list[dict]:
    return list((d or {}).get("data") or [])


# ------------------------------------------------------------------ leituras
def produtos() -> list[dict]:
    return _linhas(api("products", page_size=100, page_number=1))


def vendas(dias: int = 7, status: str = "paid", detalhe: bool = True) -> list[dict]:
    fim = datetime.now(timezone.utc)
    ini = fim - timedelta(days=max(1, min(int(dias), 90)))
    return _linhas(api(
        "sales",
        start_date=ini.strftime("%Y-%m-%d"),
        end_date=fim.strftime("%Y-%m-%d"),
        status=status or None,
        view_full_sale_details="true" if detalhe else None,
        page_size=100,
        page_number=1,
    ))


def _reais(v: Any) -> float:
    try:
        return round(float(v) / 100.0, 2)
    except Exception:
        return 0.0


def resumo(dias: int = 7) -> dict[str, Any]:
    """Vendas pagas dos últimos N dias, em REAIS, prontas pro resumo do dono."""
    try:
        vs = vendas(dias=dias, status="paid")
    except KiwifyErro as exc:
        return {"ok": False, "motivo": str(exc)[:160], "vendas": 0, "liquido": 0.0}
    bruto = liq = 0.0
    por_produto: dict[str, float] = {}
    for v in vs:
        pag = v.get("payment") or {}
        b = _reais(pag.get("charge_amount") or v.get("net_amount") or 0)
        l = _reais(pag.get("net_amount") or v.get("net_amount") or 0)
        bruto += b
        liq += l
        nome = str((v.get("product") or {}).get("name") or "produto")
        por_produto[nome] = round(por_produto.get(nome, 0.0) + l, 2)
    return {
        "ok": True,
        "dias": dias,
        "vendas": len(vs),
        "bruto": round(bruto, 2),
        "liquido": round(liq, 2),
        "por_produto": por_produto,
    }


async def conector(dias: int = 30) -> list[dict[str, Any]]:
    """Conector do livro-caixa (vendas.py): puxa as vendas PAGAS da Kiwify.

    Sem credenciais não faz nada (e não derruba a colônia) — é só silêncio.
    Cada venda entra com a prova = id do pedido, então nunca duplica.
    """
    if not cred():
        return []
    import asyncio

    vs = await asyncio.to_thread(vendas, dias, "paid", True)
    out: list[dict[str, Any]] = []
    for v in vs:
        pag = v.get("payment") or {}
        prod = v.get("product") or {}
        liquido = _reais(pag.get("net_amount") or v.get("net_amount") or 0)
        if liquido <= 0:
            continue
        out.append({
            "loja": "kiwify",
            "valor": liquido,
            "moeda": str(v.get("currency") or "BRL").upper(),
            "prova": str(v.get("id") or v.get("reference") or ""),
            "produto_id": str(prod.get("id") or ""),
            "titulo": str(prod.get("name") or ""),
        })
    return out


def saldo() -> dict[str, Any]:
    try:
        d = api("balance")
    except KiwifyErro as exc:
        return {"ok": False, "motivo": str(exc)[:160]}
    return {"ok": True, "dados": d.get("data", d)}


def afiliados() -> list[dict]:
    return _linhas(api("affiliates", page_size=100, page_number=1))


def webhooks() -> list[dict]:
    return _linhas(api("webhooks"))


def webhook_criar(url: str, nome: str = "Orbe", gatilhos: list[str] | None = None,
                  token: str = "") -> dict[str, Any]:
    """Cria um webhook pra Kiwify avisar a venda na hora (o Orbe recebe e confere)."""
    import secrets

    c = cred()
    if not c:
        raise KiwifyErro("sem credenciais da Kiwify")
    token = token or secrets.token_urlsafe(18)
    corpo = {"name": nome, "url": url, "products": "all", "token": token,
             "triggers": gatilhos or ["compra_aprovada", "compra_reembolsada", "chargeback"]}
    r = httpx.post(f"{BASE}/webhooks", headers={**_cabecalho(), "Content-Type": "application/json"},
                   json=corpo, timeout=TIMEOUT)
    if r.status_code in (401, 403):
        token(forcar=True)
        r = httpx.post(f"{BASE}/webhooks", headers={**_cabecalho(), "Content-Type": "application/json"},
                       json=corpo, timeout=TIMEOUT)
    if r.status_code not in (200, 201):
        raise KiwifyErro(f"webhook HTTP {r.status_code}: {r.text[:200]}")
    try:
        saida = r.json()
    except Exception:
        saida = {"ok": True, "texto": r.text[:160]}
    if isinstance(saida, dict):
        saida.setdefault("token", token)
    return saida


def venda(order_id: str) -> dict[str, Any]:
    """Uma venda pelo id (a fonte da verdade do valor — o corpo do webhook não vale)."""
    d = api(f"sales/{order_id}", view_full_sale_details="true")
    if isinstance(d.get("data"), dict):
        return d["data"]
    return d


def lancar_webhook(d: dict[str, Any]) -> dict[str, Any]:
    """Webhook da Kiwify → venda REAL no livro-caixa.

    O valor nunca vem do corpo do aviso: a gente busca a venda na API pelo id e
    lança o líquido de lá. Reembolso/chargeback/recusa não entra como venda.
    """
    def achar(*chaves: str) -> Any:
        for fonte in (d, d.get("data") if isinstance(d.get("data"), dict) else {}):
            for c in chaves:
                v = fonte.get(c)
                if v:
                    return v
        return ""

    oid = str(achar("order_id", "id", "sale_id", "orderId") or "")[:64]
    status = str(achar("order_status", "status", "webhook_type", "event") or "").lower()
    if not oid:
        return {"ok": False, "motivo": "aviso sem order_id"}
    if any(x in status for x in ("reembols", "refund", "chargeback", "recusad", "cancel", "expirad")):
        return {"ok": False, "motivo": f"ignorado ({status})", "order_id": oid}
    titulo = str(achar("product_name", "product_title") or "")
    try:
        v = venda(oid)
        pag = v.get("payment") or {}
        liquido = _reais(pag.get("net_amount") or v.get("net_amount") or 0)
        titulo = str((v.get("product") or {}).get("name") or titulo)
        prod_id = str((v.get("product") or {}).get("id") or "")
        moeda = str(v.get("currency") or "BRL").upper()
        aprovado = str(v.get("status") or "").lower()
    except Exception as exc:
        return {"ok": False, "motivo": f"não consegui conferir na API: {str(exc)[:80]}", "order_id": oid}
    if aprovado and aprovado not in ("paid", "approved", "aprovada", "aprovado"):
        return {"ok": False, "motivo": f"venda {oid} ainda não está paga ({aprovado})"}
    if liquido <= 0:
        return {"ok": False, "motivo": "valor líquido zero", "order_id": oid}
    import vendas

    v2 = vendas.registrar("kiwify", liquido, moeda, prova=oid, produto_id=prod_id, titulo=titulo)
    return {"ok": True, "nova": bool(v2), "valor": liquido, "moeda": moeda, "produto": titulo, "order_id": oid}


# ------------------------------------------------------------------ CLI
def main() -> None:
    import sys

    cmd = (sys.argv[1] if len(sys.argv) > 1 else "estado").lower()
    if cmd == "estado":
        print(json.dumps(estado(), ensure_ascii=False))
    elif cmd == "produtos":
        for p in produtos():
            print("-", p.get("id"), "|", p.get("name"), "|", p.get("status"))
        print(f"({len(produtos())} produto(s))")
    elif cmd == "vendas":
        r = resumo(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif cmd == "saldo":
        print(json.dumps(saldo(), ensure_ascii=False)[:600])
    elif cmd == "webhooks":
        print(json.dumps(webhooks(), ensure_ascii=False)[:600])
    elif cmd == "webhook":
        print(json.dumps(webhook_criar(sys.argv[2]), ensure_ascii=False)[:400])
    elif cmd == "venda":
        print(json.dumps(venda(sys.argv[2]), ensure_ascii=False)[:800])
    else:
        print("comandos: estado | produtos | vendas [dias] | saldo | webhooks | webhook <url>")


if __name__ == "__main__":
    main()
