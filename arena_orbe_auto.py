"""Abre a conversa existente orbe auto. Nao cria outra. Nao imprime sessao."""
from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

NOME = "orbe auto"


def _cookies() -> list[dict]:
    c0 = os.environ.get("ARENA_COOKIE_0", "").strip()
    c1 = os.environ.get("ARENA_COOKIE_1", "").strip()
    if not c0:
        return []
    expira = int(time.time()) + 180 * 24 * 3600
    pares = [("arena-auth-prod-v1.0", c0)]
    if c1:
        pares.append(("arena-auth-prod-v1.1", c1))
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


def _limpo(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if any(s in texto.lower() for s in ("base64-", "eyj", "bearer ")):
        return ""
    return texto[:60]


def main() -> None:
    cookies = _cookies()
    if not cookies:
        print("sem_sessao")
        raise SystemExit(1)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto("https://arena.ai/agent", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3500)
        me = context.request.get("https://arena.ai/api/me", timeout=20000)
        corpo = me.text()
        logado = me.status == 200 and bool(re.search(r'"email":"[^"]', corpo))
        print("login", me.status, "logado", logado)
        if not logado:
            titulo = _limpo(page.title())
            print("nao_logado", titulo)
            browser.close()
            raise SystemExit(2)
        itens = page.evaluate(
            """() => {
              const out = [];
              for (const el of document.querySelectorAll('a, button, [role="link"], [role="button"]')) {
                const text = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
                if (!text || text.length > 80) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 8 || r.height < 8) continue;
                out.push({text: text.slice(0, 60), href: (el.getAttribute('href') || '').slice(0, 100)});
              }
              return out.slice(0, 80);
            }"""
        )
        alvos = [x for x in itens if NOME in x["text"].lower()]
        print("itens", len(itens), "alvos", len(alvos))
        vistos = []
        for item in itens:
            texto = _limpo(item.get("text") or "")
            if texto and texto not in vistos:
                vistos.append(texto)
        for texto in vistos[:25]:
            print("item", texto)
        if not alvos:
            print("conversa_nao_encontrada")
            browser.close()
            raise SystemExit(3)
        antes = page.url.split("?")[0].rstrip("/")
        page.get_by_text(re.compile(r"orbe auto", re.I)).first.click(timeout=8000)
        page.wait_for_timeout(2500)
        depois = page.url.split("?")[0].rstrip("/")
        print("url_antes", antes[-80:])
        print("url_depois", depois[-80:])
        if depois == antes or depois.endswith("/agent"):
            print("nao_entrou_na_conversa_nao_digitei")
            browser.close()
            raise SystemExit(4)
        caixa = page.locator('div[contenteditable="true"]').first
        caixa.click(timeout=5000)
        caixa.press_sequentially(".")
        enviado = False
        try:
            page.locator('button:has-text("Send message")').first.click(timeout=4000)
            enviado = True
        except Exception:
            page.keyboard.press("Enter")
            enviado = True
        page.wait_for_timeout(2000)
        print("enviei_ponto", enviado, "url", page.url.split("?")[0][-80:])
        browser.close()


if __name__ == "__main__":
    main()
