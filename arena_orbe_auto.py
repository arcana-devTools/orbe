"""Abre a conversa existente. Nao cria outra. Nao imprime sessao."""
from __future__ import annotations

import os
import re
import time

from playwright.sync_api import sync_playwright


def _cookies() -> list[dict]:
    pares = []
    c0 = os.environ.get("ARENA_COOKIE_0", "").strip()
    c1 = os.environ.get("ARENA_COOKIE_1", "").strip()
    if c0:
        pares.append(("arena-auth-prod-v1.0", c0))
    if c1:
        pares.append(("arena-auth-prod-v1.1", c1))
    expira = int(time.time()) + 180 * 24 * 3600
    return [{
        "name": nome,
        "value": valor,
        "domain": ".arena.ai",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expires": expira,
    } for nome, valor in pares]


def _texto() -> str:
    texto = os.environ.get("ARENA_TEXTO", "").strip() or "."
    if "\n" in texto or len(texto) > 180:
        raise ValueError("texto_recusado")
    return texto


def main() -> None:
    cookies = _cookies()
    if not cookies:
        print("sem_sessao")
        raise SystemExit(1)
    destino = os.environ.get("ARENA_THREAD_URL", "").strip()
    if not destino.startswith("https://arena.ai/agent/"):
        print("sem_conversa")
        raise SystemExit(1)
    try:
        texto = _texto()
    except ValueError:
        print("texto_recusado")
        raise SystemExit(5)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto(destino, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3500)
        me = context.request.get("https://arena.ai/api/me", timeout=20000)
        corpo = me.text()
        logado = me.status == 200 and bool(re.search(r'"email":"[^"]', corpo))
        print("login", me.status, "logado", logado)
        if not logado:
            print("nao_logado", (page.title() or "")[:80])
            browser.close()
            raise SystemExit(2)
        final = page.url.split("?")[0].rstrip("/")
        esperado = destino.split("?")[0].rstrip("/")
        print("url_ok", final == esperado)
        print("titulo", (page.title() or "")[:80])
        if final != esperado:
            print("nao_entrou_na_conversa_nao_digitei")
            browser.close()
            raise SystemExit(4)
        if os.environ.get("ARENA_ENVIAR") != "1":
            print("abriu_sem_digitar")
            browser.close()
            return
        caixa = page.locator('div[contenteditable="true"]').first
        caixa.click(timeout=8000)
        caixa.press_sequentially(texto)
        try:
            page.locator('button:has-text("Send message")').first.click(timeout=4000)
        except Exception:
            page.keyboard.press("Enter")
        page.wait_for_timeout(2000)
        print("enviei_ok", page.url.split("?")[0].rstrip("/") == esperado, "chars", len(texto))
        browser.close()


if __name__ == "__main__":
    main()
