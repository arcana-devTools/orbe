"""CALIBRAR: inventário do que é clicável/digitável na tela (ajusta seletores sem F12)."""
from __future__ import annotations

import asyncio
import http.server
import threading
from pathlib import Path

import yaml

from adapters import Registry
from browser import MANAGER
from config import get_settings
from engine import get_engine
from models import Account
from store import STORE

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


def test_calibragem_lista_elementos_visiveis(tmp_path, monkeypatch):
    srv, base = _serve()
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path))
    (tmp_path / "fakemode.yaml").write_text(
        yaml.safe_dump({
            "id": "fakemode",
            "url": f"{base}/fake_mode.html",
            "new_chat_url": f"{base}/fake_mode.html",
            "prompt_selector": "textarea#prompt",
            "answer_selector": "div#answer",
        }, allow_unicode=True),
        encoding="utf-8",
    )

    import engine as engine_mod
    reg = Registry(get_settings().platforms_path())
    eng = engine_mod.Engine(reg, __import__("orchestrator").Orchestrator(reg))

    acc = Account(platform="fakemode", label="cal", profile="t-cal")
    STORE.add_account(acc)

    async def main():
        await MANAGER.start()
        assert MANAGER.enabled, MANAGER.disabled_reason
        try:
            return await eng.calibrate_account(acc.id)
        finally:
            await MANAGER.stop()
            STORE.delete_account(acc.id)
            srv.shutdown()

    r = asyncio.run(main())
    assert r["ok"] is True, r
    texts = " | ".join(e["text"] for e in r["elements"])
    assert "Chat" in texts and "Agent" in texts, texts          # botões de modo
    assert any(e["tag"] == "textarea" for e in r["elements"])   # caixa de prompt
    # elemento invisível/pequeno não aparece
    assert all(e["text"] for e in r["elements"])
