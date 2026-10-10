"""Marca o mini agente arena-acorda depois da chamada.

Nao publica. Nao avisa no Telegram. Nao imprime sessao.
So grava se o estado inteiro foi restaurado antes.
"""
from __future__ import annotations

import asyncio
import os

os.environ["ORBE_STATE_RESTORE"] = "force"

import canais_24h
import state_backup


def main() -> None:
    rest = asyncio.run(state_backup.restaurar(forcar=True))
    print("restaurou", bool(rest.get("ok")))
    if not rest.get("ok"):
        print("nao_marquei")
        return
    canais_24h._marcar(
        "arena-acorda",
        "chamei a conversa existente, uma vez, para ver os mini agentes e os agentes. nao publiquei. nao mandei telegram.",
    )
    salvo = asyncio.run(state_backup.salvar(forcar=True))
    print("marquei", bool(salvo.get("ok")))


if __name__ == "__main__":
    main()
