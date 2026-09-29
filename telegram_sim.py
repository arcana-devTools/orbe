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
import os
import time
from pathlib import Path
from typing import Any

import httpx

DATA = Path("data")
RADAR = DATA / "renda_radar.json"
JOBS = DATA / "autonomo_jobs.json"
OFFSET_PATH = DATA / "tg_offset.txt"

REGRAS_PRODUTO = 'REGRAS: o produto é UM arquivo único e CONCRETO (ex.: um pack de checklists ou templates preenchíveis sobre um nicho específico), com TODO o conteúdo escrito por extenso — nada de sumário de capítulos vazios. NÃO prometa arquivos, bônus, planilhas, imagens, garantias, reembolsos ou resultados de renda que não estejam no próprio texto. Página de vendas honesta: diga exatamente o que o comprador recebe. Mínimo 2500 palavras de conteúdo útil.'

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


async def enviar_produto(meta: dict) -> bool:
    """Manda o PDF pronto pro dono com ✅ aprovar / 🔁 refazer + a página de vendas."""
    import acabamento

    tok, chat = _cfg()
    pdf = acabamento.garantir_pdf(meta["id"])
    if not tok or not chat or not pdf:
        return False
    chave = meta["id"][:15]
    cr = meta.get("critica", {})
    evid = "\n".join(f"• {e.get('sinal', '')[:90]} — {e.get('url', '')[:80]}" for e in meta.get("evidencias", [])[:2])
    legenda = (f"📦 PRODUTO PRONTO: {meta['titulo']}\n{meta.get('subtitulo', '')}\n\n"
               f"{meta['paginas']} páginas • preço sugerido {acabamento.preco_fmt(meta)}\n"
               + ("🇺🇸 em inglês — pro Etsy (EUA)\n" if meta.get("idioma") == "en" else "🇧🇷 em português\n")
               + f"🧐 nota do crítico: {cr.get('media', '?')}/10\n"
               + (f"🔎 demanda comprovada:\n{evid}\n" if evid else "")
               + "\nAbre o PDF, confere, e decide:")[:1000]
    teclado = {"inline_keyboard": [[
        {"text": "✅ Aprovar p/ vender", "callback_data": f"pok_{chave}"},
        {"text": "🔁 Refazer", "callback_data": f"prf_{chave}"}],
        [{"text": "📝 ver página de vendas", "callback_data": f"pvd_{chave}"}]]}
    try:
        async with httpx.AsyncClient(timeout=60) as cx:
            r = await cx.post(f"https://api.telegram.org/bot{tok}/sendDocument",
                              data={"chat_id": chat, "caption": legenda,
                                    "reply_markup": json.dumps(teclado)},
                              files={"document": (f"{meta['titulo'][:50]}.pdf", pdf.read_bytes(),
                                                  "application/pdf")})
            return r.json().get("ok") is True
    except Exception:
        return False


HORA_RESUMO = int(os.environ.get("ORBE_TG_HORA", "19") or 19)   # horário de Brasília
_enviando = False


def _hora_brasilia() -> int:
    return time.gmtime(time.time() - 3 * 3600).tm_hour


