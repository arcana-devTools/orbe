"""
Dois recursos que o usuário pediu explicitamente:
  1. rodar a MESMA tarefa em CONTAS DIFERENTES (perfis isolados, em paralelo);
  2. entrar no site e FAZER LOGIN com a conta configurada.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from adapters import AdapterSpec, Registry, run_browser_step
from browser import MANAGER, BrowserManager
from config import get_settings
from engine import get_engine
from models import Account, TaskState
from secrets_vault import Vault
from store import STORE


# ==================================================== 1. várias contas =====
def test_mesma_tarefa_roda_em_duas_contas_diferentes(tmp_platform_yaml):
    """all_accounts=True -> 1 rota por conta, cada uma no SEU perfil de Chrome."""
    async def main():
        a1 = Account(platform="fakechat", label="pessoal", profile="t-multi-1")
        a2 = Account(platform="fakechat", label="trabalho", profile="t-multi-2")
        STORE.add_account(a1)
        STORE.add_account(a2)
        await MANAGER.start()
        assert MANAGER.enabled, MANAGER.disabled_reason
        try:
            eng = get_engine()
            eng.registry.reload()

            # sanity: com all_accounts=False usa só a primeira conta
            t_single = await eng.submit("pergunta única", prefer=["fakechat"], accounts_limit=1)
            for _ in range(90):
                await asyncio.sleep(1)
                if t_single.state in (TaskState.DONE, TaskState.FAILED):
                    break
            single_routes = len(t_single.routing)

            t_all = await eng.submit("pergunta para as duas", prefer=["fakechat"], accounts_limit=0)

            # seleção explícita: só a conta "trabalho", ignorando o limite
            t_pick = await eng.submit("só uma conta escolhida", account_ids=[a2.id], accounts_limit=0)
            for _ in range(90):
                await asyncio.sleep(1)
                if t_all.state in (TaskState.DONE, TaskState.FAILED):
                    break
            for _ in range(90):
                await asyncio.sleep(1)
                if t_pick.state in (TaskState.DONE, TaskState.FAILED):
                    break
            return (single_routes, t_all.model_copy(deep=True),
                    t_pick.model_copy(deep=True), a1.id, a2.id)
        finally:
            await MANAGER.stop()
            STORE.delete_account(a1.id)
            STORE.delete_account(a2.id)

    single_routes, task, t_pick, id1, id2 = asyncio.run(main())
    ids = {id1, id2}

    assert single_routes == 1, "accounts_limit=1 deveria usar 1 conta só"
    assert task.state == TaskState.DONE, f"{task.state}: {task.error}"
    assert len(task.routing) == 2, task.routing
    used = {r.account_id for r in task.results}
    assert used == ids, f"deveria usar as duas contas, usou {used}"
    assert len({r.account_id for r in task.results}) == 2
    assert all(r.ok for r in task.results), [r.error for r in task.results]
    assert all("OK-FROM-FAKE-AI" in r.answer for r in task.results)

    # seleção explícita de conta: exatamente a que o usuário marcou
    assert t_pick.state == TaskState.DONE, f"{t_pick.state}: {t_pick.error}"
    assert len(t_pick.results) == 1, t_pick.routing
    assert t_pick.results[0].account_id == id2
    assert t_pick.results[0].ok is True, t_pick.results[0].error


# ====================================================== 2. login auto =====
def _spec_login(base_url: str) -> AdapterSpec:
    return AdapterSpec(
        id="fakelogin",
        name="Fake com login",
        url=base_url,
        new_chat_url=base_url,
        prompt_selector="textarea#prompt",
        submit={"key": "Enter", "selector": "button#send"},
        answer_selector="div#answer",
        settle_ms=800,
        max_wait_s=20,
        logged_in_selector="textarea#prompt",
        logged_out_selector="div#gate",
        login_user_selector="input#email",
        login_pass_selector="input#senha",
        login_submit_selector="button#entrar",
        login_wait_ms=1500,
    )


def _serve_login_site():
    import http.server
    import threading

    root = Path(__file__).resolve().parent

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a, **kw):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/fake_login.html"


def test_login_automatico_com_credenciais_do_cofre():
    """O agente entra no site sozinho e responde — sem ninguém logar na mão."""
    srv, url = _serve_login_site()

    async def main():
        bm = BrowserManager(get_settings())
        await bm.start()
        assert bm.enabled, bm.disabled_reason
        try:
            ctx = await bm.context_for("t-login-ok")
            page = await ctx.new_page()
            try:
                creds = {"username": "demo@exemplo.com", "password": "senha123"}
                return await run_browser_step(page, _spec_login(url), "tarefa depois do login", creds=creds)
            finally:
                await page.close()
        finally:
            await bm.stop()
            srv.shutdown()

    data = asyncio.run(main())
    assert data["ok"] is True, data
    assert data["login"]["attempted"] is True
    assert data["login"]["ok"] is True
    assert "LOGADO-E-RESPONDENDO" in data["answer"], data["answer"]


def test_login_automatico_falha_com_senha_errada_e_avisa():
    srv, url = _serve_login_site()

    async def main():
        bm = BrowserManager(get_settings())
        await bm.start()
        try:
            ctx = await bm.context_for("t-login-ruim")
            page = await ctx.new_page()
            try:
                creds = {"username": "demo@exemplo.com", "password": "senha-errada"}
                return await run_browser_step(page, _spec_login(url), "não deve responder", creds=creds)
            finally:
                await page.close()
        finally:
            await bm.stop()
            srv.shutdown()

    data = asyncio.run(main())
    assert data["ok"] is False
    assert data["logged_out"] is True
    assert data["login"]["attempted"] is True
    assert "login" in data["error"].lower()


def test_sem_senha_no_cofre_pede_login_manual():
    srv, url = _serve_login_site()

    async def main():
        bm = BrowserManager(get_settings())
        await bm.start()
        try:
            ctx = await bm.context_for("t-login-semcred")
            page = await ctx.new_page()
            try:
                return await run_browser_step(page, _spec_login(url), "oi", creds=None)
            finally:
                await page.close()
        finally:
            await bm.stop()
            srv.shutdown()

    data = asyncio.run(main())
    assert data["ok"] is False
    assert data["login"]["attempted"] is False
    assert "sem login automático configurado" in data["error"]


def test_cofre_grava_e_engine_consegue_ler(tmp_path, monkeypatch):
    """O caminho completo: cofre criptografado -> engine -> adapter."""
    vault_file = tmp_path / "vault.json"
    v = Vault(vault_file)
    v.put("acc_demo", "demo@exemplo.com", "senha123")

    # o engine lê via VAULT global; trocamos pela instância de teste
    import engine as engine_mod
    monkeypatch.setattr(engine_mod, "VAULT", v)

    blob = json.loads(vault_file.read_text(encoding="utf-8"))
    assert "senha123" not in json.dumps(blob)
    assert engine_mod.VAULT.get("acc_demo")["password"] == "senha123"
