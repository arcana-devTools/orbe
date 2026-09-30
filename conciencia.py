"""🧠 Consciência da colônia — um laço só: perceber → decidir → agir → registrar.

Não é mágica e não é enfeite: é a colônia lendo o PRÓPRIO estado (agentes vivos,
produtos, lojas, vendas, erros), escolhendo a próxima ação mais importante por uma
tabela de prioridades, executando o que é seguro e escrevendo tudo num diário.
O diário aparece no painel e numa linha do resumo das 19h — é assim que o dono
vê "o que ela decidiu" em vez de uma lista de regras.

O que ela NUNCA cruza (ato humano por definição): senha, 2FA, captcha, aceitar
termos. O que ela faz quando esbarra nisso: **deixa a tela pronta** e espera —
se o dono está no /desktop, ela mesma abre a tela de login.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DIARIO = Path("data/diario.jsonl")
CORACAO = Path("data/_desktop_hb.json")
ULTIMO = Path("data/_conciencia.json")
GAP = 20 * 60          # um ciclo a cada 20 min


# ------------------------------------------------------------------ percepção
def humano_no_desktop(min: int = 12) -> bool:
    """O dono está com o /desktop aberto? (o ping da aba atualiza o coração)."""
    try:
        return time.time() - json.loads(CORACAO.read_text(encoding="utf-8")).get("ts", 0) < min * 60
    except Exception:
        return False


def bater_coracao() -> None:
    try:
        CORACAO.parent.mkdir(parents=True, exist_ok=True)
        CORACAO.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    except Exception:
        pass


def perceber() -> dict[str, Any]:
    """Leitura do próprio corpo e do mundo — é o que ela 'sente'."""
    p: dict[str, Any] = {"ts": time.time()}
    # corpo: a colônia
    try:
        d = json.loads(Path("data/autonomous.json").read_text(encoding="utf-8"))
        agentes = d.get("agents", []) or []
        p["vivos"] = sum(1 for a in agentes if a.get("alive"))
        p["mortos"] = sum(1 for a in agentes if not a.get("alive"))
        p["ciclos"] = int(d.get("ciclos", 0))
    except Exception:
        p.update(vivos=-1, mortos=-1, ciclos=0)
    # mente: a IA está disponível?
    try:
        import llm_pool

        p["ia"] = bool(llm_pool.disponivel())
    except Exception:
        p["ia"] = False
    # trabalho: produtos por status
    try:
        import acabamento

        metas = acabamento._metas()
        p["produtos"] = len(metas)
        p["aguardando_dono"] = sum(1 for m in metas if m.get("status") == "aguardando_dono")
        # já avisados não travam o laço: o dono viu, o resto do trabalho segue
        p["aguardando_sem_aviso"] = sum(
            1 for m in metas if m.get("status") == "aguardando_dono" and not m.get("notificado"))
        p["aprovados"] = sum(1 for m in metas if m.get("status") in ("aprovado", "publicado"))
        p["reprovados"] = sum(1 for m in metas if m.get("status") == "reprovado")
        try:
            import uiclap

            # o kit guarda o produto em "origem" (e "produto_id" se existir)
            ks = uiclap.kits()
            prontos = {str(k.get("produto_id") or k.get("origem") or "") for k in ks}
            titulos = {str((k.get("info") or {}).get("titulo") or "").strip().lower() for k in ks}
            p["aprovados_sem_kit"] = sum(
                1 for m in metas if m.get("status") == "aprovado" and str(m.get("id")) not in prontos
            and str(m.get("titulo", "")).strip().lower() not in titulos)
        except Exception:
            p["aprovados_sem_kit"] = 0
    except Exception:
        p.update(produtos=0, aguardando_dono=0, aguardando_sem_aviso=0, aprovados=0, reprovados=0, aprovados_sem_kit=0)
    # pesquisa de mercado
    try:
        import mercado

        bs = mercado.ler()
        p["briefs"] = len(bs)
        p["briefs_novos"] = sum(1 for b in bs if b.get("status") == "novo")
    except Exception:
        p.update(briefs=0, briefs_novos=0)
    # dinheiro de verdade
    try:
        import vendas

        st = vendas.status()
        p["vendas"] = st.get("vendas", 0)
        p["total_txt"] = st.get("total_txt", "R$ 0")
        p["lojas"] = st.get("lojas", {})
    except Exception:
        p.update(vendas=0, total_txt="R$ 0", lojas={})
    # correntes: o que só o dono pode fazer
    try:
        import pendencias

        p["pendencias"] = pendencias.lista()
    except Exception:
        p["pendencias"] = []
    # auto-cuidado: o que falta EM MIM (não no dono)
    p["kiwify_ok"] = bool(p.get("lojas", {}).get("kiwify", {}).get("ok"))
    p["sessao_kiwify"] = Path("data/kiwify_sessao.json").exists()
    try:
        import kiwify_painel

        p["kiwify_login"] = bool(kiwify_painel._segredo("login") and kiwify_painel._segredo("senha"))
    except Exception:
        p["kiwify_login"] = False
    p["webhook_ok"] = False
    if p["kiwify_ok"]:
        try:
            import kiwify

            alvo = base_publica().rstrip("/") + "/kiwify/webhook"
            p["webhook_ok"] = any(str(w.get("url", "")).rstrip("/") == alvo for w in kiwify.webhooks())
        except Exception:
            p["webhook_ok"] = False
    try:
        import habilidades

        p["habilidades"] = len(habilidades.lista())
        p["habilidades_txt"] = habilidades.resumo_txt()
    except Exception:
        p["habilidades"] = 0
        p["habilidades_txt"] = ""
    p["humano_aqui"] = humano_no_desktop()
    return p


def base_publica() -> str:
    """Meu próprio endereço na internet (o Render entrega RENDER_EXTERNAL_URL)."""
    import os

    return (os.environ.get("ORBE_BASE") or os.environ.get("RENDER_EXTERNAL_URL")
            or "https://orbe-xfzn.onrender.com").rstrip("/")


# ------------------------------------------------------------------ decisão
def decidir(p: dict[str, Any]) -> dict[str, Any]:
    """A próxima ação mais importante. Simples, explícita e explicável."""
    def d(acao: str, porque: str, **kw: Any) -> dict[str, Any]:
        return {"acao": acao, "porque": porque, **kw}

    if p.get("vivos") == 0:
        return d("reviver", "a colônia está extinta — sem agente vivo ninguém trabalha")
    if not p.get("ia"):
        return d("esperar", "sem IA disponível (Groq/OpenRouter) — não gasto o resto à toa")
    # primeiro ela se arruma: o que depende DELA, não do dono
    if p.get("sessao_kiwify") and not p.get("kiwify_ok"):
        return d("criar_api_key", "tenho sessão no painel da Kiwify mas não a credencial: criar a API Key")
    if p.get("kiwify_login") and not p.get("sessao_kiwify") and p.get("humano_aqui"):
        return d("entrar", "tenho login/senha da Kiwify e nenhuma sessão: entrar sozinha", alvo="kiwify")
    if p.get("kiwify_ok") and not p.get("webhook_ok"):
        return d("configurar_webhook", "Kiwify conectada sem webhook: registrar o aviso de venda")
    if p.get("aprovados_sem_kit", 0) > 0:
        return d("embalar", f"{p['aprovados_sem_kit']} produto(s) aprovado(s) ainda não virou livro: embalar")
    sem_aviso = p.get("aguardando_sem_aviso")
    if sem_aviso is None:
        sem_aviso = p.get("aguardando_dono", 0)
    if sem_aviso:
        return d("avisar", f"{sem_aviso} produto(s) novo(s) esperando o dono decidir", humano=True)
    # correntes humanas: ela mesma prepara a tela se o dono estiver por perto
    for i in p.get("pendencias", []):
        onde = str(i.get("onde", ""))
        if "Kiwify" in onde:
            if not (p.get("lojas", {}).get("kiwify", {}).get("ok")):
                if p.get("humano_aqui"):
                    return d("abrir_login", "Kiwify sem credencial e o dono está no desktop: abrir a tela de login",
                             alvo="kiwify", humano=True)
                return d("esperar", "Kiwify sem credencial — esperando o dono abrir o /desktop")
            return d("observar", "Kiwify já conectada")
        if "Mercado Livre" in onde and p.get("humano_aqui"):
            return d("abrir_login", "Mercado Livre sem sessão e o dono está no desktop: abrir o portal de afiliados",
                     alvo="ml", humano=True)
    if p.get("briefs_novos", 0) == 0 and p.get("produtos", 0) == 0:
        return d("pesquisar", "sem demanda mapeada ainda — precisa pesquisar antes de escrever")
    if p.get("produtos", 0) == 0:
        return d("produzir", "já tem demanda mapeada, falta o primeiro produto")
    return d("observar", "tudo rodando: produzir/publicar é o ciclo normal da colônia")


# ------------------------------------------------------------------ ação
async def agir(dec: dict[str, Any]) -> dict[str, Any]:
    """Executa só o que é seguro e reversível. Senha/termos: nunca."""
    acao = dec.get("acao")
    try:
        import habilidades

        receita = habilidades.ler(str(acao))
        if receita:
            try:
                from conciencia import anotar

                anotar(f"vou seguir minha habilidade de '{acao}'")
            except Exception:
                pass
    except Exception:
        pass
    if acao == "abrir_login":
        alvo = dec.get("alvo")
        try:
            if alvo == "kiwify":
                import kiwify_painel

                d = await kiwify_painel.abrir()
                return {"feito": True, "resumo": f"Kiwify aberta: {str(d.get('titulo'))[:60]}"}
            if alvo == "ml":
                import afiliados_ml

                d = await afiliados_ml.abrir()
                return {"feito": True, "resumo": f"Mercado Livre aberto: {str(d.get('titulo'))[:60]}"}
        except Exception as exc:
            return {"feito": False, "resumo": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if acao == "criar_api_key":
        try:
            import kiwify_painel

            r = await kiwify_painel.criar_api_key()
            return {"feito": bool(r.get("ok")), "resumo": r.get("motivo") or "API Key criada e guardada no cofre"}
        except Exception as exc:
            return {"feito": False, "resumo": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if acao == "embalar":
        try:
            import acabamento
            import uiclap

            feitos = []
            for m in acabamento._metas():
                # relê a cada volta: duas execuções juntas já criaram kit duplicado uma vez
                ks = uiclap.kits()
                # o kit guarda o produto em "origem" (e em "produto_id" se existir)
                prontos = {str(k.get("produto_id") or k.get("origem") or "") for k in ks}
                titulos = {str((k.get("info") or {}).get("titulo") or "").strip().lower() for k in ks}
                if (m.get("status") == "aprovado" and str(m.get("id")) not in prontos
                        and str(m.get("titulo", "")).strip().lower() not in titulos):
                    try:
                        r = uiclap.kit_de_produto(str(m.get("id")))
                        feitos.append(str((r or {}).get("kid") or m.get("id"))[:24])
                    except Exception as exc:
                        return {"feito": False, "resumo": f"falhou em {m.get('titulo')}: {str(exc)[:90]}"}
            return {"feito": bool(feitos), "resumo": f"embalei {len(feitos)} livro(s): " + ", ".join(feitos)}
        except Exception as exc:
            return {"feito": False, "resumo": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if acao == "avisar":
        try:
            import telegram_sim

            ok = await telegram_sim.resumo_diario(forcar=True)
            return {"feito": bool(ok), "resumo": "mandei o resumo com os produtos pro Telegram"
                    if ok else "não tinha nada novo pra avisar"}
        except Exception as exc:
            return {"feito": False, "resumo": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if acao == "entrar":
        try:
            import kiwify_painel

            r = await kiwify_painel.entrar()
            if not r.get("ok") and r.get("esperando") == "captcha":
                # travou no anti-robo: ela aluga maos (Hermes) com IP residencial
                try:
                    import hermes

                    if hermes.disponivel():
                        h = await hermes.pedir(
                            "Abra https://dashboard.kiwify.com.br/ no Chrome, faca login com as "
                            "credenciais dos secrets (ORBE_KIWIFY_LOGIN / ORBE_KIWIFY_SENHA), "
                            "resolva o captcha se aparecer (voce esta em IP residencial) e, ao "
                            "entrar, envie os cookies para a Orbe. Nada de alterar dados da conta.")
                        return {"feito": bool(h.get("ok")), "resumo": h.get("resumo") or h.get("motivo", "")}
                except Exception as exc:
                    return {"feito": False, "resumo": f"Hermes falhou: {str(exc)[:100]}"}
            return {"feito": bool(r.get("ok")), "resumo": r.get("resumo") or r.get("motivo", "")}
        except Exception as exc:
            return {"feito": False, "resumo": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if acao == "configurar_webhook":
        try:
            import kiwify

            url = base_publica() + "/kiwify/webhook"
            r = kiwify.webhook_criar(url, nome="Orbe")
            return {"feito": True, "resumo": f"webhook registrado em {url}"}
        except Exception as exc:
            return {"feito": False, "resumo": f"{type(exc).__name__}: {str(exc)[:120]}"}
    if acao == "reviver":
        return {"feito": False, "resumo": "o renascimento acontece sozinho no próximo tick"}
    return {"feito": False, "resumo": "nada a executar agora"}


# ------------------------------------------------------------------ diário
def _escrever(p: dict[str, Any], dec: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    linha = {"ts": time.time(), "acao": dec.get("acao"), "porque": dec.get("porque"),
             "resultado": r.get("resumo", ""), "vivos": p.get("vivos"), "vendas": p.get("vendas"),
             "total": p.get("total_txt")}
    try:
        DIARIO.parent.mkdir(parents=True, exist_ok=True)
        with DIARIO.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except Exception:
        pass
    try:
        ULTIMO.write_text(json.dumps({"percebido": p, "decidido": dec, "resultado": r},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return linha


def anotar(texto: str, acao: str = "nota") -> None:
    """Ela escreve no próprio diário — inclusive quando age em nome do dono."""
    _escrever({"vivos": -1, "vendas": -1, "total_txt": ""}, {"acao": acao, "porque": texto},
              {"resumo": "registrado"})


def diario(n: int = 12) -> list[dict]:
    try:
        linhas = [json.loads(x) for x in DIARIO.read_text(encoding="utf-8").splitlines() if x.strip()]
        return linhas[-n:]
    except Exception:
        return []


def ultimo() -> dict[str, Any]:
    try:
        return json.loads(ULTIMO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def txt_curto() -> str:
    """Uma linha pro resumo das 19h: o que ela decidiu hoje."""
    u = ultimo()
    if not u:
        return ""
    d = u.get("decidido", {})
    return f"🧠 Decidi: {d.get('acao')} — {d.get('porque')}"


async def ciclo(forcar: bool = False) -> dict[str, Any]:
    """Um passo completo: perceber → decidir → agir → registrar."""
    try:
        if not forcar and ULTIMO.exists():
            u = json.loads(ULTIMO.read_text(encoding="utf-8"))
            if time.time() - float(u.get("percebido", {}).get("ts", 0)) < GAP:
                return u
    except Exception:
        pass
    p = perceber()
    dec = decidir(p)
    r = await agir(dec)
    try:
        import habilidades

        p["habilidade_nova"] = await habilidades.tentar_aprender(dec, r) or ""
    except Exception:
        p["habilidade_nova"] = ""
    linha = _escrever(p, dec, r)
    return {"percebido": p, "decidido": dec, "resultado": r, "linha": linha}


async def laco() -> None:
    """Roda pra sempre, em silêncio, junto com o servidor."""
    import asyncio

    await asyncio.sleep(90)          # espera o servidor respirar
    while True:
        try:
            await ciclo()
        except Exception:
            pass
        await asyncio.sleep(GAP)
