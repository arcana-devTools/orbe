"""🤝 Hermes — as MÃOS que a colônia aluga quando o corpo dela não alcança.

Divisão combinada (e combinada com o dono):
- **Orbe** é o cérebro: percebe, decide, guarda o dinheiro, lembra (diário/habilidades)
  e é a única que fala com o dono.
- **Hermes** (Nous Research, MIT) é o par de mãos: roda uma tarefa só, descartável,
  dentro de um job do GitHub Actions — de graça, sem cartão, sem instalar nada no
  PC do dono — e com IP residencial (WARP), que é onde o captcha não aparece.

Como a Orbe chama: `pedir("tarefa")` → dispara o workflow → o Hermes executa →
o resultado volta em `POST /api/hermes/resultado` e entra no diário dela.
Nenhuma credencial do dono viaja no texto da tarefa: elas vivem como secrets do Actions.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ULTIMO = Path("data/hermes_ultimo.json")
REPO = os.environ.get("ORBE_HERMES_REPO", "arcana-devTools/orbe-uic")
WORKFLOW = os.environ.get("ORBE_HERMES_WF", "hermes.yml")


def disponivel() -> bool:
    """Só faz sentido chamar se existir o PAT do GitHub (e o workflow no repo)."""
    return bool(os.environ.get("ORBE_GITHUB_PAT", "").strip())


def _pat() -> str:
    pat = os.environ.get("ORBE_GITHUB_PAT", "").strip()
    if pat:
        return pat
    try:
        from secrets_vault import VAULT

        d = VAULT.get("github") or {}
        return str((d.get("extra") or {}).get("pat", "")).strip()
    except Exception:
        return ""


async def pedir(tarefa: str, voltar: str = "orbe") -> dict[str, Any]:
    """Dispara o Hermes numa tarefa. O texto NÃO deve conter senha nem token."""
    import httpx

    pat = _pat()
    if not pat:
        return {"ok": False, "motivo": "sem PAT do GitHub"}
    if not tarefa.strip():
        return {"ok": False, "motivo": "tarefa vazia"}
    r = httpx.post(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
        json={"ref": "main", "inputs": {"tarefa": tarefa[:1800], "voltar": voltar}},
        timeout=45,
    )
    if r.status_code >= 300:
        return {"ok": False, "motivo": f"HTTP {r.status_code}: {r.text[:160]}"}
    reg = {"ts": time.time(), "tarefa": tarefa[:300], "status": "enviada"}
    ULTIMO.parent.mkdir(parents=True, exist_ok=True)
    ULTIMO.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "resumo": f"chamei o Hermes: {tarefa[:70]}"}


def anotar_resultado(dado: dict[str, Any]) -> dict[str, Any]:
    """Guarda o que o Hermes devolveu e registra no diário da colônia."""
    reg = {"ts": time.time(), "status": "recebido", "dado": json.loads(json.dumps(dado))[:6000]}
    try:
        ULTIMO.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    try:
        import conciencia

        conciencia.anotar(f"Hermes devolveu: {str(dado)[:180]}", acao="hermes")
    except Exception:
        pass
    return {"ok": True}
