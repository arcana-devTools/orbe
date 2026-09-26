"""Botão SIM no Telegram (o sonho do dono: aprovar oportunidades com 1 toque).

Camadas:
1. AVISO com botões: quando o 🛰️ batedor acha ideia nova, manda mensagem com
   [✅ SIM, montar missão] [❌ ignorar].
2. LISTENER (getUpdates em polling): obedece o toque do dono:
   - ✅ → transforma a ideia em MISSÃO: vira gig no catálogo da fábrica
     (autônomos passam a produzir o produto dessa ideia) + confirma no Telegram
   - ❌ → marca como rejeitada (nunca mais insiste)
   - /radar → lista o radar
   - /status → resumo da colônia
Usa o MESMO bot_token/chat_id configurados no painel (digest do autopilot).
"""
from __future__ import annotations

import asyncio
import html
import json
import time
from pathlib import Path
from typing import Any

import httpx

DATA = Path("data")
RADAR = DATA / "renda_radar.json"
JOBS = DATA / "autonomo_jobs.json"
OFFSET_PATH = DATA / "tg_offset.txt"

_app: Any = None  # referência do main (AUTOPILOT, SWARM) resolvida sob demanda


def _cfg() -> tuple[str, str]:
    from autopilot import AUTOPILOT

    return str(AUTOPILOT.cfg.get("bot_token", "")), str(AUTOPILOT.cfg.get("chat_id", ""))


def _api_ok(payload: dict) -> dict:
    return {"ok": payload.get("ok") is True, "result": payload.get("result", [])}


async def _tg(method: str, **kw) -> dict:
    tok, _ = _cfg()
    if not tok:
        return {"ok": False, "result": []}
    try:
        async with httpx.AsyncClient(timeout=20) as cx:
            r = await cx.post(f"https://api.telegram.org/bot{tok}/{method}", json=kw)
            return _api_ok(r.json())
    except Exception:
        return {"ok": False, "result": []}


async def aviso_ideia(ideia: dict, idx: int) -> None:
    """Mensagem com botões SIM/não pra uma ideia nova do radar."""
    _, chat = _cfg()
    if not chat:
        return
    txt = (
        f"💡 <b>IDEIA CAÇADA</b> (#{idx})\n\n"
        f"<b>{html.escape(str(ideia.get('ideia', '')))}</b>\n"
        f"{html.escape(str(ideia.get('como_funciona', '')))[:400]}\n\n"
        f"💰 potencial: R$ {ideia.get('potencial_brl_mes', '?')}/mês"
        f" • ⏱️ {ideia.get('esforco_horas_semana', '?')}h/sem"
        f" • risco: {html.escape(str(ideia.get('risco', '?')))}\n"
        f"1º passo: {html.escape(str(ideia.get('primeiro_passo', '')))[:200]}\n\n"
        f"Montar missão pra colônia produzir isso?"
    )
    teclado = {"inline_keyboard": [[
        {"text": "✅ SIM, montar", "callback_data": f"sim_{idx}"},
        {"text": "❌ ignorar", "callback_data": f"nao_{idx}"},
    ]]}
    await _tg("sendMessage", chat_id=chat, text=txt, parse_mode="HTML",
              reply_markup=teclado)


async def _radar_lista() -> str:
    itens = _radar()
    if not itens:
        return "🛰️ radar vazio — os batedores ainda estão caçando."
    linhas = []
    for i, x in enumerate(itens[-10:]):
        idx = len(itens) - 10 + i if len(itens) > 10 else i
        marca = "✅" if x.get("status") == "aprovada" else ("❌" if x.get("status") == "rejeitada" else "•")
        linhas.append(f"#{idx}{marca} {str(x.get('ideia'))[:60]} — R${x.get('potencial_brl_mes', '?')}/mês (score {x.get('score')})")
    return "🛰️ <b>RADAR</b>\n" + "\n".join(linhas) + "\n\nResponde ✅ numa pra montar missão, ou /sim <número>"


def _radar() -> list[dict]:
    try:
        return json.loads(RADAR.read_text(encoding="utf-8"))
    except Exception:
        return []


def _radar_salvar(itens: list[dict]) -> None:
    RADAR.parent.mkdir(exist_ok=True)
    RADAR.write_text(json.dumps(itens[-80:], ensure_ascii=False, indent=1), encoding="utf-8")


