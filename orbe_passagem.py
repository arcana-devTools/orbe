"""Orbe de passagem. Nao sobe servidor. Nao chama o Render. Nao publica."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

os.environ["ORBE_STATE_RESTORE"] = "force"

import state_backup


def main() -> None:
    rest = asyncio.run(state_backup.restaurar(forcar=True))
    print("passagem", "restaurou", bool(rest.get("ok")), flush=True)
    if not rest.get("ok"):
        raise SystemExit(1)
    doc = json.loads(Path("data/canais_24h.json").read_text(encoding="utf-8"))
    for nome, val in (doc.get("agentes") or {}).items():
        if isinstance(val, dict):
            texto = (val.get("ultimo") or "").replace("\n", " ")[:200]
            print(f"[{nome}] {texto}", flush=True)
    print("host suspenso nao foi chamado", flush=True)


if __name__ == "__main__":
    main()
