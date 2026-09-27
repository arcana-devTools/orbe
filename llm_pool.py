"""Motor de IA por API (sem navegador, sem arriscar a conta da Arena).

Ordem de tentativa (o primeiro que responder ganha):
  1. Groq       — grátis, sem cartão, rápido (gpt-oss-120b → qwen → gpt-oss-20b)
  2. OpenRouter — reserva: modelos ":free" descobertos na hora via /models
  (3. Arena pelo navegador fica como último recurso, fora deste módulo)

Chaves: cofre (data/secrets, criptografado) em "llm_groq"/"llm_openrouter",
ou variáveis ORBE_GROQ_API_KEY / ORBE_OPENROUTER_API_KEY (Render).
Respeita limites do plano grátis: espaçamento mínimo + pausa ao levar 429.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

GROQ_URL = "https://api.groq.com/openai/v1"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
GROQ_MODELOS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
OPENROUTER_PREFERIDOS = ["openai/gpt-oss-120b:free", "meta-llama/llama-3.3-70b-instruct:free",
                         "qwen/qwen3-235b-a22b:free", "deepseek/deepseek-chat-v3.1:free"]
GAP_MIN_S = 20          # espaçamento mínimo entre chamadas no mesmo provedor
_estado: dict[str, dict[str, Any]] = {}   # provedor -> {ultimo, pausa_ate, erro}
_or_free_cache: dict[str, Any] = {"ts": 0.0, "ids": []}


def _chave(nome: str) -> str:
    env = os.environ.get(f"ORBE_{nome.upper()}_API_KEY", "").strip()
    if env:
        return env
    try:
        from secrets_vault import VAULT

        d = VAULT.get(f"llm_{nome}") or {}
        return str((d.get("extra") or {}).get("key", "")).strip()
    except Exception:
        return ""


def salvar_chave(nome: str, chave: str) -> None:
    from secrets_vault import VAULT

    VAULT.put(f"llm_{nome}", extra={"key": chave.strip()})


def provedores() -> list[str]:
    return [p for p in ("groq", "openrouter") if _chave(p)]


def disponivel() -> bool:
    return bool(provedores())


def status() -> dict[str, Any]:
    out = {}
    for p in ("groq", "openrouter"):
        k = _chave(p)
        st = _estado.get(p, {})
        out[p] = {"configurada": bool(k), "hint": ("…" + k[-4:]) if k else "",
                  "pausa_s": max(0, int(st.get("pausa_ate", 0) - time.time())),
                  "ultimo_erro": st.get("erro", "")}
    return out


async def _modelos_openrouter(cx: httpx.AsyncClient, chave: str) -> list[str]:
    if time.time() - _or_free_cache["ts"] < 6 * 3600 and _or_free_cache["ids"]:
        return _or_free_cache["ids"]
    try:
        r = await cx.get(f"{OPENROUTER_URL}/models", headers={"Authorization": f"Bearer {chave}"})
        ids = [m["id"] for m in r.json().get("data", []) if str(m.get("id", "")).endswith(":free")]
    except Exception:
        ids = []
    pref = [m for m in OPENROUTER_PREFERIDOS if m in ids] or OPENROUTER_PREFERIDOS[:2]
    resto = [m for m in ids if m not in pref][:3]
    _or_free_cache.update(ts=time.time(), ids=pref + resto)
    return _or_free_cache["ids"]


async def chat(system: str, user: str, max_tokens: int = 3500,
               temperature: float = 0.7) -> tuple[str, str]:
    """Devolve (texto, "provedor:modelo"). Levanta RuntimeError se nenhum respondeu."""
    erros = []
    async with httpx.AsyncClient(timeout=120) as cx:
        for prov in provedores():
            st = _estado.setdefault(prov, {"ultimo": 0.0, "pausa_ate": 0.0, "erro": ""})
            if time.time() < st["pausa_ate"]:
                erros.append(f"{prov}: em pausa (limite)")
                continue
            espera = GAP_MIN_S - (time.time() - st["ultimo"])
            if espera > 0:
                import asyncio

                await asyncio.sleep(espera)
            chave = _chave(prov)
            base = GROQ_URL if prov == "groq" else OPENROUTER_URL
            modelos = GROQ_MODELOS if prov == "groq" else await _modelos_openrouter(cx, chave)
            hdr = {"Authorization": f"Bearer {chave}"}
            if prov == "openrouter":
                hdr.update({"HTTP-Referer": "https://github.com/arcana-devTools/orbe", "X-Title": "Orbe"})
            for modelo in modelos:
                st["ultimo"] = time.time()
                try:
                    r = await cx.post(f"{base}/chat/completions", headers=hdr, json={
                        "model": modelo, "temperature": temperature, "max_tokens": max_tokens,
                        "messages": [{"role": "system", "content": system},
                                     {"role": "user", "content": user}]})
                except Exception as exc:
                    erros.append(f"{prov}/{modelo}: {type(exc).__name__}")
                    continue
                if r.status_code == 429:
                    try:
                        ra = float(r.headers.get("retry-after", "60"))
                    except ValueError:
                        ra = 60.0
                    st["pausa_ate"] = time.time() + min(max(ra, 30), 3600)
                    st["erro"] = "429 limite do plano grátis"
                    erros.append(f"{prov}: 429")
                    break  # limite é da conta, não do modelo → próximo provedor
                if r.status_code in (401, 403):
                    st["erro"] = f"{r.status_code} chave recusada"
                    erros.append(f"{prov}: {r.status_code}")
                    break
                if r.status_code != 200:
                    erros.append(f"{prov}/{modelo}: HTTP {r.status_code}")
                    continue  # modelo indisponível → tenta o próximo
                try:
                    txt = (r.json()["choices"][0]["message"].get("content") or "").strip()
                except Exception:
                    txt = ""
                if txt:
                    st["erro"] = ""
                    return txt, f"{prov}:{modelo}"
                erros.append(f"{prov}/{modelo}: resposta vazia")
    raise RuntimeError("; ".join(erros) or "nenhuma chave de IA configurada")
