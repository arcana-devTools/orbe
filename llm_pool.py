"""Motor de IA por API (sem navegador, sem arriscar a conta da Arena).

Ordem de tentativa (o primeiro que responder ganha):
  1. Groq       — grátis, sem cartão, rápido (gpt-oss-120b → qwen → gpt-oss-20b)
  2. OpenRouter — reserva: modelos ":free" descobertos na hora via /models
  3. Cloudflare — reserva grátis, sem cartão, quando o Groq estoura
  (Arena pelo navegador fica como último recurso, fora deste módulo)

Chaves: cofre em "llm_groq"/"llm_openrouter", ORBE_GROQ_API_KEY /
ORBE_OPENROUTER_API_KEY, e ORBE_CF_AI_TOKEN + ORBE_CF_ACCOUNT para a reserva.
Respeita limites do plano grátis: espaçamento mínimo + pausa ao levar 429.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

GROQ_URL = "https://api.groq.com/openai/v1"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
CF_URL = "https://api.cloudflare.com/client/v4/accounts"
GROQ_MODELOS = ["qwen/qwen3.8-27b", "openai/gpt-oss-safeguard-20b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
# Cada reserva tem cota própria. Uma acabar não derruba as outras.
RESERVAS = (
    ("kilo", "https://api.kilo.ai/api/gateway/chat/completions", ("kilo-auto/free", "qwen/qwen3.8-27b:free")),
    ("llm7", "https://api.llm7.io/v1/chat/completions", ("mistral-Nemo-Instruct-2407", "codestral-latest")),
    ("ovh", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions",
     ("Qwen3.6-27B", "Mistral-Small-3.2-24B-Instruct-2506", "Meta-Llama-3_3-70B-Instruct", "gpt-oss-20b")),
)
CF_MODELOS = ["@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/meta/llama-3.1-8b-instruct"]
OPENROUTER_PREFERIDOS = ["openai/gpt-oss-120b:free", "meta-llama/llama-3.3-70b-instruct:free",
                         "qwen/qwen3-235b-a22b:free", "deepseek/deepseek-chat-v3.1:free"]
GAP_MIN_S = 20          # espaçamento mínimo entre chamadas no mesmo provedor
GAP_CF_S = 2
_estado: dict[str, dict[str, Any]] = {}
_pausa_modelo: dict[str, float] = {}      # "groq:modelo" -> até quando evitar   # provedor -> {ultimo, pausa_ate, erro}
_cota_dia_ate = 0.0
_or_free_cache: dict[str, Any] = {"ts": 0.0, "ids": []}


def marcar_cota_dia(segundos: float) -> None:
    """A cota do dia acabou. Não gasta o resto em tentativa vazia."""
    global _cota_dia_ate
    ate = time.time() + min(max(float(segundos or 0), 3600), 8 * 3600)
    if ate > _cota_dia_ate:
        _cota_dia_ate = ate
    try:
        from pathlib import Path
        arq = Path("data/cota_dia.txt")
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(str(_cota_dia_ate))
    except Exception:
        pass


def cota_cheia() -> bool:
    global _cota_dia_ate
    if _cota_dia_ate <= 0:
        try:
            from pathlib import Path
            _cota_dia_ate = float(Path("data/cota_dia.txt").read_text().strip())
        except Exception:
            return False
    return time.time() < _cota_dia_ate


def _chave(nome: str) -> str:
    if nome == "cf":
        return (os.environ.get("ORBE_CF_AI_TOKEN", "") or os.environ.get("ORBE_CF_API_TOKEN", "")).strip()
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
    return [p for p in ("groq", "openrouter", "cf") if _chave(p)]


def disponivel() -> bool:
    return bool(provedores())


def status() -> dict[str, Any]:
    out = {}
    for p in ("groq", "openrouter", "cf"):
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



async def _chamada_cf(cx: httpx.AsyncClient, modelo: str, system: str, user: str,
                      max_tokens: int) -> tuple[str, str]:
    """Reserva grátis da Cloudflare. Sem cartão. A chave não sai daqui."""
    conta = os.environ.get("ORBE_CF_ACCOUNT", "").strip()
    chave = _chave("cf")
    if not conta or not chave:
        return "", "chave"
    url = f"{CF_URL}/{conta}/ai/run/{modelo}"
    try:
        r = await cx.post(
            url,
            headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
            json={"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                  "max_tokens": max_tokens},
        )
    except Exception as exc:
        return "", type(exc).__name__
    if r.status_code == 429:
        corpo = r.text.lower()
        if "daily" in corpo or "allocation" in corpo:
            marcar_cota_dia(6 * 3600)
        _pausa_modelo[f"cf:{modelo}"] = time.time() + 40
        return "", "429"
    if r.status_code in (401, 403):
        return "", "chave"
    if r.status_code != 200:
        return "", f"HTTP {r.status_code}"
    try:
        data = r.json()
        result = data.get("result") or {}
        txt = ""
        choices = result.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            txt = (msg.get("content") or "").strip()
        if not txt:
            txt = str(result.get("response") or "").strip()
    except Exception:
        txt = ""
    return (txt, "") if len(txt) >= 8 else ("", "resposta vazia")


async def _uma_chamada(cx: httpx.AsyncClient, prov: str, modelo: str, system: str, user: str,
                      max_tokens: int, temperature: float, web: bool) -> tuple[str, str]:
    """Devolve (texto, "") em sucesso ou ("", motivo) — motivo "chave" aborta o provedor."""
    import asyncio

    if prov == "cf":
        return await _chamada_cf(cx, modelo, system, user, max_tokens)
    chave = _chave(prov)
    base = GROQ_URL if prov == "groq" else OPENROUTER_URL
    hdr = {"Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    if prov == "openrouter":
        hdr.update({"HTTP-Referer": "https://github.com/arcana-devTools/orbe", "X-Title": "Orbe"})
    corpo = {"model": modelo, "temperature": temperature, "max_tokens": max_tokens,
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if web:
        corpo["tools"] = [{"type": "browser_search"}]
    for tentativa in range(3):          # limite POR MINUTO: espera os segundos pedidos e repete
        try:
            r = await cx.post(f"{base}/chat/completions", headers=hdr, json=corpo)
        except Exception as exc:
            return "", type(exc).__name__
        if r.status_code == 429 and web:
            _pausa_modelo[f"{prov}:{modelo}"] = time.time() + 120
            return "", "429 cota"
        if r.status_code == 429:
            try:
                ra = float(r.headers.get("retry-after", "60"))
            except ValueError:
                ra = 60.0
            corpo_txt = r.text.lower()
            diario = ("tokens per day" in corpo_txt or "tpd:" in corpo_txt) and ra > 90
            if not diario and ra <= 45 and tentativa < 2:
                await asyncio.sleep(ra + 1)
                continue
            # cota do dia: pula este modelo e deixa a reserva atender. Minuto: trava curta.
            espera_pausa = min(max(ra, 6 * 3600), 8 * 3600) if diario else min(max(ra, 12), 45)
            _pausa_modelo[f"{prov}:{modelo}"] = time.time() + espera_pausa
            if diario:
                marcar_cota_dia(ra)
            trecho = " ".join(r.text.split())[:80]
            return "", ("429 cota diária " if diario else "429 ") + trecho
        if r.status_code in (401, 403):
            return "", "chave"
        if r.status_code != 200:
            return "", f"HTTP {r.status_code}"
        try:
            msg = r.json()["choices"][0]["message"]
            txt = (msg.get("content") or msg.get("reasoning") or msg.get("reasoning_content") or "").strip()
        except Exception:
            txt = ""
        return (txt, "") if txt else ("", "resposta vazia")
    return "", "429"


async def _chamada_solta(cx: httpx.AsyncClient, nome: str, url: str, modelo: str,
                         system: str, user: str, max_tokens: int, temperature: float) -> tuple[str, str]:
    """Reserva sem chave. A cota de uma não trava as outras."""
    chave = f"{nome}:{modelo}"
    if time.time() < _pausa_modelo.get(chave, 0):
        return "", "pausa"
    try:
        r = await cx.post(
            url,
            json={
                "model": modelo,
                "messages": [
                    {"role": "system", "content": system[:1500]},
                    {"role": "user", "content": user[:4000]},
                ],
                "max_tokens": min(max_tokens, 600),
                "temperature": temperature,
            },
            timeout=50,
        )
    except Exception as exc:
        return "", type(exc).__name__
    if r.status_code == 429:
        _pausa_modelo[chave] = time.time() + 40
        return "", "429"
    if r.status_code != 200:
        return "", f"HTTP {r.status_code}"
    try:
        msg = r.json()["choices"][0]["message"]
        txt = (msg.get("content") or msg.get("reasoning") or "").strip()
    except Exception:
        txt = ""
    return (txt, "") if txt else ("", "resposta vazia")


async def _reservas(system: str, user: str, max_tokens: int, temperature: float) -> tuple[str, str, list[str]]:
    erros: list[str] = []
    async with httpx.AsyncClient(timeout=60) as cx:
        for nome, url, modelos in RESERVAS:
            for modelo in modelos:
                txt, motivo = await _chamada_solta(cx, nome, url, modelo, system, user, max_tokens, temperature)
                if txt:
                    return txt, f"{nome}:{modelo}", erros
                erros.append(f"{nome}/{modelo}: {motivo}")
    return "", "", erros


async def buscar_publico(consulta: str) -> str:
    """Busca pública. Não depende da cota do Groq."""
    import re

    q = (consulta or "").strip()[:180]
    if not q:
        return ""
    trechos: list[str] = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Orbe/1.0)"}
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as cx:
        try:
            r = await cx.get("https://lite.duckduckgo.com/lite/", params={"q": q})
            if r.status_code == 200:
                links = re.findall(r"result-link[^>]*>(.*?)</a>", r.text, re.S)
                snips = re.findall(r"result-snippet[^>]*>(.*?)</td>", r.text, re.S)
                for i, titulo in enumerate(links):
                    snip = snips[i] if i < len(snips) else ""
                    limpo = re.sub(r"<[^>]+>", " ", f"{titulo}: {snip}")
                    limpo = re.sub(r"\s+", " ", limpo).strip()
                    if len(limpo) > 20:
                        trechos.append(limpo[:300])
                    if len(trechos) >= 6:
                        break
        except Exception:
            pass
        if not trechos:
            try:
                r = await cx.get(
                    "https://pt.wikipedia.org/w/api.php",
                    params={"action": "opensearch", "search": q, "limit": 5, "format": "json"},
                )
                if r.status_code == 200:
                    data = r.json()
                    nomes = data[1] if len(data) > 1 else []
                    desc = data[2] if len(data) > 2 else []
                    for i, nome in enumerate(nomes):
                        extra = desc[i] if i < len(desc) else ""
                        trechos.append(f"{nome}: {extra}"[:300])
            except Exception:
                pass
    return "\n".join(trechos)[:2500]


async def chat(system: str, user: str, max_tokens: int = 3500,
               temperature: float = 0.7, web: bool = False) -> tuple[str, str]:
    """Devolve (texto, "provedor:modelo"). Levanta RuntimeError se nenhum respondeu.
    web=True: pesquisa na internet de verdade (Groq gpt-oss + browser_search)."""
    import asyncio

    erros = []
    pular_cf = cota_cheia()
    provs = (["groq"] if "groq" in provedores() else []) if web else provedores()
    async with httpx.AsyncClient(timeout=180) as cx:
        for prov in provs:
            st = _estado.setdefault(prov, {"ultimo": 0.0, "pausa_ate": 0.0, "erro": ""})
            if prov == "groq":
                modelos = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"] if web else GROQ_MODELOS
            elif prov == "cf":
                if pular_cf:
                    erros.append("cf: cota do dia")
                    continue
                modelos = CF_MODELOS
            else:
                modelos = await _modelos_openrouter(cx, _chave(prov))
            for modelo in modelos:
                falta = _pausa_modelo.get(f"{prov}:{modelo}", 0) - time.time()
                if falta > 20:
                    erros.append(f"{prov}/{modelo}: em pausa (cota)")
                    continue
                if falta > 0:
                    await asyncio.sleep(falta + 1)
                gap = GAP_CF_S if prov == "cf" else GAP_MIN_S
                if not st.get("erro"):
                    espera = gap - (time.time() - st["ultimo"])
                    if espera > 0:
                        await asyncio.sleep(espera)
                st["ultimo"] = time.time()
                txt, motivo = await _uma_chamada(cx, prov, modelo, system, user, max_tokens, temperature, web)
                if txt:
                    st["erro"] = ""
                    return txt, f"{prov}:{modelo}"
                st["erro"] = f"{modelo}: {motivo}"
                erros.append(f"{prov}/{modelo}: {motivo}")
                if motivo == "chave":
                    break
    if web:
        trechos = await buscar_publico(user)
        extra = ("\n\nTrechos públicos:\n" + trechos) if trechos else ""
        if not trechos:
            erros.append("busca pública vazia")
        try:
            return await chat(
                system,
                user + extra,
                max_tokens=max_tokens,
                temperature=temperature,
                web=False,
            )
        except Exception as exc:
            erros.append(str(exc)[:160])
    if not web:
        txt, origem, extra = await _reservas(system, user, max_tokens, temperature)
        erros.extend(extra)
        if txt:
            return txt, origem
    raise RuntimeError("; ".join(erros) or ("pesquisa web precisa da chave Groq" if web
                                             else "nenhuma chave de IA configurada"))


async def chat_reserva(system: str, user: str, max_tokens: int = 700,
                        temperature: float = 0.3) -> tuple[str, str]:
    """Só a reserva. A colônia usa quando o Groq não responde."""
    if cota_cheia() or not _chave("cf") or not os.environ.get("ORBE_CF_ACCOUNT", "").strip():
        txt, origem, extra = await _reservas(system, user, max_tokens, temperature)
        if txt:
            return txt, origem
        raise RuntimeError("; ".join(extra) or "reserva sem resposta")
    import asyncio

    erros = []
    async with httpx.AsyncClient(timeout=90) as cx:
        st = _estado.setdefault("cf", {"ultimo": 0.0, "pausa_ate": 0.0, "erro": ""})
        for modelo in CF_MODELOS:
            falta = _pausa_modelo.get(f"cf:{modelo}", 0) - time.time()
            if falta > 20:
                erros.append(f"cf/{modelo}: em pausa (cota)")
                continue
            txt, motivo = await _uma_chamada(cx, "cf", modelo, system, user, max_tokens, temperature, False)
            st["ultimo"] = time.time()
            if txt:
                st["erro"] = ""
                return txt, f"cf:{modelo}"
            st["erro"] = f"{modelo}: {motivo}"
            erros.append(f"cf/{modelo}: {motivo}")
            if motivo == "chave":
                break
    txt, origem, extra = await _reservas(system, user, max_tokens, temperature)
    if txt:
        return txt, origem
    erros.extend(extra)
    raise RuntimeError("; ".join(erros) or "reserva sem resposta")
