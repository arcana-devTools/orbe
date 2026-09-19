"""
pre_actions: clicar em modo/modelo ANTES de digitar o prompt.
É o que permite usar a Arena em "Agent Mode" (ou qualquer site com seletor).
"""
from __future__ import annotations

import asyncio
import http.server
import threading
from pathlib import Path

import yaml

from adapters import Registry
from browser import BrowserManager
from config import get_settings

ROOT_TESTS = Path(__file__).resolve().parent


def _serve() -> tuple[http.server.ThreadingHTTPServer, str]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT_TESTS), **kw)

        def log_message(self, *a, **kw):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _yaml_mode(base: str) -> dict:
    return {
        "id": "fakemode",
        "name": "Fake com modos",
        "url": f"{base}/fake_mode.html",
        "new_chat_url": f"{base}/fake_mode.html",
        "prompt_selector": "textarea#prompt",
        "submit": {"key": "Enter", "selector": "button#send"},
        "answer_selector": "div#answer",
        "settle_ms": 600,
        "max_wait_s": 15,
        "logged_in_selector": "textarea#prompt",
        "logged_out_selector": "a[href*='nao-existe']",
    }


def test_pre_actions_escolhe_o_modo_antes_do_prompt(tmp_path, monkeypatch):
    srv, base = _serve()
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path))

    spec = _yaml_mode(base)
    spec["pre_actions"] = [
        # seletor inexistente + optional: pula sem falhar
        {"click": "button#nao-existe", "wait_ms": 200, "optional": True},
        # o clique de verdade: troca para o modo agent
        {"click": "button#mode-agent", "wait_ms": 300, "optional": True},
    ]
    (tmp_path / "fakemode.yaml").write_text(
        yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    from adapters import run_browser_step

    async def main():
        reg = Registry(get_settings().platforms_path())
        s = reg.get("fakemode")
        assert s is not None and len(s.pre_actions) == 2, "YAML deveria carregar pre_actions"
        bm = BrowserManager(get_settings())
        await bm.start()
        assert bm.enabled, bm.disabled_reason
        try:
            ctx = await bm.context_for("t-modo")
            page = await ctx.new_page()
            try:
                return await run_browser_step(page, s, "tarefa em modo agent")
            finally:
                await page.close()
        finally:
            await bm.stop()
            srv.shutdown()

    data = asyncio.run(main())
    assert data["ok"] is True, data
    assert "RESPONDI-NO-MODO-agent" in data["answer"], data["answer"]


def test_pre_action_obrigatorio_que_para_a_tarefa(tmp_path, monkeypatch):
    srv, base = _serve()
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path))

    spec = _yaml_mode(base)
    spec["pre_actions"] = [{"click": "button#nao-existe", "optional": False}]
    (tmp_path / "fakemode.yaml").write_text(
        yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    from adapters import run_browser_step

    async def main():
        reg = Registry(get_settings().platforms_path())
        bm = BrowserManager(get_settings())
        await bm.start()
        try:
            ctx = await bm.context_for("t-modo-req")
            page = await ctx.new_page()
            try:
                return await run_browser_step(page, reg.get("fakemode"), "não deve rodar")
            finally:
                await page.close()
        finally:
            await bm.stop()
            srv.shutdown()

    data = asyncio.run(main())
    assert data["ok"] is False
    assert "pre_action 1" in data["error"], data["error"]
