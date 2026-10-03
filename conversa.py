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


async def _responder(pergunta: str) -> str:
    """Responde a pergunta. Não devolve frase pronta no lugar da resposta."""
    import asyncio
    import httpx
    import llm_pool

    sistema = (
        "Você é o Orbe. O Hermes é a outra mão. "
        "Responda a pergunta do dono em português, direto, em até 4 frases. "
        "Se ele perguntar limite, diga o limite real, sem enrolar. "
        "Não invente dinheiro. Não repita senha, chave ou token. "
        "Não peça para ele fazer o passo."
    )
    try:
        txt, _origem = await asyncio.wait_for(
            llm_pool.chat(sistema, pergunta[:1800], max_tokens=220, temperature=0.3),
            16,
        )
        if (txt or "").strip():
            return _sem_segredo(txt.strip())
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=12) as cx:
            bruto, _motivo = await llm_pool._uma_chamada(
                cx, "groq", "openai/gpt-oss-safeguard-20b", sistema, pergunta[:1200], 180, 0.3, False
            )
        if (bruto or "").strip():
            return _sem_segredo(bruto.strip())
    except Exception:
        pass
    return ""


async def _voz_rapida(para: str, texto: str) -> list[tuple[str, str]]:
    curto = texto.strip().lower().strip("?!., ")
    cumprimento = curto in {"oi", "ola", "olá", "e ai", "e aí", "bom dia", "boa tarde", "boa noite"}
    pergunta = texto
    if not cumprimento:
        try:
            import asyncio
            import llm_pool
            visto = await asyncio.wait_for(llm_pool.buscar_publico(texto), 6)
        except Exception:
            visto = ""
        if visto:
            pergunta = texto[:700] + "\n\nVi agora:\n" + visto[:800] + "\n\nResponda a pergunta com isso, se servir."
    fala = await _responder(pergunta)
    if not fala:
        fala = "A cabeça não respondeu. Pergunta de novo."
    if para == "hermes":
        return [("hermes", fala)]
    if para == "orbe":
        return [("orbe", fala)]
    return [("orbe", fala), ("hermes", fala)]



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
