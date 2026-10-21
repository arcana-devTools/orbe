"""Le propostas. Nao envia. Nao publica."""
from __future__ import annotations

import asyncio
import os

os.environ["ORBE_STATE_RESTORE"] = "force"

import propostas_leitura
import state_backup


def main() -> None:
    rest = asyncio.run(state_backup.restaurar(forcar=True))
    print("propostas", "restaurou", bool(rest.get("ok")), flush=True)
    if not rest.get("ok"):
        raise SystemExit(1)
    print(propostas_leitura.consultar(), flush=True)


if __name__ == "__main__":
    main()
