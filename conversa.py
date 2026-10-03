"""Caixa de entrada do dono. Orbe responde. Hermes recebe e devolve."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

ARQ = Path("data/conversa.json")
_SEGREDO = re.compile(
    r"(?i)(senha|password|token|pat|api[_ ]?key|cookie|authorization)\s*[:=]\s*\S+"
    r"|eyJ[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{10,}"
)


def _sem_segredo(txt: str) -> str:
    return _SEGREDO.sub("…", txt or "")[:1800]


def _ler() -> dict[str, Any]:
    try:
        d = json.loads(ARQ.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("msgs"), list):
            return d
    except Exception:
        pass
    return {"msgs": [], "hermes_ts": 0.0}


def _salvar(d: dict[str, Any]) -> None:
    d["msgs"] = (d.get("msgs") or [])[-80:]
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    ARQ.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


def _interno(txt: str) -> bool:
    s = (txt or "").strip()
    if not s.startswith("{") and not s.startswith("["):
        return False
    return any(x in s for x in ("falta_brl", '"feito"', '"origem"', '"ok":'))


def _texto_hermes(dado: Any) -> str:
    if isinstance(dado, dict):
        for k in ("saida", "resumo", "texto", "resultado", "msg"):
            v = dado.get(k)
            if isinstance(v, str) and v.strip() and not _interno(v):
                return _sem_segredo(v.strip())
        return ""
    texto = _sem_segredo(str(dado))
    return "" if _interno(texto) else texto


def _ingerir_hermes(d: dict[str, Any]) -> None:
    try:
        reg = json.loads(Path("data/hermes_ultimo.json").read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(reg, dict) or reg.get("status") != "recebido":
        return
    ts = float(reg.get("ts") or 0)
    if ts <= float(d.get("hermes_ts") or 0):
        return
    texto = _texto_hermes(reg.get("dado"))
    if not texto.strip():
        d["hermes_ts"] = ts
        return
    d["msgs"].append({"ts": ts, "de": "hermes", "texto": texto})
    d["hermes_ts"] = ts


def lista() -> dict[str, Any]:
    d = _ler()
    antes = len(d["msgs"])
    _ingerir_hermes(d)
    if len(d["msgs"]) != antes:
        _salvar(d)
    return {"msgs": d["msgs"]}


def _contexto() -> str:
    import time
    linhas = [f"Agora é {time.strftime('%d/%m/%Y %H:%M')}. Você está no ar, não num chat de 2024."]
    try:
        import mao
        linhas.append("O celular está no ar." if mao.online("celular") else "O celular está fora.")
        linhas.append("O PC está no ar." if mao.online("pc") else "O PC está fora.")
    except Exception:
        pass
    linhas.append("Você olha a web e age pelo celular, pelo PC e pelo Hermes.")
    return "\n".join(linhas)


def _preso(txt: str) -> bool:
    t = (txt or "").lower()
    return ("2024" in t and ("até" in t or "ate" in t)) or "fora deste ambiente" in t or "fora desse ambiente" in t


async def _chamar(quem: str, pergunta: str, extra: str = "") -> str:
    import asyncio
    import httpx
    import llm_pool

    if quem == "hermes":
        sistema = (
            "Você é o Hermes, as mãos da colônia. Fale em português, com as suas palavras, em até 3 frases. "
            "Você sai e faz. Não diga que está preso num chat. Não copie o Orbe. "
            "Não invente dinheiro. Não repita senha, chave ou token."
        )
    else:
        sistema = (
            "Você é o Orbe, a colônia. Fale em português, com as suas palavras, em até 3 frases. "
            "Você não é um assistente preso em 2024. Você olha fora e age. "
            "Não copie o Hermes. Não invente dinheiro. Não repita senha, chave ou token."
        )
    if extra:
        sistema += " " + extra
    corpo = _contexto() + "\n\n" + pergunta[:1500]
    try:
        async with httpx.AsyncClient(timeout=12) as cx:
            bruto, _motivo = await llm_pool._uma_chamada(
                cx, "groq", "qwen/qwen3.8-27b", sistema, corpo, 180, 0.5, False
            )
        if (bruto or "").strip():
            return _sem_segredo(bruto.strip())
    except Exception:
        pass
    try:
        txt, _origem = await asyncio.wait_for(
            llm_pool.chat(sistema, corpo, max_tokens=180, temperature=0.5),
            12,
        )
        if (txt or "").strip():
            return _sem_segredo(txt.strip())
    except Exception:
        pass
    return ""


async def _uma(quem: str, pergunta: str) -> str:
    fala = await _chamar(quem, pergunta)
    if fala and _preso(fala):
        fala = await _chamar(quem, pergunta, "A fala anterior estava errada. Responda de novo, sem dizer que está preso em 2024.")
    return fala or ""


async def _voz_rapida(para: str, texto: str) -> list[tuple[str, str]]:
    import asyncio

    curto = texto.strip().lower().strip("?!., ")
    cumprimento = curto in {"oi", "ola", "olá", "e ai", "e aí", "bom dia", "boa tarde", "boa noite"}
    base = texto
    if not cumprimento:
        try:
            import llm_pool
            visto = await asyncio.wait_for(llm_pool.buscar_publico(texto), 5)
        except Exception:
            visto = ""
        if visto:
            base = texto[:600] + "\n\nVi agora:\n" + visto[:700]
    quem = ["orbe", "hermes"] if para == "os dois" else [para if para in ("orbe", "hermes") else "orbe"]
    falas = await asyncio.gather(*[_uma(q, base) for q in quem])
    saida = []
    for q, fala in zip(quem, falas):
        saida.append((q, fala or "Não consegui responder agora."))
    return saida



def _sair_hermes(texto: str) -> None:
    try:
        import asyncio

        loop = asyncio.get_running_loop()

        async def _vai() -> None:
            try:
                import hermes
                await hermes.pedir("Mensagem do dono na caixa: " + texto[:1500])
            except Exception:
                pass

        loop.create_task(_vai())
    except Exception:
        pass


async def enviar(para: str, texto: str) -> dict[str, Any]:
    texto = (texto or "").strip()[:2000]
    if not texto:
        return {"ok": False, "motivo": "vazio"}
    para = para if para in ("orbe", "hermes", "os dois") else "os dois"
    d = _ler()
    _ingerir_hermes(d)
    d["msgs"].append({"ts": time.time(), "de": "dono", "texto": texto, "para": para})
    _salvar(d)
    try:
        falas = await _voz_rapida(para, texto)
    except Exception:
        falas = [("orbe", "Estou aqui.")]
    for quem, fala in falas:
        d["msgs"].append({"ts": time.time(), "de": quem, "texto": fala or "Estou aqui."})
    _salvar(d)
    if para in ("hermes", "os dois"):
        _sair_hermes(texto)
    return {"ok": True, "msgs": d["msgs"]}
