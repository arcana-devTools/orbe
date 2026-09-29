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


# ---- IP residencial: de datacenter o portal da Shopee pede captcha ------------
_PORTA = int(os.environ.get("ORBE_WARP_PORTA", "25345"))
_PROC: dict[str, Any] = {}
_BIN = Path(os.environ.get("ORBE_TMP", "/tmp")) / "wireproxy"


def _socks_vivo(px: str) -> bool:
    try:
        with httpx.Client(proxy=px, timeout=12) as c:
            return "warp=on" in c.get("https://www.cloudflare.com/cdn-cgi/trace").text
    except Exception:
        return False


def _warp_conf() -> str:
    """Perfil do WARP: variável ORBE_WARP_CONF (Render), cofre ou arquivo local."""
    env = os.environ.get("ORBE_WARP_CONF")
    if env:
        return env.strip()
    for arq in (Path("data/warp.conf"), Path("data/_uic/warp/wgcf-profile.conf")):
        try:
            return arq.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    try:
        d = VAULT.get("warp")
        if d:
            e = d.get("extra") if isinstance(d, dict) else d.extra
            if e.get("conf"):
                return e["conf"]
    except Exception:
        pass
    for arq in (Path("data/_uic/warp/wgcf-profile.conf"), Path("/tmp/wgcf-profile.conf")):
        try:
            return arq.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    return ""


def _wireproxy() -> Path | None:
    if _BIN.exists() and _BIN.stat().st_size > 1_000_000:
        return _BIN
    url = ("https://github.com/whyvl/wireproxy/releases/latest/download/"
           "wireproxy_linux_amd64.tar.gz")
    try:
        with httpx.Client(timeout=90, follow_redirects=True) as c:
            r = c.get(url)
        import io
        import tarfile

        with tarfile.open(fileobj=io.BytesIO(r.content)) as t:
            for m in t.getmembers():
                if m.name.endswith("wireproxy"):
                    _BIN.write_bytes(t.extractfile(m).read())
                    _BIN.chmod(0o755)
                    return _BIN
    except Exception:
        return None
    return None


def _socks() -> str | None:
    """Socks5 pronto: o ORBE_SOCKS do ambiente, ou um túnel WARP que a gente mesmo sobe."""
    px = os.environ.get("ORBE_SOCKS")
    if px and _socks_vivo(px):
        return px
    local = f"socks5://127.0.0.1:{_PORTA}"
    if _socks_vivo(local):
        return local
    p = _PROC.get("p")
    if p and p.poll() is None and _socks_vivo(local):
        return local
    conf, bin = _warp_conf(), _wireproxy()
    if not conf or not bin:
        return px or None
    ini = _BIN.parent / f"warp_{_PORTA}.ini"
    ini.write_text(conf + f"\n[Socks5]\nBindAddress = 127.0.0.1:{_PORTA}\n", encoding="utf-8")
    try:
        import subprocess

        _PROC["p"] = subprocess.Popen([str(bin), "-s", "-c", str(ini)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return px or None
    for _ in range(30):
        time.sleep(1)
        if _socks_vivo(local):
            return local
    return px or None


def _cliente() -> httpx.Client:
    """ORBE_SOCKS = proxy socks5 pronto; sem ele a gente sobe o WARP."""
    return httpx.Client(headers=_cabecalho(), timeout=40, proxy=_socks(),
                        follow_redirects=False)


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


def qr_base64(url: str) -> str:
    """PNG do QR code da URL, pronto para <img src="data:image/png;base64,...">."""
    import base64
    import io

    import segno

    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=6, border=2)
    return base64.b64encode(buf.getvalue()).decode()


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