async def resumo_diario(forcar: bool = False) -> bool:
    """Única notificação do dia: no HORA_RESUMO, só se houver produto aprovado pelo crítico
    que o dono ainda não viu. Sem produto → silêncio total."""
    global _enviando
    import acabamento

    if _enviando or (not forcar and _hora_brasilia() != HORA_RESUMO):
        return False
    import vendas

    tok, chat = _cfg()
    novos = [m for m in acabamento._metas() if m.get("status") == "aguardando_dono" and not m.get("notificado")]
    ultimo = _ultimo_resumo()
    vendas_novas = vendas.desde(ultimo)
    try:
        import freelas

        propostas = freelas.pendentes()
        est_wk = freelas.estado()
        liberou = bool(est_wk.get("liberado_em")) and not est_wk.get("liberacao_avisada")
    except Exception:
        propostas, liberou = [], False
    if not tok or not chat or not (novos or vendas_novas or propostas or liberou):
        return False
    if time.time() - ultimo < 20 * 3600 and not forcar:     # nunca 2 resumos no mesmo dia
        return False
    _enviando = True
    try:
        dia = time.time() - 86400
        metas = acabamento._metas()
        reprov = sum(1 for m in metas if m.get("status") == "reprovado" and m.get("criado", 0) > dia)
        try:
            import mercado

            pesq = sum(1 for b in mercado.ler() if b.get("ts", b.get("criado", 0)) > dia)
        except Exception:
            pesq = 0
        try:
            import aprendizado

            apr = aprendizado.resumo_txt()
        except Exception:
            apr = ""
        partes = ["🌙 Resumo do dia", vendas.resumo_txt(ultimo)]
        if novos:
            partes.append(f"📦 {len(novos)} produto(s) passaram no crítico e esperam sua decisão (abaixo).")
        if liberou:
            partes.append("🎉 O Workana LIBEROU seu perfil: já dá pra enviar propostas.")
            est_wk["liberacao_avisada"] = time.time()
            freelas._salvar_estado(est_wk)
        if propostas:
            partes.append(f"💼 {len(propostas)} proposta(s) de freela no Workana esperando seu OK (abaixo).")
        partes.append(f"(últimas 24h: {pesq} pesquisa(s) de mercado, {reprov} produto(s) barrado(s) pelo crítico)")
        if apr:
            partes.append(apr)
        await _tg("sendMessage", chat_id=chat, text="\n".join(partes))
        _marcar_resumo()
        for m in novos[:3]:
            if await enviar_produto(m):
                m["notificado"] = time.time()
                p = acabamento.PRODUTOS / m["id"] / "meta.json"
                p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        for v in propostas[:3]:
            if await enviar_proposta(v):
                itens = freelas.ler()
                for x in itens:
                    if x["slug"] == v["slug"]:
                        x["notificado"] = time.time()
                freelas._salvar(itens)
        __import__("state_backup").sujo()
        return True
    finally:
        _enviando = False


async def enviar_proposta(v: dict) -> bool:
    """Vaga do Workana + proposta escrita pela colônia, com ✅ enviar / ❌ pular."""
    tok, chat = _cfg()
    if not tok or not chat:
        return False
    chave = v["slug"][:48]
    eh99 = v.get("plataforma") == "99freelas"
    extra = ""
    if eh99:
        try:
            import freelas99

            con = (await freelas99.painel()).get("conexoes")
            extra = f"🎟️ enviar custa {freelas99.CUSTO_CONEXOES} conexões (você tem {con})\n"
        except Exception:
            extra = "🎟️ enviar custa 3 conexões\n"
    texto = (f"💼 FREELA ({'99Freelas' if eh99 else 'Workana'}): {v['titulo']}\n"
             f"💵 {v['orcamento']} • {v['propostas']} propostas {v['publicado']}\n" + extra
             + ("✅ cliente com pagamento verificado\n" if v.get("pagamento_verificado") else "")
             + f"🧐 chance (IA): {v.get('nota', '?')}/10 — {v.get('motivo_ia', '')}\n"
             f"💰 preço sugerido: {v.get('preco_sugerido', '?')} • prazo {v.get('prazo_dias', '?')} dia(s)\n"
             f"{v['url']}\n\n📝 Proposta:\n{v.get('proposta', '')}")[:4000]
    teclado = {"inline_keyboard": [[{"text": "✅ Enviar", "callback_data": f"fok_{chave}"},
                                    {"text": "❌ Pular", "callback_data": f"fno_{chave}"}]]}
    try:
        r = await _tg("sendMessage", chat_id=chat, text=texto, reply_markup=teclado,
                      disable_web_page_preview=True)
        return r.get("ok") is True
    except Exception:
        return False


