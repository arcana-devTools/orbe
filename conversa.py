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


async def _voz(quem: str, texto: str) -> str:
    import llm_pool

    if quem == "hermes":
        sistema = (
            "Você é o Hermes, as mãos da colônia. Português, frases curtas. "
            "Responda ao dono. Não peça para ele fazer o passo. Não invente dinheiro. "
            "Não repita senha, chave ou token."
        )
    else:
        sistema = (
            "Você é o Orbe, a colônia. Português, frases curtas. "
            "Responda ao dono. O Hermes é a outra mão. Não peça para ele fazer o passo. "
            "Não invente dinheiro. Não repita senha, chave ou token. Não conte o método."
        )
    txt, _origem = await llm_pool.chat(sistema, texto[:2000], max_tokens=220, temperature=0.4)
    return _sem_segredo((txt or "").strip()) or "Estou aqui."


async def enviar(para: str, texto: str) -> dict[str, Any]:
    texto = (texto or "").strip()[:2000]
    if not texto:
        return {"ok": False, "motivo": "vazio"}
    para = para if para in ("orbe", "hermes", "os dois") else "os dois"
    d = _ler()
    _ingerir_hermes(d)
    agora = time.time()
    d["msgs"].append({"ts": agora, "de": "dono", "texto": texto, "para": para})
    novos: list[dict[str, Any]] = []
    if para in ("orbe", "os dois"):
        try:
            fala = await _voz("orbe", texto)
        except Exception:
            fala = "A cabeça apertou. Manda de novo daqui a pouco."
        item = {"ts": time.time(), "de": "orbe", "texto": fala}
        d["msgs"].append(item)
        novos.append(item)
    if para in ("hermes", "os dois"):
        try:
            fala = await _voz("hermes", texto)
        except Exception:
            fala = "Recebi. A voz apertou, mas eu sigo."
        item = {"ts": time.time(), "de": "hermes", "texto": fala}
        d["msgs"].append(item)
        novos.append(item)
        try:
            import hermes

            h = await hermes.pedir("Mensagem do dono na caixa: " + texto[:1500])
            if not h.get("ok"):
                aviso = {"ts": time.time(), "de": "hermes", "texto": "Não consegui sair agora."}
                d["msgs"].append(aviso)
                novos.append(aviso)
        except Exception:
            aviso = {"ts": time.time(), "de": "hermes", "texto": "Não consegui sair agora."}
            d["msgs"].append(aviso)
            novos.append(aviso)
    _salvar(d)
    return {"ok": True, "msgs": d["msgs"], "novos": novos}
