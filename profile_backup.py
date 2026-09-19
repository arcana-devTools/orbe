"""Backup criptografado do perfil Chrome no GitHub (opcional).

Por que: o Render (plano free) reinicia o container quando quer e o disco é
efêmero — sem backup, cada reinício pedia login de novo. Com um token do
GitHub (só leitura/escrita de Contents), o Orbe sobe um zip CRIPTOGRAFADO
(Fernet, chave derivada do próprio token) do perfil em
``<seu-user>/orbe/profiles/`` e o restaura no boot. O repo pode ser público:
sem o token, o .enc é lixo.

O que entra no zip: só o que segura a sessão (Cookies, Local/Session Storage,
Login Data, Preferences). Caches ficam de fora.
"""
from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken

from config import get_settings

_s = get_settings()

GH = "https://api.github.com"
REPO = "orbe"
MAX_ZIP = 60 * 1024 * 1024  # 60 MB já é perfil doente; não sobe

SKIP_DIRS = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "GrShaderCache",
    "ShaderCache", "blob_storage", "Crashpad", "component_crx_cache",
    "optimization_guide", "Service Worker", "VideoDecodeStats",
    "Safe Browsing", "Feature Engagement Tracker", "segmentation_platform",
}
SKIP_SUFFIX = (".log", ".lock")


def _fernet(token: str) -> Fernet:
    key = hashlib.sha256(("orbe-profile-backup:" + token.strip()).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _profile_dir(profile: str) -> Path:
    return Path(_s.profile_path(profile))


def _zip_profile(profile_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(profile_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(profile_dir)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if p.name.endswith(SKIP_SUFFIX):
                continue
            z.write(p, rel.as_posix())
    return buf.getvalue()


async def _gh_user(token: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{GH}/user", headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            return None
        return r.json().get("login")


def _path_in_repo(account_id: str, platform: str) -> str:
    return f"profiles/{platform}--{account_id}.enc"


async def backup_profile(profile: str, account_id: str, platform: str, token: str) -> dict[str, Any]:
    """Sobe o perfil criptografado. Falha silencioso (não derruba o login)."""
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "sem token de backup"}
    pdir = _profile_dir(profile)
    if not pdir.exists():
        return {"ok": False, "error": "perfil não existe"}
    raw = _zip_profile(pdir)
    if not raw:
        return {"ok": False, "error": "zip vazio"}
    if len(raw) > MAX_ZIP:
        return {"ok": False, "error": f"perfil grande demais ({len(raw)//1024//1024} MB)"}
    blob = _fernet(token).encrypt(raw)
    user = await _gh_user(token)
    if not user:
        return {"ok": False, "error": "token inválido no GitHub"}
    path = _path_in_repo(account_id, platform)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=120) as c:
        cur = await c.get(f"{GH}/repos/{user}/{REPO}/contents/{path}", headers=headers)
        sha = cur.json().get("sha") if cur.status_code == 200 else None
        body: dict[str, Any] = {
            "message": f"orbe: backup de perfil {platform}",
            "content": base64.b64encode(blob).decode("ascii"),
        }
        if sha:
            body["sha"] = sha
        r = await c.put(f"{GH}/repos/{user}/{REPO}/contents/{path}", headers=headers, json=body)
        if r.status_code not in (200, 201):
            return {"ok": False, "error": f"github: {r.status_code}"}
    return {"ok": True, "kb": len(blob) // 1024}


async def restore_profile(profile: str, account_id: str, platform: str, token: str) -> dict[str, Any]:
    """Baixa e descriptografa o perfil, se o local estiver vazio."""
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "sem token de backup"}
    pdir = _profile_dir(profile)
    if pdir.exists() and any(pdir.iterdir()):
        return {"ok": False, "skipped": True, "error": "perfil local já existe"}
    user = await _gh_user(token)
    if not user:
        return {"ok": False, "error": "token inválido no GitHub"}
    path = _path_in_repo(account_id, platform)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(f"{GH}/repos/{user}/{REPO}/contents/{path}", headers=headers)
        if r.status_code != 200:
            return {"ok": False, "error": "sem backup no github"}
        blob = base64.b64decode(r.json().get("content", ""))
    try:
        raw = _fernet(token).decrypt(blob)
    except InvalidToken:
        return {"ok": False, "error": "token não confere com o backup"}
    pdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            dest = (pdir / name).resolve()
            if not str(dest).startswith(str(pdir.resolve())):
                continue  # anti path-traversal
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, open(dest, "wb") as out:
                out.write(src.read())
    return {"ok": True}

META_PATH = "profiles/_meta.enc"


async def backup_meta(token: str) -> dict[str, Any]:
    """Lista de contas + prefs (sem o token) criptografados — pra o Render
    reiniciar e o painel voltar com as contas que você criou."""
    import json

    from store import STORE

    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "sem token"}
    payload = {
        "accounts": [a.model_dump() for a in STORE.accounts.values()],
        "prefs": {k: v for k, v in STORE.prefs.items() if k != "backup_token"},
    }
    blob = _fernet(token).encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    user = await _gh_user(token)
    if not user:
        return {"ok": False, "error": "token inválido no GitHub"}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=60) as c:
        cur = await c.get(f"{GH}/repos/{user}/{REPO}/contents/{META_PATH}", headers=headers)
        sha = cur.json().get("sha") if cur.status_code == 200 else None
        body: dict[str, Any] = {
            "message": "orbe: backup de contas/prefs",
            "content": base64.b64encode(blob).decode("ascii"),
        }
        if sha:
            body["sha"] = sha
        r = await c.put(f"{GH}/repos/{user}/{REPO}/contents/{META_PATH}", headers=headers, json=body)
        if r.status_code not in (200, 201):
            return {"ok": False, "error": f"github: {r.status_code}"}
    return {"ok": True}


async def restore_meta(token: str) -> dict[str, Any]:
    """Restaura contas/prefs quando o container reinicia com tudo vazio."""
    import json

    from store import STORE

    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "sem token"}
    if STORE.accounts:
        return {"ok": False, "skipped": True}
    user = await _gh_user(token)
    if not user:
        return {"ok": False, "error": "token inválido no GitHub"}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{GH}/repos/{user}/{REPO}/contents/{META_PATH}", headers=headers)
        if r.status_code != 200:
            return {"ok": False, "error": "sem meta backup"}
        blob = base64.b64decode(r.json().get("content", ""))
    try:
        data = json.loads(_fernet(token).decrypt(blob))
    except Exception:
        return {"ok": False, "error": "token não confere"}
    from models import Account

    n = 0
    for a in data.get("accounts", []):
        try:
            STORE.accounts[a["id"]] = Account(**a)
            n += 1
        except Exception:
            pass
    prefs = data.get("prefs", {}) or {}
    prefs["backup_token"] = token
    STORE.prefs = prefs
    STORE.save_accounts()
    STORE.save_prefs()
    return {"ok": True, "accounts": n}
