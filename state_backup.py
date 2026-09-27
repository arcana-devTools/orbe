"""Memória que sobrevive: estado da colônia criptografado no GitHub.

O Render grátis APAGA o disco ao dormir/reiniciar/redeployar. Então:
- a cada 10 min (se mudou) e ao desligar → empacota data/*.json + últimas
  entregas, criptografa (Fernet, chave ORBE_STATE_KEY) e grava em
  estado/orbe-state.enc na branch `orbe-estado` do repo
  (NUNCA na main: push na main = Render redeploya = loop de reinícios).
- no boot, se data/autonomous.json não existe (Render acordou zerado) → baixa,
  decifra e restaura tudo antes da colônia/Telegram começarem.

Variáveis: ORBE_STATE_KEY (obrigatória p/ ligar), ORBE_GITHUB_PAT,
ORBE_GITHUB_REPO (padrão arcana-devTools/orbe), ORBE_ESTADO_BACKUP=0 desliga.
Segredos do cofre (data/secrets) NÃO entram — no Render vêm das variáveis.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import os
import tarfile
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

DATA = Path("data")
ARQUIVOS = ["autonomous.json", "autonomo_jobs.json", "renda_radar.json",
            "autopilot.json", "tg_offset.txt", "prefs.json", "briefs.json"]
MAX_RESULTADOS = 60           # últimas entregas (.md) que viajam junto
BRANCH = "orbe-estado"
CAMINHO = "estado/orbe-state.enc"
GH = "https://api.github.com"
INTERVALO_S = 600
_status: dict[str, Any] = {"ultimo_backup": 0.0, "ultimo_restore": 0.0, "erro": "", "hash": ""}


def _cofre(nome: str) -> dict:
    try:
        from secrets_vault import VAULT

        return VAULT.get(nome) or {}
    except Exception:
        return {}


def _chave_estado() -> str:
    return os.environ.get("ORBE_STATE_KEY", "").strip() or \
        str((_cofre("state_key").get("extra") or {}).get("key", "")).strip()


def _pat() -> str:
    return os.environ.get("ORBE_GITHUB_PAT", "").strip() or \
        str((_cofre("github").get("extra") or {}).get("pat", "")).strip()


def _repo() -> str:
    return os.environ.get("ORBE_GITHUB_REPO", "arcana-devTools/orbe").strip()


def ativo() -> bool:
    return os.environ.get("ORBE_ESTADO_BACKUP", "1") != "0" and bool(_chave_estado() and _pat())


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_chave_estado().encode()).digest()))


def _hdr() -> dict:
    return {"Authorization": f"Bearer {_pat()}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


# ------------------------------------------------------------------ pacote
def empacotar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for nome in ARQUIVOS:
            p = DATA / nome
            if p.exists():
                tar.add(p, arcname=nome)
        prod = DATA / "produtos"
        if prod.exists():
            for p in prod.glob("*/*"):
                if p.suffix in (".json", ".md"):
                    tar.add(p, arcname=f"produtos/{p.parent.name}/{p.name}")
        res = DATA / "resultados"
        if res.exists():
            mds = sorted(res.glob("*.md"), key=lambda x: x.stat().st_mtime)[-MAX_RESULTADOS:]
            for p in mds:
                tar.add(p, arcname=f"resultados/{p.name}")
    return buf.getvalue()


def desempacotar(dados: bytes) -> list[str]:
    DATA.mkdir(parents=True, exist_ok=True)
    nomes = []
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
        for m in tar.getmembers():
            # só arquivos comuns, sem caminho absoluto nem "..": nada escapa de data/
            if not m.isfile() or m.name.startswith("/") or ".." in Path(m.name).parts:
                continue
            destino = DATA / m.name
            destino.parent.mkdir(parents=True, exist_ok=True)
            f = tar.extractfile(m)
            if f:
                destino.write_bytes(f.read())
                nomes.append(m.name)
    return nomes


# ------------------------------------------------------------------ GitHub
async def _garantir_branch(cx: httpx.AsyncClient) -> None:
    r = await cx.get(f"{GH}/repos/{_repo()}/git/ref/heads/{BRANCH}", headers=_hdr())
    if r.status_code == 200:
        return
    main = await cx.get(f"{GH}/repos/{_repo()}/git/ref/heads/main", headers=_hdr())
    main.raise_for_status()
    sha = main.json()["object"]["sha"]
    c = await cx.post(f"{GH}/repos/{_repo()}/git/refs", headers=_hdr(),
                      json={"ref": f"refs/heads/{BRANCH}", "sha": sha})
    if c.status_code not in (201, 422):   # 422 = já criada por outra chamada
        c.raise_for_status()


async def salvar(forcar: bool = False) -> dict[str, Any]:
    if not ativo():
        return {"ok": False, "motivo": "backup desligado (falta ORBE_STATE_KEY ou PAT)"}
    bruto = empacotar()
    h = hashlib.sha256(bruto).hexdigest()
    if not forcar and h == _status["hash"]:
        return {"ok": True, "igual": True}
    cifrado = _fernet().encrypt(bruto)
    try:
        async with httpx.AsyncClient(timeout=60) as cx:
            # commit ÓRFÃO + ref forçada: a branch guarda só a foto mais recente
            # (o histórico não cresce a cada 10 min e o repo não incha)
            base = f"{GH}/repos/{_repo()}/git"
            b = await cx.post(f"{base}/blobs", headers=_hdr(),
                              json={"content": base64.b64encode(cifrado).decode(), "encoding": "base64"})
            b.raise_for_status()
            t = await cx.post(f"{base}/trees", headers=_hdr(), json={"tree": [
                {"path": CAMINHO, "mode": "100644", "type": "blob", "sha": b.json()["sha"]}]})
            t.raise_for_status()
            c = await cx.post(f"{base}/commits", headers=_hdr(), json={
                "message": f"estado {time.strftime('%Y-%m-%d %H:%M')}", "tree": t.json()["sha"], "parents": []})
            c.raise_for_status()
            sha = c.json()["sha"]
            r = await cx.patch(f"{base}/refs/heads/{BRANCH}", headers=_hdr(), json={"sha": sha, "force": True})
            if r.status_code == 422 or r.status_code == 404:   # branch ainda não existe
                r = await cx.post(f"{base}/refs", headers=_hdr(), json={"ref": f"refs/heads/{BRANCH}", "sha": sha})
            r.raise_for_status()
    except Exception as exc:
        _status["erro"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return {"ok": False, "erro": _status["erro"]}
    _status.update(ultimo_backup=time.time(), hash=h, erro="")
    return {"ok": True, "bytes": len(cifrado)}


async def restaurar(forcar: bool = False) -> dict[str, Any]:
    """Só restaura se o disco está zerado (Render) — ou se forçado."""
    if not ativo():
        return {"ok": False, "motivo": "backup desligado"}
    if (DATA / "autonomous.json").exists() and not forcar \
            and os.environ.get("ORBE_STATE_RESTORE") != "force":
        return {"ok": False, "motivo": "disco já tem estado (não sobrescrevo)"}
    try:
        async with httpx.AsyncClient(timeout=30) as cx:
            r = await cx.get(f"{GH}/repos/{_repo()}/contents/{CAMINHO}",
                             headers={**_hdr(), "Accept": "application/vnd.github.raw+json"},
                             params={"ref": BRANCH})
        if r.status_code == 404:
            return {"ok": False, "motivo": "ainda não há backup no GitHub"}
        r.raise_for_status()
        bruto = _fernet().decrypt(r.content)
    except InvalidToken:
        _status["erro"] = "ORBE_STATE_KEY diferente da usada no backup"
        return {"ok": False, "erro": _status["erro"]}
    except Exception as exc:
        _status["erro"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return {"ok": False, "erro": _status["erro"]}
    nomes = desempacotar(bruto)
    _status.update(ultimo_restore=time.time(), hash=hashlib.sha256(bruto).hexdigest(), erro="")
    return {"ok": True, "arquivos": len(nomes)}


async def laco() -> None:
    while True:
        await asyncio.sleep(INTERVALO_S)
        try:
            await salvar()
        except Exception:
            pass


def status() -> dict[str, Any]:
    return {"ativo": ativo(), "branch": BRANCH, "repo": _repo(), **{k: v for k, v in _status.items() if k != "hash"}}
