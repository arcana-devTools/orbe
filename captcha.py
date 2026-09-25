"""Detector de captcha + MURO HUMANO com POP-UP DO WIDGET (dono, 25/09/2026).

O Orbe NUNCA clica nem resolve captcha sozinho: anti-bot analisa COMO o clique
foi feito — clique de robô reprova, gera loop de desafio e é caminho pro ban.
Mas o DONO pediu conforto: em vez da tela inteira, o painel mostra SÓ O WIDGET
recortado em pop-up; o toque dele é repetido no ponto exato com movimento
humanizado do mouse real; o captcha some; a tarefa RETOMA sozinha.

Fluxo: detecta → avisa (Telegram + pop-up no painel) → segura a tarefa
→ dono toca no pop-up (pode ser do celular) → clique humanizado → some → retoma.
"""
from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, Optional

from events import BUS

SELETORES = [
    "iframe[src*='recaptcha']",
    "iframe[title*='recaptcha' i]",
    "iframe[src*='hcaptcha']",
    "iframe[title*='hcaptcha' i]",
    "iframe[src*='challenges.cloudflare']",
    "iframe[title*='challenge' i]",
    ".cf-turnstile",
    "#cf-chl-widget",
    "[class*='captcha' i]",
    # captcha INFRA do eproc (TJ/TRF brasileiros): div/campo/img por ID
    "[id*='captcha' i]",
    "img[src*='captcha' i]",
]
_TITULOS_CF = ("just a moment", "attention required", "checking your browser")


async def _padrao_tj(page) -> bool:
    """Verificação de segurança TJ/eproc: img-dataURI + input#ans + botão #jar."""
    try:
        if await page.locator("input#ans").count() and await page.locator("#jar").count():
            txt = ((await page.evaluate("() => (document.body.innerText||'').toLowerCase()")) or "")
            return "digite o c" in txt or "verificação de segurança" in txt
    except Exception:
        pass
    return False

# ---- estado compartilhado com o painel (pop-up) -------------------------
ESTADO: dict[str, Any] = {
    "ativo": False,
    "plataforma": "",
    "desc": "",
    "imagem": "",          # PNG base64 (data URI pronta)
    "task_id": "",
    "abortar": False,
    "atualizado_em": 0.0,
}
_PAGE = None
_BBOX: Optional[dict] = None
_LOCK = asyncio.Lock()


async def ha_captcha(page) -> str:
    """Descrição do captcha visível, ou '' se não houver."""
    try:
        titulo = (await page.title() or "").strip().lower()
        for frag in _TITULOS_CF:
            if frag in titulo:
                return f"interstitial Cloudflare (“{titulo[:48]}”)"
    except Exception:
        pass
    if await _padrao_tj(page):
        return "verificação de segurança TJ/eproc (#ans + #jar)"
    for sel in SELETORES:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 5)):
                if await loc.nth(i).is_visible():
                    return sel
        except Exception:
            continue
    return ""


async def _maior_bbox(page) -> Optional[dict]:
    """Maior widget de captcha visível (o challenge abre iframe maior que o box)."""
    if await _padrao_tj(page):
        try:
            melhor = None
            loc = page.locator("img")
            n = await loc.count()
            for i in range(min(n, 10)):
                if await loc.nth(i).is_visible():
                    bb = await loc.nth(i).bounding_box()
                    if bb and 150 <= bb["width"] <= 700 and bb["height"] >= 40:
                        area = bb["width"] * bb["height"]
                        if not melhor or area > melhor[0]:
                            melhor = (area, bb)
            if melhor:
                return melhor[1]
        except Exception:
            pass
    melhor = None
    for sel in SELETORES:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 5)):
                if await loc.nth(i).is_visible():
                    bb = await loc.nth(i).bounding_box()
                    if bb and bb["width"] > 20 and bb["height"] > 20:
                        area = bb["width"] * bb["height"]
                        if not melhor or area > melhor[0]:
                            melhor = (area, bb)
        except Exception:
            continue
    return melhor[1] if melhor else None


def _clip_de(bb: dict, pad: int = 6) -> dict:
    return {
        "x": max(0, bb["x"] - pad),
        "y": max(0, bb["y"] - pad),
        "width": bb["width"] + pad * 2,
        "height": bb["height"] + pad * 2,
    }


