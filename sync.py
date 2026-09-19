"""Sincroniza arquivos arquivados para GitHub ou Google Drive.

Usa a SESSÃO do navegador da conta escolhida (perfil persistente onde o
usuário fez login uma vez pelo /desktop). Sem tokens/chaves: o Orbe pilota
a interface web do serviço, como faz com as IAs.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from browser import MANAGER
from events import BUS

REPO = "orbe-arquivos"


async def _new_page(profile: str, url: str) -> Any:
    ctx = await MANAGER.context_for(profile)
    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    return page


async def upload_github(profile: str, files: list[Path]) -> dict[str, Any]:
    page = await _new_page(profile, "https://github.com")
    try:
        user = await page.evaluate(
            "() => (document.querySelector('meta[name=\"user-login\"]')||{}).content || ''"
        )
        if not user:
            return {"ok": False, "error": "conta GitHub sem login — use o botão LOGIN no painel"}
        # garante o repositório
        await page.goto(f"https://github.com/{user}/{REPO}", wait_until="domcontentloaded")
        if "404" in (page.url + await page.title()) or page.locator("h1:has-text('404')").count():
            await page.goto("https://github.com/new", wait_until="domcontentloaded")
            await page.locator("input[name='repository[name]'], input[data-testid='repository-name-input']").first.fill(REPO)
            await page.get_by_role("button", name=re.compile("Create repository", re.I)).first.click()
            await page.wait_for_load_state("domcontentloaded")
        # descobre o branch default
        branch = "main"
        await page.goto(f"https://github.com/{user}/{REPO}/upload/{branch}", wait_until="domcontentloaded")
        if page.locator("input[type='file']").count() == 0:
            branch = "master"
            await page.goto(f"https://github.com/{user}/{REPO}/upload/{branch}", wait_until="domcontentloaded")
        inp = page.locator("input[type='file']").first
        await inp.set_input_files([str(f) for f in files])
        btn = page.get_by_role("button", name=re.compile("Commit changes", re.I)).first
        await btn.click(timeout=60000)
        await page.wait_for_timeout(1500)
        # diálogo de confirmação (UI nova) tem outro botão com o mesmo nome
        confirm = page.get_by_role("button", name=re.compile("Commit changes", re.I))
        if await confirm.count() > 1:
            await confirm.last.click()
        await page.wait_for_timeout(2000)
        url = f"https://github.com/{user}/{REPO}"
        await BUS.ok(f"github: {len(files)} arquivo(s) em {REPO}", "sync")
        return {"ok": True, "url": url}
    finally:
        await page.close()


async def upload_drive(profile: str, files: list[Path]) -> dict[str, Any]:
    page = await _new_page(profile, "https://drive.google.com/drive/my-drive")
    try:
        if "accounts.google" in page.url:
            return {"ok": False, "error": "conta Google sem login — use o botão LOGIN no painel"}
        inp = page.locator("input[type='file']")
        if await inp.count():
            await inp.first.set_input_files([str(f) for f in files])
        else:
            async with page.expect_file_chooser(timeout=15000) as fc:
                novo = page.get_by_role("button", name=re.compile("^(New|Novo)$", re.I)).first
                await novo.click()
                await page.get_by_text(re.compile("File upload|Upload de arquivo", re.I)).first.click()
            await fc.value.set_files([str(f) for f in files])
        await page.wait_for_timeout(4000)
        await BUS.ok(f"drive: {len(files)} arquivo(s) enviados", "sync")
        return {"ok": True, "url": "https://drive.google.com/drive/my-drive"}
    finally:
        await page.close()


async def sync_files(dest: str, files: list[Path], profile: str) -> dict[str, Any]:
    """dest: 'github' | 'drive'. Roda com trava do perfil (não concorre com tarefas)."""
    try:
        async with MANAGER.lock_for(profile):
            if dest == "github":
                return await asyncio.wait_for(upload_github(profile, files), 180)
            if dest == "drive":
                return await asyncio.wait_for(upload_drive(profile, files), 180)
        return {"ok": False, "error": f"destino desconhecido: {dest}"}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "timeout no upload"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
