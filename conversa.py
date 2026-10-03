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


def _texto_hermes(dado: Any) -> str:
    if isinstance(dado, dict):
        for k in ("saida", "resumo", "texto", "resultado", "msg"):
            v = dado.get(k)
            if isinstance(v, str) and v.strip():
                return _sem_segredo(v.strip())
        return _sem_segredo(json.dumps(dado, ensure_ascii=False))
    return _sem_segredo(str(dado))


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


async def _voz_rapida(para: str, texto: str) -> list[tuple[str, str]]:
    """Uma chamada só, no modelo que já responde. Não espera a fila inteira."""
    import httpx
    import llm_pool

    if para == "hermes":
        sistema = (
            "Você é o Hermes. Português, uma frase curta. "
            "Responda ao dono. Não peça passo. Não invente dinheiro."
        )
    elif para == "orbe":
        sistema = (
            "Você é o Orbe. Português, uma frase curta. "
            "Responda ao dono. Não peça passo. Não invente dinheiro. Não conte o método."
        )
    else:
        sistema = (
            "Você é a caixa. Duas linhas, português, curtas. "
            "Linha 1 começa com Orbe: . Linha 2 começa com Hermes: . "
            "Não peça passo. Não invente dinheiro. Não conte o método."
        )
    curto = texto.strip().lower()
    cumprimento = len(curto) < 28 and not any(x in curto for x in ("?", "hoje", "agora", "preco", "preço", "cotac", "noticia", "notícia", "quanto"))
    visto = ""
    if not cumprimento:
        try:
            import asyncio
            visto = await asyncio.wait_for(llm_pool.buscar_publico(texto), 5)
        except Exception:
            visto = ""
        sistema += " Se houver texto em 'Vi agora', use isso para fato e número. Se não houver, diga que não viu fora. Não invente."
        if visto:
            texto = texto[:700] + "\n\nVi agora:\n" + visto[:900]
        else:
            texto = texto[:700] + "\n\nNão vi nada fora agora."
    chave = llm_pool._chave("groq")
    txt = ""
    if chave:
        try:
            async with httpx.AsyncClient(timeout=8) as cx:
                bruto, _motivo = await llm_pool._uma_chamada(
                    cx, "groq", "qwen/qwen3.8-27b", sistema, texto[:1600], 140, 0.3, False
                )
                txt = (bruto or "").strip()
        except Exception:
            txt = ""
    if not txt:
        try:
            import asyncio
            txt, _origem, _erros = await asyncio.wait_for(
                llm_pool._reservas(sistema, texto[:800], 80, 0.3), 8
            )
        except Exception:
            txt = ""
    txt = _sem_segredo(txt)
    if para == "os dois":
        orbe, hermes = "Estou aqui.", "Recebi."
        for linha in txt.splitlines():
            s = linha.strip()
            baixo = s.lower()
            if baixo.startswith("orbe:"):
                orbe = s.split(":", 1)[1].strip() or orbe
            elif baixo.startswith("hermes:"):
                hermes = s.split(":", 1)[1].strip() or hermes
        if txt and orbe == "Estou aqui." and "hermes:" not in txt.lower():
            orbe = txt
        return [("orbe", orbe), ("hermes", hermes)]
    quem = "hermes" if para == "hermes" else "orbe"
    return [(quem, txt or "Estou aqui.")]


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
