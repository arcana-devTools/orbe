"""
v0.12 — probe ativo de login (check_probe) + sintaxe INLINE de divisão por conta.

Problema que motivou: a home pública da Arena tem textarea ("Ask anything…"),
então logged_in_selector genérico reportava "ok" (logado) pra conta VAZIA.
O probe clica no seletor de modos e procura um item que só existe logado.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
import yaml

from adapters import Registry, check_login
from browser import MANAGER
from config import get_settings
from orchestrator import Orchestrator

ROOT_TESTS = Path(__file__).resolve().parent
EXPECT = '[role="menuitem"]:text-matches("^\\\\s*Agent\\\\s*$")'


def _spec(tmp_path: Path, url: str):
    (tmp_path / "fakeprobe.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "fakeprobe",
                "name": "Fake Probe",
                "kind": "browser",
                "url": url,
                "new_chat_url": url,
                "prompt_selector": "textarea#prompt",
                # armadilha: textarea VISÍVEL mesmo deslogado (como a Arena)
                "logged_in_selector": "textarea#prompt",
                "logged_out_selector": "a[href*='nao-existe-em-nenhum-lugar']",
                "check_probe": {"click": "button#modes", "expect": EXPECT},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return Registry(Path(str(tmp_path))).get("fakeprobe")


@pytest.mark.parametrize(
    "variant,esperado", [("logado", "ok"), ("deslogado", "logged_out")]
)
def test_probe_no_menu(tmp_path, monkeypatch, fake_site, variant, esperado):
    """logado -> ok; deslogado -> logged_out MESMO com a textarea genérica
    visível (o falso 'ok' que a Arena produzia)."""
    monkeypatch.setattr(get_settings(), "platforms_dir", str(tmp_path))
    base = fake_site.rsplit("/", 1)[0]  # fake_site vem como .../fake_chat.html
    dst = ROOT_TESTS / f"fake_probe_{variant}.html"
    shutil.copyfile(ROOT_TESTS / "fake_probe.html", dst)
    spec = _spec(tmp_path, f"{base}/{dst.name}")

    async def run():
        await MANAGER.start()
        try:
            ctx = await MANAGER.context_for("t-probe")
            page = await ctx.new_page()
            try:
                await page.goto(spec.url, wait_until="domcontentloaded")
                return await check_login(page, spec)
            finally:
                await page.close()
        finally:
            await MANAGER.stop()

    try:
        assert asyncio.run(run()) == esperado
    finally:
        dst.unlink(missing_ok=True)


# ------------------------------------------------- split inline por conta
def test_split_inline_com_barra():
    r = Orchestrator._split_per_account(
        "conta 1: escreva um poema curto / conta 2: escreva um haiku sobre o mar", 2
    )
    assert r[0] == "escreva um poema curto"
    assert r[1] == "escreva um haiku sobre o mar"


def test_split_inline_com_ponto_virgula():
    r = Orchestrator._split_per_account("conta 1: clima; conta 2: chuva", 2)
    assert r == ["clima", "chuva"]


def test_split_barra_solta_nao_quebra_texto_sem_diretiva():
    r = Orchestrator._split_per_account("pesquise Trends / insights de IA", 2)
    assert r[0] == r[1] == "pesquise Trends / insights de IA"


def test_split_mistura_inline_e_multilinha():
    goal = "Tema: clima\nconta 1: foque no Brasil / conta 2: foque na Europa"
    r = Orchestrator._split_per_account(goal, 2)
    assert r[0] == "foque no Brasil", r
    assert r[1] == "foque na Europa", r
