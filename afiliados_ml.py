"""Afiliados do Mercado Livre — a colônia usa a conta do DONO (logada por ele, 1x).

Regras (combinadas com o dono):
- Login/2FA/captcha: SÓ o dono, pelo /desktop. A colônia nunca digita senha nem resolve captcha.
- Uso SOMENTE LEITURA + gerador oficial de link do portal. Nada de compra, nada de alterar conta.
- Pouco acesso (≈1x/semana) pra não parecer robô.
- Sessão = cookies do ML, guardados no backup CRIPTOGRAFADO (branch orbe-estado), nunca no git.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

PERFIL = "mercadolivre-afiliados"
PORTAL = "https://afiliados.mercadolivre.com.br/"
SESSAO = Path("data/ml_sessao.json")
LINKS = Path("data/afiliados_ml.json")
_DOMINIOS = ("mercadolivre", "mercadolibre", "mercadopago", "mercadolibre.com")


async def _pagina():
    from browser import MANAGER

    ctx = await MANAGER.context_for(PERFIL)
    if SESSAO.exists():
        try:
            atuais = [c for c in await ctx.cookies() if any(d in c.get("domain", "") for d in _DOMINIOS)]
            if not atuais:          # Render reiniciou: perfil zerado → devolve a sessão do backup
                await ctx.add_cookies(json.loads(SESSAO.read_text(encoding="utf-8")))
        except Exception:
            pass
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return ctx, page


async def estado(page=None) -> dict[str, Any]:
    if page is None:
        _, page = await _pagina()
    js = """() => {
      const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      const t = s => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 90);
      return {
        links: [...document.querySelectorAll('a[href]')].filter(vis).slice(0, 80)
                 .map(a => [t(a.innerText), a.href]),
        botoes: [...document.querySelectorAll('button,[role=button]')].filter(vis).slice(0, 40)
                 .map(b => t(b.innerText || b.getAttribute('aria-label'))),
        campos: [...document.querySelectorAll('input,textarea')].filter(vis).slice(0, 20)
                 .map(i => [i.type, i.name, i.placeholder, i.getAttribute('aria-label')].join('|')),
        texto: t(document.body ? document.body.innerText : '').length ? document.body.innerText.slice(0, 2500) : ''
      };
    }"""
    try:
        d = await page.evaluate(js)
    except Exception as exc:
        d = {"erro": f"{type(exc).__name__}: {str(exc)[:120]}"}
    d.update(url=page.url, titulo=await page.title())
    d["logado"] = await logado(page)
    return d


async def logado(page) -> bool:
    url = page.url or ""
    if "login" in url or "/jms/" in url:
        return False
    try:
        return "afiliados" in url and await page.locator("text=/Gerador de link|Ferramentas|Meus links|Links/i") \
            .count() > 0
    except Exception:
        return False


async def _clicar_texto(page, texto: str) -> bool:
    alvo = page.get_by_text(texto, exact=False)
    if not await alvo.count():
        return False
    await alvo.first.click(timeout=8000, force=True)
    return True


async def preparar(acao: str) -> dict[str, Any]:
    """O toque do celular no VNC erra o botão. A colônia clica o que o dono pediu.
    Nunca digita senha. Cookies só se ele apertar o botão da barra."""
    _, page = await _pagina()
    try:
        await page.bring_to_front()
    except Exception:
        pass
    acao = (acao or "").strip().lower()
    if acao not in ("entrar", "cookies"):
        return {"ok": False, "motivo": "ação inválida"}
    if not page.url or page.url.startswith("about:"):
        await page.goto(PORTAL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)
    clicou = False
    try:
        if acao == "cookies":
            clicou = await _clicar_texto(page, "Aceitar cookies")
        else:
            clicou = await _clicar_texto(page, "Já tenho conta")
        await page.wait_for_timeout(1000)
    except Exception as exc:
        return {"ok": False, "clicou": False, "motivo": type(exc).__name__}
    if not clicou:
        return {"ok": False, "clicou": False, "motivo": "não achei o botão nessa tela", "url": page.url}
    tem_senha = False
    try:
        tem_senha = await page.locator("input[type='password']").count() > 0
    except Exception:
        pass
    return {"ok": True, "clicou": True, "url": page.url, "titulo": await page.title(),
            "tem_senha": tem_senha, "logado": await logado(page)}


async def abrir(url: str = PORTAL) -> dict[str, Any]:
    """Abre o portal no Chrome do desktop virtual (o dono loga por /desktop se preciso)."""
    _, page = await _pagina()
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2500)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return await estado(page)


async def salvar_sessao() -> dict[str, Any]:
    ctx, page = await _pagina()
    cookies = [c for c in await ctx.cookies() if any(d in c.get("domain", "") for d in _DOMINIOS)]
    if not cookies:
        return {"ok": False, "motivo": "nenhum cookie do Mercado Livre — o login foi concluído?"}
    SESSAO.parent.mkdir(parents=True, exist_ok=True)
    SESSAO.write_text(json.dumps(cookies), encoding="utf-8")
    __import__("state_backup").sujo()
    return {"ok": True, "cookies": len(cookies), "logado": await logado(page), "url": page.url}


async def tela() -> bytes:
    _, page = await _pagina()
    return await page.screenshot(type="png")


def links() -> list[dict]:
    try:
        return json.loads(LINKS.read_text(encoding="utf-8"))
    except Exception:
        return []


def status() -> dict[str, Any]:
    ls = links()
    return {"sessao_salva": SESSAO.exists(),
            "sessao_idade_h": round((time.time() - SESSAO.stat().st_mtime) / 3600, 1) if SESSAO.exists() else None,
            "links": len(ls)}
