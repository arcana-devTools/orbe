"""
Recursos pedidos pelo usuário neste round:
  1. colar a URL de qualquer IA e ela virar plataforma (POST /api/platforms/auto);
  2. CONFERIR TODAS: checagem em lote de sessão por conta.
"""
from __future__ import annotations

import asyncio
import http.server
import threading
from pathlib import Path

from adapters import Registry
from browser import MANAGER
from config import get_settings
from engine import get_engine
from models import Account
from orchestrator import Orchestrator
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


def _write_yaml(dir_: Path, spec: dict) -> None:
    import yaml

    (dir_ / f"{spec['id']}.yaml").write_text(
        yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_plataforma_criada_por_url_vira_yaml_e_entra_no_registry(tmp_path, monkeypatch):
    """ensure_adapter + reload: o caminho que o POST /api/platforms/auto executa."""
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path))
    reg = Registry(get_settings().platforms_path())
    orch = Orchestrator(reg)

    spec = orch.ensure_adapter("https://ia-desconhecida-exemplo.com/chat", name="IA Desconhecida")
    assert spec.url == "https://ia-desconhecida-exemplo.com/chat"
    assert spec.name == "IA Desconhecida"

    reg.reload()
    novo = reg.get(spec.id)
    assert novo is not None, "o YAML gravado deveria ser recarregado pelo registry"
    assert novo.url == spec.url
    # não duplica na segunda chamada
    again = orch.ensure_adapter("https://ia-desconhecida-exemplo.com/chat")
    assert again.id == spec.id
    assert len([p for p in tmp_path.glob("*.yaml")]) == 1


def test_check_all_reporta_ok_e_logged_out_por_conta(tmp_path, monkeypatch):
    srv, base = _serve()
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path))

    _write_yaml(tmp_path, {
        "id": "fakechat", "name": "Fake", "kind": "browser",
        "url": f"{base}/fake_chat.html", "new_chat_url": f"{base}/fake_chat.html",
        "prompt_selector": "textarea#prompt", "submit": {"key": "Enter", "selector": "button#send"},
        "answer_selector": "div#answer", "settle_ms": 800, "max_wait_s": 20,
        "logged_in_selector": "textarea#prompt", "logged_out_selector": "a[href*='nao-existe']",
    })
    _write_yaml(tmp_path, {
        "id": "fakelogin", "name": "Fake login", "kind": "browser",
        "url": f"{base}/fake_login.html", "new_chat_url": f"{base}/fake_login.html",
        "prompt_selector": "textarea#prompt", "submit": {"key": "Enter"},
        "answer_selector": "div#answer", "settle_ms": 800, "max_wait_s": 20,
        "logged_in_selector": "textarea#prompt", "logged_out_selector": "div#gate",
    })

    a_ok = Account(platform="fakechat", label="ativa", profile="t-chk-ok")
    a_out = Account(platform="fakelogin", label="travada", profile="t-chk-out")
    STORE.add_account(a_ok)
    STORE.add_account(a_out)

    # Registry guarda a pasta em que foi construído: cria um motor novo
    # apontando para a pasta monkeypatched (em produção o reload basta).
    import engine as engine_mod

    reg = Registry(get_settings().platforms_path())
    eng = engine_mod.Engine(reg, Orchestrator(reg))

    async def main():
        await MANAGER.start()
        assert MANAGER.enabled, MANAGER.disabled_reason
        try:
            results = await eng.check_all_accounts()
            # status persistido na loja É o que o painel exibe depois
            saved = {
                a_ok.id: STORE.accounts[a_ok.id].status.value,
                a_out.id: STORE.accounts[a_out.id].status.value,
            }
            return results, saved
        finally:
            await MANAGER.stop()
            STORE.delete_account(a_ok.id)
            STORE.delete_account(a_out.id)
            srv.shutdown()

    results, saved = asyncio.run(main())
    by_platform = {r["platform"]: r for r in results}

    assert by_platform["fakechat"]["status"] == "ok", by_platform["fakechat"]
    assert by_platform["fakechat"]["ok"] is True
    assert by_platform["fakelogin"]["status"] == "logged_out", by_platform["fakelogin"]
    assert by_platform["fakelogin"]["ok"] is False

    # o status persiste na loja (é o que o painel exibe depois)
    assert saved[a_ok.id] == "ok", saved
    assert saved[a_out.id] == "logged_out", saved
