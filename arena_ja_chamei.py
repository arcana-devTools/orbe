"""Uma chamada por dia civil em Brasilia. Nao imprime sessao."""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))
REPO = "arcana-devTools/orbe"
WORKFLOW = "arena-orbe-auto.yml"


def ja_enviou_hoje() -> bool:
    pat = os.environ.get("ORBE_GITHUB_PAT", "").strip()
    atual = os.environ.get("GITHUB_RUN_ID", "").strip()
    if not pat:
        print("trava_indisponivel")
        return False
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=12",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "orbe-arena-checar",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            dados = json.loads(resp.read().decode())
    except Exception as exc:
        print("trava_indisponivel", type(exc).__name__)
        return False
    hoje = datetime.now(BRT).date()
    for run in dados.get("workflow_runs") or []:
        if str(run.get("id") or "") == atual:
            continue
        if run.get("conclusion") != "success":
            continue
        created = run.get("created_at") or ""
        try:
            dt = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(BRT)
        except ValueError:
            continue
        if dt.date() == hoje:
            print("ja_chamei_hoje")
            return True
    return False


def main() -> None:
    enviar = "nao" if ja_enviou_hoje() else "sim"
    path = os.environ.get("GITHUB_OUTPUT", "")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"enviar={enviar}\n")
    print("enviar", enviar)


if __name__ == "__main__":
    main()
