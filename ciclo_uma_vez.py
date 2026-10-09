"""Um ciclo dos canais, fora do Render. Nao imprime cookie nem senha."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

os.environ["ORBE_STATE_RESTORE"] = "force"

import canais_24h
import state_backup


def main() -> None:
    rest = asyncio.run(state_backup.restaurar(forcar=True))
    print("restaurou", bool(rest.get("ok")), rest.get("motivo") or rest.get("erro") or rest.get("arquivos"))
    if not rest.get("ok"):
        raise SystemExit(1)
    canais_24h.ciclo()
    salvo = asyncio.run(state_backup.salvar(forcar=True))
    print("salvou", bool(salvo.get("ok")), salvo.get("erro") or salvo.get("bytes") or salvo.get("igual"))
    doc = json.loads(Path("data/canais_24h.json").read_text(encoding="utf-8"))
    for nome, val in (doc.get("agentes") or {}).items():
        if isinstance(val, dict):
            texto = (val.get("ultimo") or "").replace("\n", " ")[:240]
            print(f"[{nome}] {texto}")


if __name__ == "__main__":
    main()