async def _decidir_freela(chave: str, enviar: bool) -> str:
    import freelas

    v = freelas.marcar(chave, "aprovada" if enviar else "pulada")
    if not v:
        return "vaga não encontrada"
    if not enviar:
        return f"❌ Pulei: {html.escape(v['titulo'][:80])}"
    if v.get("plataforma") == "99freelas":          # aqui dá pra enviar de verdade, na hora
        import freelas99

        try:
            r = await freelas99.enviar(v)
        except Exception as exc:
            r = {"ok": False, "motivo": f"{type(exc).__name__}: {str(exc)[:120]}"}
        freelas.marcar(chave, "enviada" if r.get("ok") else "falhou_envio")
        if r.get("ok"):
            return (f"📨 Proposta ENVIADA no 99Freelas: {html.escape(v['titulo'][:80])}\n"
                    f"Oferta R$ {r['oferta']:.2f}. Se o cliente responder, te aviso no resumo.")
        return (f"⚠️ Não consegui enviar no 99Freelas: {html.escape(str(r.get('motivo') or r.get('resposta'))[:200])}\n"
                f"Link: {v['url']}")
    return (f"✅ Aprovada: {html.escape(v['titulo'][:80])}\n"
            "O Workana ainda não liberou seu perfil para enviar propostas; assim que liberar, "
            "a colônia envia as aprovadas sozinha.")


_RESUMO = Path("data/tg_resumo.json")


def _ultimo_resumo() -> float:
    try:
        return float(json.loads(_RESUMO.read_text(encoding="utf-8")).get("ultimo", 0))
    except Exception:
        return 0.0


def _marcar_resumo() -> None:
    _RESUMO.parent.mkdir(parents=True, exist_ok=True)
    _RESUMO.write_text(json.dumps({"ultimo": time.time()}), encoding="utf-8")


def _pagina_de_vendas(chave: str) -> str:
    import acabamento

    pid = acabamento.achar(chave)
    p = acabamento.PRODUTOS / (pid or "_") / "pagina_de_vendas.md"
    return ("📝 Página de vendas:\n\n" + html.escape(p.read_text(encoding="utf-8")))[:4000] if pid and p.exists() \
        else "página não encontrada"


def _decidir_produto(chave: str, aprovar: bool) -> str:
    import acabamento

    pid = acabamento.achar(chave)
    if not pid:
        return "produto não encontrado (talvez de antes de um reinício)"
    meta = acabamento.marcar(pid, "aprovado" if aprovar else "refazer")
    if aprovar:
        if (meta.get("idioma") or "pt") == "pt":
            try:
                import uiclap

                uiclap.kit_de_produto(pid)
                n = sum(1 for k in uiclap.kits() if k.get("status") == "pronto" and not k.get("teste"))
                return (f"✅ APROVADO: {meta['titulo']}\n📚 Livro físico pronto pro UICLAP ({n} na fila). "
                        "Quando puder: abra portal.uiclap.com no Chrome e clique no favorito 📚 Publicar Orbe.")
            except Exception as e:
                print("kit UICLAP falhou:", e, flush=True)
        return (f"✅ APROVADO: {meta['titulo']} ({acabamento.preco_fmt(meta)})\n"
                "Fica na fila 'pronto pra vender' — publica sozinho quando a loja estiver conectada.")
    return f"🔁 Descartado: {meta['titulo']}. O acabador faz outro a partir do próximo rascunho."


async def _produtos_lista() -> str:
    import acabamento

    metas = acabamento._metas()[-10:]
    if not metas:
        return "nenhum produto finalizado ainda"
    ic = {"aguardando_dono": "⏳", "aprovado": "✅", "refazer": "🔁"}
    return "📦 PRODUTOS\n" + "\n".join(
        f"{ic.get(m.get('status'), '•')} {html.escape(m['titulo'])} — {acabamento.preco_fmt(m)}, {m['paginas']} págs"
        for m in metas)


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


