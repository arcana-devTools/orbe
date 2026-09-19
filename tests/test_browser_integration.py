"""
Teste de integração com Chromium REAL (headless): abre a "IA falsa", envia o
prompt, espera a resposta e confirma a extração. É o mesmo caminho de código
que o ChatGPT/Gemini/Claude percorrem em produção.
"""
from __future__ import annotations

import asyncio

import pytest

from adapters import Registry, check_login, run_browser_step
from browser import BrowserManager
from config import get_settings

pytest.importorskip("playwright")


def test_navegador_abre_envia_prompt_e_extrai_resposta(tmp_platform_yaml, fake_site):
    async def main():
        reg = Registry(get_settings().platforms_path())
        reg.reload()
        spec = reg.get("fakechat")
        assert spec is not None, "adapter fakechat não carregou"

        bm = BrowserManager(get_settings())
        await bm.start()
        assert bm.enabled, f"chromium não subiu: {bm.disabled_reason}"
        try:
            ctx = await bm.context_for("t-fakechat")
            page = await ctx.new_page()
            try:
                # login detectado antes de mandar prompt
                await page.goto(fake_site, wait_until="domcontentloaded")
                state = await check_login(page, spec)
                assert state == "ok", state

                data = await run_browser_step(page, spec, "qual é a resposta?", screenshot_path=None)
            finally:
                await page.close()
        finally:
            await bm.stop()

        return data

    data = asyncio.run(main())
    assert data["ok"] is True, data
    assert "OK-FROM-FAKE-AI" in data["answer"], data["answer"]
    assert "qual é a resposta?" in data["answer"]
    assert data["title"].startswith("Fake AI")


def test_adapter_sem_caixa_de_prompt_reporta_erro_claro(tmp_platform_yaml):
    """Se o site mudar de layout, o Orbe precisa dizer isso em vez de travar."""
    async def main():
        reg = Registry(get_settings().platforms_path())
        reg.reload()
        spec = reg.get("fakechat")
        spec.prompt_selector = "textarea#nao-existe-mesmo"
        # força fallback genérico a falhar também, apontando para página sem input
        spec.url = "about:blank"
        spec.new_chat_url = "about:blank"
        spec.logged_in_selector = ""
        spec.logged_out_selector = ""

        bm = BrowserManager(get_settings())
        await bm.start()
        try:
            ctx = await bm.context_for("t-fakechat-2")
            page = await ctx.new_page()
            try:
                data = await run_browser_step(page, spec, "oi")
            finally:
                await page.close()
        finally:
            await bm.stop()
        return data

    data = asyncio.run(main())
    assert data["ok"] is False
    assert "caixa de prompt" in data["error"], data["error"]
