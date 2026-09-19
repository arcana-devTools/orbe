"""
Teste ponta-a-ponta: cria conta -> envia tarefa -> engine abre o perfil,
consulta a IA falsa, grava resultado e sintetiza.
"""
from __future__ import annotations

import asyncio

import pytest

from browser import MANAGER
from config import get_settings
from engine import get_engine
from models import Account, TaskState
from store import STORE


def test_task_end_to_end_com_chromium_real(tmp_platform_yaml):
    async def main():
        # prepara: conta no perfil de teste + adapter apontando para a IA falsa
        acc = Account(platform="fakechat", label="teste", profile="t-e2e")
        STORE.add_account(acc)

        await MANAGER.start()
        assert MANAGER.enabled, f"chromium não subiu: {MANAGER.disabled_reason}"
        try:
            eng = get_engine()
            eng.registry.reload()
            assert eng.registry.get("fakechat") is not None

            task = await eng.submit("explique o que é um agente de IA", prefer=["fakechat"])
            for _ in range(90):          # até ~90s
                await asyncio.sleep(1)
                if task.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELED):
                    break
            return task.model_copy(deep=True)
        finally:
            await MANAGER.stop()
            STORE.delete_account(acc.id)

    task = asyncio.run(main())

    assert task.state == TaskState.DONE, f"{task.state}: {task.error}"
    assert len(task.results) == 1
    r = task.results[0]
    assert r.ok is True, r.error
    assert r.platform == "fakechat"
    assert "OK-FROM-FAKE-AI" in r.answer
    assert "explique o que é um agente" in r.answer
    assert r.elapsed_s > 0
    assert task.synthesis and "OK-FROM-FAKE-AI" in task.synthesis
    assert task.finished_at is not None
    assert task.plan, "plano deveria estar preenchido"


def test_rota_para_site_inexistente_falha_sem_quebrar_a_tarefa(tmp_path):
    """Uma rota quebrada não pode derrubar as outras (gather com return_exceptions)."""
    async def main():
        from adapters import AdapterSpec
        from orchestrator import Orchestrator

        acc = Account(platform="site-morto", label="morto", profile="t-dead")
        STORE.add_account(acc)
        await MANAGER.start()
        try:
            eng = get_engine()
            bad = AdapterSpec(
                id="site-morto",
                name="Site Morto",
                url="http://127.0.0.1:9/nao-existe",   # porta fechada
                new_chat_url="http://127.0.0.1:9/nao-existe",
                prompt_selector="textarea",
                settle_ms=500,
                max_wait_s=5,
            )
            eng.orch.registry.specs[bad.id] = bad
            task = await eng.submit("tente algo impossível", prefer=["site-morto"])
            for _ in range(60):
                await asyncio.sleep(1)
                if task.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELED):
                    break
            return task.model_copy(deep=True)
        finally:
            await MANAGER.stop()
            STORE.delete_account(acc.id)

    task = asyncio.run(main())
    assert task.state in (TaskState.DONE, TaskState.FAILED)
    assert task.results, "deveria ter registrado o resultado da rota"
    assert task.results[0].ok is False
    assert task.results[0].error
