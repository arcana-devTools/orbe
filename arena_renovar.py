"""Renova a sessao da Arena. Nao imprime cookie. Nao grava cookie vazio."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

from nacl import encoding, public

NOMES = ("arena-auth-prod-v1.0", "arena-auth-prod-v1.1")
REPO = "arcana-devTools/orbe"


def _pedir() -> tuple[int, dict[str, str]]:
    c0 = os.environ.get("ARENA_COOKIE_0", "").strip()
    c1 = os.environ.get("ARENA_COOKIE_1", "").strip()
    if not c0:
        print("sem_sessao")
        raise SystemExit(1)
    cookie = f"{NOMES[0]}={c0}"
    if c1:
        cookie += f"; {NOMES[1]}={c1}"
    req = urllib.request.Request(
        "https://arena.ai/api/me",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Cookie": cookie,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            status = resp.status
            corpo = resp.read(4000).decode("utf-8", "replace")
            brutos = resp.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as exc:
        status = exc.code
        corpo = exc.read(4000).decode("utf-8", "replace")
        brutos = exc.headers.get_all("Set-Cookie") or []
    novos = {}
    for item in brutos:
        nome = item.split("=", 1)[0]
        if nome not in NOMES:
            continue
        valor = item.split(";", 1)[0].split("=", 1)[1]
        if not valor or "max-age=0" in item.lower():
            continue
        novos[nome] = valor
    logado = status == 200 and bool(re.search(r'"email":"[^"]', corpo))
    print("login", status, "logado", logado, "cookies_novos", len(novos))
    return status, novos if logado else {}


def _salvar(novos: dict[str, str]) -> None:
    pat = os.environ.get("ORBE_GITHUB_PAT", "").strip()
    if not pat or not novos:
        print("mantive_a_sessao_anterior")
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        chave = json.loads(resp.read().decode())
    box = public.SealedBox(public.PublicKey(chave["key"].encode(), encoding.Base64Encoder()))
    mapa = {NOMES[0]: "ARENA_COOKIE_0", NOMES[1]: "ARENA_COOKIE_1"}
    for nome, valor in novos.items():
        segredo = mapa[nome]
        cifrado = base64.b64encode(box.encrypt(valor.encode())).decode()
        corpo = json.dumps({"encrypted_value": cifrado, "key_id": chave["key_id"]}).encode()
        put = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{segredo}",
            data=corpo,
            method="PUT",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(put, timeout=25) as resp:
            print("salvou", segredo, resp.status, "len", len(valor))


def main() -> None:
    status, novos = _pedir()
    if status != 200:
        raise SystemExit(2)
    _salvar(novos)
    print("pronta")


if __name__ == "__main__":
    main()
