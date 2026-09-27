"""Orbe se configura sozinho no Render (API oficial) — o dono não clica em nada.

Uso (sandbox/PC/Termux, com a chave no cofre "render" ou ORBE_RENDER_API_KEY):
    python3 render_admin.py status              # acha o serviço "orbe", mostra deploy/variáveis (só nomes)
    python3 render_admin.py env ARQUIVO.env     # MESCLA as variáveis do arquivo (não apaga as outras)
    python3 render_admin.py deploy              # dispara deploy e acompanha até Live
Nunca imprime valores de variáveis.
"""
from __future__ import annotations

import os
import sys
import time

import httpx

API = "https://api.render.com/v1"
NOME_SERVICO = os.environ.get("ORBE_RENDER_SERVICO", "orbe")


def _chave() -> str:
    k = os.environ.get("ORBE_RENDER_API_KEY", "").strip()
    if k:
        return k
    from secrets_vault import VAULT

    return str(((VAULT.get("render") or {}).get("extra") or {}).get("key", "")).strip()


def _cx() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=30, headers={
        "Authorization": f"Bearer {_chave()}", "Accept": "application/json"})


def servico(cx: httpx.Client) -> dict:
    r = cx.get("/services", params={"name": NOME_SERVICO, "limit": 20})
    r.raise_for_status()
    for item in r.json():
        s = item.get("service", item)
        if s.get("name") == NOME_SERVICO:
            return s
    raise SystemExit(f"serviço '{NOME_SERVICO}' não encontrado nesta conta Render")


def env_atual(cx: httpx.Client, sid: str) -> dict[str, str]:
    out, cursor = {}, None
    while True:
        r = cx.get(f"/services/{sid}/env-vars", params={"limit": 100, **({"cursor": cursor} if cursor else {})})
        r.raise_for_status()
        itens = r.json()
        for it in itens:
            ev = it.get("envVar", it)
            out[ev["key"]] = ev.get("value", "")
        if len(itens) < 100:
            return out
        cursor = itens[-1].get("cursor")


def ler_env(caminho: str) -> dict[str, str]:
    d = {}
    for linha in open(caminho, encoding="utf-8"):
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def aplicar_env(novas: dict[str, str]) -> list[str]:
    with _cx() as cx:
        sid = servico(cx)["id"]
        tudo = env_atual(cx, sid)
        tudo.update(novas)                       # mescla: não apaga o que já existia
        r = cx.put(f"/services/{sid}/env-vars", json=[{"key": k, "value": v} for k, v in tudo.items()])
        r.raise_for_status()
        return sorted(tudo)


def deploy(esperar_s: int = 900) -> str:
    with _cx() as cx:
        sid = servico(cx)["id"]
        r = cx.post(f"/services/{sid}/deploys", json={"clearCache": "do_not_clear"})
        r.raise_for_status()
        did = r.json()["id"]
        t0, st = time.time(), ""
        while time.time() - t0 < esperar_s:
            st = cx.get(f"/services/{sid}/deploys/{did}").json().get("status", "")
            if st in ("live", "build_failed", "update_failed", "canceled", "deactivated"):
                return st
            time.sleep(15)
        return st or "timeout"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        with _cx() as cx:
            s = servico(cx)
            print("serviço:", s["name"], s["id"], "| branch:", s.get("branch"), "| suspenso:", s.get("suspended"))
            print("variáveis (nomes):", sorted(env_atual(cx, s["id"])))
    elif cmd == "env":
        print("variáveis agora:", aplicar_env(ler_env(sys.argv[2])))
    elif cmd == "deploy":
        print("deploy terminou:", deploy())
