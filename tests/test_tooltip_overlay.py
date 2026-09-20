"""
v0.13 — tooltip/popover Radix sobre a textarea (caso REAL da Arena:
"Auto-routes you to the right modality" interceptava pointer events e o
click da textarea estourava timeout 5000ms).

A correção em camadas: Escape antes de digitar -> clique normal ->
clique force -> fill() (que foca via DOM e ignorar overlay).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from adapters import Registry, run_browser_step
from browser import MANAGER
from config import get_settings

ROOT_TESTS = Path(__file__).resolve().parent


@pytest.fixture
def fake_site():
    import http.server
    import threading

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT_TESTS), **kw)

        def log_message(self, *a, **kw):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/fake_tooltip.html"
    srv.shutdown()


def test_run_step_passa_com_tooltip_bloqueando_a_textarea(tmp_path, monkeypatch, fake_site):
    """Réplica do erro da Arena: div overlay cobre a textarea e o botão Enviar.
    Antes: TimeoutError no click. Agora: Escape + force + fill entregam o prompt."""
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path))
    (tmp_path / "faketip.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "faketip",
                "name": "Fake Tooltip",
                "kind": "browser",
                "url": fake_site,
                "new_chat_url": fake_site,
                "prompt_selector": "textarea#prompt",
                "submit": {"selector": "button#send", "key": "Enter"},
                "answer_selector": "div#answer",
                "settle_ms": 700,
                "max_wait_s": 20,
                "logged_in_selector": "",
                "logged_out_selector": "a[href*='nao-existe-nenhum']",
                # replica o yaml da Arena: pre_action deixa "popover" aberto
                "pre_actions": [{"click": "button#modes", "wait_ms": 300}],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    spec = Registry(Path(str(tmp_path))).get("faketip")

    async def run():
        await MANAGER.start()
        try:
            ctx = await MANAGER.context_for("t-tooltip")
            page = await ctx.new_page()
            try:
                return await run_browser_step(page, spec, "diga ola tooltip")
            finally:
                await page.close()
        finally:
            await MANAGER.stop()

    r = asyncio.run(run())
    assert r["ok"], f"step deveria passar com tooltip, veio: {r['error'][:200]}"
    assert "OK-FROM-FAKE-AI" in r["answer"], r["answer"][:120]
