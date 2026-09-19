"""Configuração de teste: isola dados em /tmp e garante import do app."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

TMP = Path(tempfile.mkdtemp(prefix="orbe-test-"))
os.environ["ORBE_USER_DATA_DIR"] = str(TMP / "profiles")
os.environ["ORBE_DOWNLOADS_DIR"] = str(TMP / "downloads")
os.environ["ORBE_SHOTS_DIR"] = str(TMP / "shots")
os.environ["ORBE_ACCOUNTS_FILE"] = str(TMP / "accounts.json")
os.environ["ORBE_TASKS_FILE"] = str(TMP / "tasks.json")
os.environ["ORBE_HEADLESS"] = "1"
os.environ["ORBE_MAX_CONCURRENT_TASKS"] = "2"
os.environ["ORBE_LLM_API_KEY"] = ""

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def fake_site():
    """Servidor HTTP local servindo uma 'IA falsa' para testes de navegador."""
    import http.server
    import threading

    root = Path(__file__).resolve().parent

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a, **kw):  # silêncio
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/fake_chat.html"
    srv.shutdown()


@pytest.fixture
def tmp_platform_yaml(fake_site):
    """Cria um adapter YAML temporário apontando para a IA falsa."""
    from config import get_settings

    s = get_settings()
    path = Path(s.platforms_dir) / "test-fakechat.yaml"
    path.write_text(
        f"""
id: fakechat
name: Fake AI
kind: browser
category: teste
url: "{fake_site}"
new_chat_url: "{fake_site}"
prompt_selector: "textarea#prompt"
submit:
  key: Enter
  selector: "button#send"
answer_selector: "div#answer"
answer_index: -1
settle_ms: 800
max_wait_s: 20
logged_in_selector: "textarea#prompt"
logged_out_selector: "a[href*='nao-existe-login']"
""",
        encoding="utf-8",
    )
    yield path
    try:
        path.unlink()
    except OSError:
        pass