def _aprovar(idx: int) -> str:
    itens = _radar()
    if idx < 0 or idx >= len(itens):
        return f"índice #{idx} não existe — manda /radar pra ver os números"
    it = itens[idx]
    it["status"] = "aprovada"
    it["aprovada_em"] = time.time()
    _radar_salvar(itens)
    # vira GIG da fábrica: catálogo lê data/autonomo_jobs.json a cada expedição
    try:
        cat = json.loads(JOBS.read_text(encoding="utf-8"))
        slug = "missao_" + "".join(c if c.isalnum() else "_" for c in str(it.get("ideia", "")).lower())[:24]
        if not any(g.get("id") == slug for g in cat.get("entregas", [])):
            cat.setdefault("entregas", []).append({
                "id": slug,
                "nome": f"Produto: {str(it.get('ideia'))[:48]}",
                "preco": 5.0,
                "prompt": (
                    f"Crie um PRODUTO DIGITAL COMPLETO e pronto pra vender sobre: {it.get('ideia')}. "
                    f"Como funciona: {it.get('como_funciona')} "
                    "Entregue: título vendedor, descrição da página de vendas, e o conteúdo do produto "
                    "bem estruturado (seções com textos completos). Em português."
                ),
            })
        JOBS.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return (f"🚀 MISSÃO CRIADA: {str(it.get('ideia'))[:60]}\n"
            "A colônia já tem o produto no catálogo — entregas começam nos próximos ciclos.")


def _rejeitar(idx: int) -> str:
    itens = _radar()
    if 0 <= idx < len(itens):
        itens[idx]["status"] = "rejeitada"
        _radar_salvar(itens)
        return f"❌ ideia #{idx} descartada (não insisto mais)"
    return f"índice #{idx} não existe"


async def _status() -> str:
    from autonomous import SWARM

    s = SWARM.state()
    return (f"🤖 <b>ORBE AUTÔNOMO</b>\n"
            f"viv@s: {s['vivos']} • clones: {s['clones']} • ciclos: {s['ciclos']}\n"
            f"💼 entregas reais: {s.get('entregas_total', 0)} (receita interna R$ {s.get('receita_total', 0)})")


def _offset() -> int:
    try:
        return int(OFFSET_PATH.read_text().strip() or 0)
    except Exception:
        return 0


def _offset_salvar(v: int) -> None:
    try:
        OFFSET_PATH.write_text(str(v), encoding="utf-8")
    except Exception:
        pass


async def _tratar(update: dict) -> None:
    _, chat = _cfg()
    msg = update.get("message") or {}
    cb = update.get("callback_query") or {}
    texto = ""
    alvo_chat = chat
    if cb:
        data = str(cb.get("data", ""))
        _, alvo_chat = str(cb.get("message", {}).get("chat", {}).get("id", "")), chat
        if data.startswith("sim_"):
            texto = _aprovar(int(data[4:]))
        elif data.startswith("nao_"):
            texto = _rejeitar(int(data[4:]))
        await _tg("answerCallbackQuery", callback_query_id=cb.get("id"))
    else:
        cmd = str(msg.get("text", "")).strip().lower()
        if cmd.startswith("/radar"):
            texto = await _radar_lista()
        elif cmd.startswith("/sim "):
            try:
                texto = _aprovar(int(cmd.split()[1]))
            except Exception:
                texto = "uso: /sim <número> (ver /radar)"
        elif cmd.startswith("/status"):
            texto = await _status()
        elif cmd.startswith("/start"):
            texto = ("🤖 Orbe Autônomo na escuta!\n\n"
                     "/radar — ver ideias caçadas\n"
                     "/sim <nº> — aprovar ideia\n"
                     "/status — colônia\n\n"
                     "Quando o batedor achar algo, mando botões ✅/❌ aqui.")
        else:
            return
    if texto:
        await _tg("sendMessage", chat_id=alvo_chat, text=texto, parse_mode="HTML")


async def _poller() -> None:
    while True:
        tok, chat = _cfg()
        if not tok or not chat:
            await asyncio.sleep(20)
            continue
        res = (await _tg("getUpdates", offset=_offset(), timeout=25)).get("result", [])
        for u in res:
            _offset_salvar(int(u.get("update_id", 0)) + 1)
            try:
                await _tratar(u)
            except Exception:
                pass
        await asyncio.sleep(2 if res else 5)


def iniciar() -> None:
    asyncio.get_running_loop().create_task(_poller())