def prompt_missao(ideia: str) -> str:
    return (f"Estratégia aprovada pelo dono: \"{ideia}\". Produza o ARQUIVO que o cliente final vai "
            "COMPRAR dentro dessa estratégia — NÃO um guia sobre a estratégia, sobre vender online, "
            "Gumroad ou produtos digitais. Público/nicho: {tema}. Faça um pack em PDF realmente útil "
            "para esse público (checklists, planners, modelos, roteiros ou fichas), com título vendedor "
            "e TODO o conteúdo escrito. Em português. " + REGRAS_PRODUTO)


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
                "prompt": prompt_missao(str(it.get("ideia", ""))),

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
        alvo_chat = chat
        if data.startswith("sim_"):
            texto = _aprovar(int(data[4:]))
        elif data.startswith("nao_"):
            texto = _rejeitar(int(data[4:]))
        elif data.startswith("pok_") or data.startswith("prf_"):
            texto = _decidir_produto(data[4:], data.startswith("pok_"))
        elif data.startswith("fok_") or data.startswith("fno_"):
            texto = await _decidir_freela(data[4:], data.startswith("fok_"))
        elif data.startswith("pvd_"):
            texto = _pagina_de_vendas(data[4:])
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
        elif cmd.startswith("/produtos"):
            texto = await _produtos_lista()
        elif cmd.startswith("/vendas"):
            import vendas

            texto = html.escape(vendas.resumo_txt(time.time() - 86400))
        elif cmd.startswith("/status"):
            texto = await _status()
        elif cmd.startswith("/start"):
            texto = ("🤖 Orbe Autônomo na escuta!\n\n"
                     "/radar — ver ideias caçadas\n"
                     "/sim <nº> — aprovar ideia\n"
                     "/status — colônia\n\n"
                     "/produtos — produtos prontos\n"
                     "/vendas — vendas REAIS (dinheiro de verdade)\n\n"
                     f"Só mando 1 mensagem por dia ({HORA_RESUMO}h), e só se tiver produto aprovado pelo crítico.")
        else:
            return
    if texto:
        await _tg("sendMessage", chat_id=alvo_chat, text=texto, parse_mode="HTML")


def _chat_de(update: dict) -> str:
    m = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    return str((m.get("chat") or {}).get("id", ""))


async def _capturar_dono() -> bool:
    """Sem chat_id salvo: o 1º chat PRIVADO que falar com o bot vira o dono
    (grava em data/autopilot.json e confirma no Telegram)."""
    res = (await _tg("getUpdates", offset=_offset(), timeout=25)).get("result", [])
    for u in res:
        _offset_salvar(int(u.get("update_id", 0)) + 1)
        m = u.get("message") or {}
        if (m.get("chat") or {}).get("type") == "private":
            from autopilot import AUTOPILOT

            cid = str(m["chat"]["id"])
            AUTOPILOT.save(chat_id=cid)
            await _tg("sendMessage", chat_id=cid,
                      text="🔗 Orbe conectado a este chat! Avisos do batedor chegam aqui com ✅/❌.\n/radar /status")
            return True
    return False


async def _poller() -> None:
    while True:
        tok, chat = _cfg()
        if not tok:
            await asyncio.sleep(20)
            continue
        if not chat:
            if not await _capturar_dono():
                await asyncio.sleep(5)
            continue
        res = (await _tg("getUpdates", offset=_offset(), timeout=25)).get("result", [])
        for u in res:
            _offset_salvar(int(u.get("update_id", 0)) + 1)
            if _chat_de(u) != chat:   # bot é público: só o dono manda
                continue
            try:
                await _tratar(u)
            except Exception:
                pass
        await asyncio.sleep(2 if res else 5)


def iniciar() -> None:
    asyncio.get_running_loop().create_task(_poller())
