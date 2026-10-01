"""Consultas que a colônia faz nos sites que o dono liberou.

VirusTotal, Shodan e IntelX. Serve para conferir um link, um arquivo ou um
endereço que ela já tem. Não caça máquina aberta. Não devolve senha.
"""
from __future__ import annotations

import base64
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

SITES = {
    "virustotal": "https://www.virustotal.com/gui/home/search",
    "shodan": "https://www.shodan.io/",
    "intelx": "https://intelx.io/",
}
_ENV = {
    "virustotal": "ORBE_VT_KEY",
    "shodan": "ORBE_SHODAN_KEY",
    "intelx": "ORBE_INTELX_KEY",
}
_RECUSADO = re.compile(r"\b(port|vuln|os|net|product|country|city|org|asn|hostname)\s*:", re.I)
_SENHA = re.compile(r"\b(password|passwd|senha|credential|secret)\b", re.I)


def _chave(site: str) -> str:
    nome = _ENV.get(site, "")
    bruto = os.environ.get(nome, "").strip() if nome else ""
    if bruto:
        return bruto
    try:
        from secrets_vault import VAULT

        d = VAULT.get(site) or {}
        extra = d.get("extra") or {}
        return str(extra.get("key") or extra.get("api_key") or d.get("password") or "").strip()
    except Exception:
        return ""


def estado() -> dict[str, Any]:
    return {s: {"chave": bool(_chave(s)), "url": u} for s, u in SITES.items()}


def pagina(site: str) -> str:
    if site not in SITES:
        raise ValueError("site")
    return SITES[site]


def consultar(site: str, alvo: str) -> dict[str, Any]:
    site = (site or "").strip().lower()
    alvo = (alvo or "").strip()
    if site not in SITES:
        raise ValueError("site")
    if not alvo or len(alvo) > 200 or any(c in alvo for c in "\n\r"):
        raise ValueError("alvo")
    if _RECUSADO.search(alvo) or _SENHA.search(alvo):
        return {"ok": False, "motivo": "consulta recusada", "site": site}
    chave = _chave(site)
    if not chave:
        return {"ok": False, "motivo": "sem chave no cofre", "site": site, "url": SITES[site]}
    if site == "virustotal":
        return _vt(alvo, chave)
    if site == "shodan":
        return _shodan(alvo, chave)
    return _intelx(alvo, chave)


def _vt(alvo: str, chave: str) -> dict[str, Any]:
    ident = base64.urlsafe_b64encode(alvo.encode()).decode().strip("=")
    r = httpx.get(
        f"https://www.virustotal.com/api/v3/urls/{ident}",
        headers={"x-apikey": chave},
        timeout=30,
    )
    if r.status_code == 404:
        return {"ok": True, "site": "virustotal", "conhecido": False}
    if r.status_code >= 300:
        return {"ok": False, "site": "virustotal", "motivo": f"HTTP {r.status_code}"}
    stats = (((r.json().get("data") or {}).get("attributes") or {}).get("last_analysis_stats") or {})
    return {"ok": True, "site": "virustotal", "conhecido": True,
            "malicioso": int(stats.get("malicious") or 0),
            "suspeito": int(stats.get("suspicious") or 0)}


def _shodan(alvo: str, chave: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", alvo):
        return {"ok": False, "site": "shodan", "motivo": "endereço recusado"}
    ip = alvo
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", alvo):
        d = httpx.get("https://api.shodan.io/dns/resolve", params={"hostnames": alvo, "key": chave}, timeout=30)
        if d.status_code >= 300:
            return {"ok": False, "site": "shodan", "motivo": f"HTTP {d.status_code}"}
        ip = str((d.json() or {}).get(alvo) or "")
        if not ip:
            return {"ok": True, "site": "shodan", "conhecido": False, "endereco": alvo}
    r = httpx.get(f"https://api.shodan.io/shodan/host/{ip}", params={"key": chave}, timeout=30)
    if r.status_code == 404:
        return {"ok": True, "site": "shodan", "conhecido": False, "ip": ip}
    if r.status_code >= 300:
        return {"ok": False, "site": "shodan", "motivo": f"HTTP {r.status_code}"}
    j = r.json()
    portas = sorted({int(x.get("port")) for x in (j.get("data") or []) if x.get("port")})
    return {"ok": True, "site": "shodan", "conhecido": True, "ip": ip,
            "org": str(j.get("org") or "")[:80], "pais": j.get("country_code") or "",
            "portas": portas[:20]}


def _intelx(alvo: str, chave: str) -> dict[str, Any]:
    base = os.environ.get("ORBE_INTELX_URL", "https://free.intelx.io").rstrip("/")
    r = httpx.post(
        f"{base}/intelligent/search",
        headers={"x-key": chave, "Content-Type": "application/json"},
        json={"term": alvo, "maxresults": 5, "media": 0, "sort": 4, "terminate": []},
        timeout=30,
    )
    if r.status_code >= 300:
        return {"ok": False, "site": "intelx", "motivo": f"HTTP {r.status_code}"}
    ident = str((r.json() or {}).get("id") or "")
    if not ident:
        return {"ok": False, "site": "intelx", "motivo": "sem id"}
    g = httpx.get(
        f"{base}/intelligent/search/result",
        headers={"x-key": chave},
        params={"id": ident, "limit": 5},
        timeout=30,
    )
    if g.status_code >= 300:
        return {"ok": False, "site": "intelx", "motivo": f"HTTP {g.status_code}"}
    itens = []
    for it in (g.json().get("records") or [])[:5]:
        nome = str(it.get("name") or "")[:80]
        if _SENHA.search(nome):
            continue
        itens.append({"nome": nome, "bucket": str(it.get("bucket") or "")[:40]})
    return {"ok": True, "site": "intelx", "itens": len(itens), "amostra": itens}
