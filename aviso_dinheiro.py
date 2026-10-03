"""Aviso ao dono no Telegram. So as 7h e as 18h, horario de Brasilia.

Uma vez em cada horario. Sem dizer o que estao fazendo.
Dinheiro simulado nao entra.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

HORAS = {7, 18}
MARCA = Path("data/aviso_horario.json")


def _cfg() -> tuple[str, str]:
    tok = os.environ.get("ORBE_TG_TOKEN", "").strip()
    chat = os.environ.get("ORBE_TG_CHAT", "").strip()
    if tok and chat:
        return tok, chat
    try:
        from autopilot import AUTOPILOT
        tok = tok or str(AUTOPILOT.cfg.get("bot_token") or "").strip()
        chat = chat or str(AUTOPILOT.cfg.get("chat_id") or "").strip()
    except Exception:
        pass
    return tok, chat


def _agora() -> tuple[int, str]:
    t = time.gmtime(time.time() - 3 * 3600)
    return t.tm_hour, time.strftime("%Y-%m-%d", t)


def _ler() -> dict:
    try:
        return json.loads(MARCA.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gravar(dado: dict) -> None:
    MARCA.parent.mkdir(parents=True, exist_ok=True)
    MARCA.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


def avisar(venda: dict) -> bool:
    """Nao manda na hora. O dinheiro real aparece no aviso das 7h e das 18h."""
    return False


def trabalhando() -> bool:
    hora, dia = _agora()
    if hora not in HORAS:
        return False
    chave = f"{dia}-{hora:02d}"
    marca = _ler()
    if marca.get("slot") == chave:
        return False
    tok, chat = _cfg()
    if not tok or not chat:
        return False
    desde = float(marca.get("ts") or 0)
    try:
        import vendas
        itens = vendas.ler()
        soma = float(vendas.totais(itens).get("BRL") or 0)
        novos = [v for v in itens if float(v.get("ts") or 0) > desde and str(v.get("moeda") or "") == "BRL"]
        novo = round(sum(float(v.get("valor") or 0) for v in novos), 2)
    except Exception:
        soma, novo = 0.0, 0.0
    extra = f"Dinheiro novo: R$ {novo:.2f}." if novo else "Dinheiro novo: nenhum."
    texto = f"Estao trabalhando. Soma real: R$ {soma:.2f}. {extra}"
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    corpo = json.dumps({"chat_id": chat, "text": texto[:4000]}).encode()
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            ok = 200 <= r.status < 300
    except Exception:
        return False
    if ok:
        _gravar({"slot": chave, "ts": time.time()})
    return ok


def raro(chave: str, segundos: int = 6 * 3600) -> bool:
    """True se esse aviso extra pode sair. Trava repeticao curta."""
    marca = _ler()
    extras = marca.get("extras") or {}
    agora = time.time()
    if agora - float(extras.get(chave) or 0) < segundos:
        return False
    extras[chave] = agora
    marca["extras"] = extras
    _gravar(marca)
    return True