async def _crop_b64(page, bb: dict) -> str:
    png = await page.screenshot(clip=_clip_de(bb))
    return "data:image/png;base64," + base64.b64encode(png).decode()


async def _clique_humano(page, bb: dict, nx: float, ny: float) -> None:
    """Toque do dono → mouse real no ponto, com trajetória humanizada."""
    x = bb["x"] + max(0.0, min(1.0, nx)) * bb["width"]
    y = bb["y"] + max(0.0, min(1.0, ny)) * bb["height"]
    await page.mouse.move(x - 14, y - 9, steps=6)
    await page.mouse.move(x + 3, y + 2, steps=9)
    await page.mouse.move(x, y, steps=4)
    await page.wait_for_timeout(60 + int(time.time() * 100) % 70)
    await page.mouse.click(x, y)


async def clique_remoto(nx: float, ny: float) -> dict:
    """Chamado pelo painel quando o dono toca no pop-up."""
    if not _PAGE or not _BBOX:
        return {"ok": False, "erro": "nenhum captcha em pausa"}
    try:
        await _clique_humano(_PAGE, _BBOX, nx, ny)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def pedir_abort() -> None:
    ESTADO["abortar"] = True


def texto_do_dono(texto: str) -> dict:
    """Dono ditou o texto do captcha (ex.: letras da imagem do eproc)."""
    global _TEXTO
    _TEXTO = (texto or "").strip()
    return {"ok": True, "texto": bool(_TEXTO)}


async def portao_humano(
    page,
    plataforma: str,
    timeout_s: int = 900,
    task_id: str = "",
    campo: str = "",
    botao: str = "",
) -> dict:
    """Se houver captcha: avisa, publica o pop-up e espera o dono resolver.

    {"captcha": False} = livre. {"captcha": True, "resolvido": bool} caso contrário;
    a tarefa fica em pausa (até timeout_s) em vez de falhar bobamente.
    """
    global _PAGE, _BBOX, _CAMPO, _BOTAO, _TEXTO
    achado = await ha_captcha(page)
    if not achado:
        return {"captcha": False}

    _PAGE = page
    _BBOX = None
    _CAMPO, _BOTAO = campo, botao
    _TEXTO = ""
    async with _LOCK:
        ESTADO.update(ativo=True, plataforma=plataforma, desc=achado,
                      imagem="", task_id=task_id, abortar=False,
                      tem_campo=bool(campo),
                      atualizado_em=time.time())
    aviso = (
        f"🧩 Captcha em {plataforma} — tarefa PAUSADA ({achado}).\n"
        "Abra o painel: o pop-up mostra SÓ o captcha — toque nele pra resolver."
    )
    await BUS.warn(aviso, "captcha")
    try:
        from autopilot import AUTOPILOT

        await AUTOPILOT.send_telegram(aviso)
    except Exception:
        pass

    inicio = time.time()
    resolvido = False
    try:
        while time.time() - inicio < timeout_s:
            if ESTADO.get("abortar"):
                break
            # dono ditou o texto → preenche o campo e submete (conteúdo é
            # 100% humano; o Orbe só digita sob ditado — igual 2FA)
            if _TEXTO and _CAMPO:
                try:
                    alvo = page.locator(_CAMPO).first
                    await alvo.click(timeout=4000)
                    await alvo.fill(_TEXTO)
                    if _BOTAO:
                        await page.locator(_BOTAO).first.click(timeout=4000)
                    _TEXTO = ""
                    await page.wait_for_timeout(2500)
                except Exception:
                    _TEXTO = ""
            bb = await _maior_bbox(page)
            _BBOX = bb
            if bb is None:
                resolvido = True
                break
            try:
                img = await _crop_b64(page, bb)
                async with _LOCK:
                    ESTADO.update(imagem=img, atualizado_em=time.time())
            except Exception:
                pass
            await asyncio.sleep(2.5)
    finally:
        _BBOX = None
        async with _LOCK:
            ESTADO.update(ativo=False, imagem="", atualizado_em=time.time())
        if resolvido:
            await BUS.ok(f"🧩 captcha resolvido pelo dono — retomando {plataforma}", "captcha")
        else:
            await BUS.error(f"🧩 captcha não resolvido — {plataforma} falhou", "captcha")
    return {"captcha": True, "resolvido": resolvido,
            "esperou_s": round(time.time() - inicio)}
