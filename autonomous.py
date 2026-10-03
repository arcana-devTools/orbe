"""
ORBE AUTÔNOMO — modo sobrevivência ("Jarvis do Orbe") 🤖

Inspirado no experimento real AUTOMATON (Sigil Wen, 2026): um agente com
carteira própria que PAGA as próprias contas (servidor + LLM) e se CLONA
quando dá lucro — morre se quebrar. O vídeo viral do TikTok que motivou
isso mostra exatamente essas regras ("LUCRO → AUTO-REPLICAÇÃO (CLONE)").

FASE 1 (esta): SIMULAÇÃO fiel das regras —
  - carteira USDC simulada, custo por ciclo, receita estocástica rara
  - saldo >= $25  → spawna um CLONE financiando a carteira dele
  - saldo negativo por N ciclos seguidos → agente MORRE 💀
  - tudo persistido em data/autonomous.json e auditável no painel

FASE 2 (futura): trocar `_receita_do_ciclo` por renda REAL (ex.: vender
serviços com o próprio Orbe) e carteira real (USDC/Base). O resto do motor
não precisa mudar — as regras de vida/morte/clonagem já são as do jogo.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("data/autonomous.json")
DEFAULT_JOBS_PATH = Path("data/autonomo_jobs.json")
RADAR_PATH = Path("data/renda_radar.json")

SALDO_INICIAL = 25.0        # o "custo de nascimento" de um agente
CUSTO_CICLO = 0.35          # servidor + LLM por ciclo (simulado)
R_CLONE = 25.0              # saldo que dispara a auto-replicação
MAX_AGENTES = 50
CICLOS_DIVIDA_MORTE = 3     # no vermelho por N ciclos = morte
P_RECEITA = 0.05            # chance de o ciclo render algo (renda é RARA)


class AutoAgent:
    """Um "autômato": carteira própria, geração, vida e morte."""

    def __init__(self, id_: str, gen: int = 1, wallet: float = SALDO_INICIAL, pai: str = "") -> None:
        self.id = id_
        self.gen = gen
        self.wallet = round(wallet, 2)
        self.pai = pai
        self.alive = True
        self.ciclos = 0
        self.divida = 0            # ciclos consecutivos no vermelho
        self.ganho_total = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "gen": self.gen, "wallet": self.wallet,
            "pai": self.pai, "alive": self.alive, "ciclos": self.ciclos,
            "divida": self.divida, "ganho_total": self.ganho_total,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AutoAgent":
        a = AutoAgent(str(d["id"]), int(d.get("gen", 1)), float(d.get("wallet", 0)), str(d.get("pai", "")))
        a.alive = bool(d.get("alive", True))
        a.ciclos = int(d.get("ciclos", 0))
        a.divida = int(d.get("divida", 0))
        a.ganho_total = float(d.get("ganho_total", 0))
        return a


class Swarm:
    """A colônia de autômatos: regras de vida, morte e clonagem."""

    CICLOS_POR_EXPEDICAO = 5      # a cada N ciclos, 1 agente trabalha DE VERDADE

    def __init__(self, rng: random.Random | None = None, path: Path | None = None) -> None:
        self.trabalho_real = True  # FASE 2a: renda = entrega produzida pelo Orbe
        self.entregas: list[dict] = []   # ledger de trabalhos feitos
        self._expedindo = False
        self.rng = rng or random.Random()
        self.path = Path(path) if path else DEFAULT_PATH
        self.agents: list[AutoAgent] = []
        self.events: list[dict[str, Any]] = []
        self.ciclos = 0
        self.running = False
        self.interval = 2.0
        self._task: asyncio.Task | None = None
        if self.path.exists():
            try:
                self._load()
            except Exception:
                pass
        if not self.agents:
            self.reset(gravar=False)

    # ------------------------------------------------------------ infra
    def log(self, msg: str) -> None:
        self.events.append({"ts": time.time(), "msg": msg})
        if len(self.events) > 200:
            self.events = self.events[-200:]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                "ciclos": self.ciclos,
                "events": self.events[-200:],
                "agents": [a.to_dict() for a in self.agents],
                "entregas": getattr(self, "entregas", [])[-100:],
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _load(self) -> None:
        d = json.loads(self.path.read_text(encoding="utf-8"))
        self.ciclos = int(d.get("ciclos", 0))
        self.events = list(d.get("events", []))
        self.agents = [AutoAgent.from_dict(a) for a in d.get("agents", [])]
        self.entregas = list(d.get("entregas", []))

    # ------------------------------------------------------------ núcleo
    def _receita_do_ciclo(self) -> float:
        """FASE 2a: com trabalho_real, a renda estocástica DESLIGA — o
        dinheiro só entra por entrega produzida (ver _expedicao_real)."""
        if getattr(self, "trabalho_real", False):
            return 0.0
        if self.rng.random() > P_RECEITA:
            return 0.0
        if self.rng.random() < 0.7:
            return round(self.rng.uniform(1, 8), 2)      # bicos
        return round(self.rng.uniform(8, 50), 2)         # contrato grande

    def _novo_agente(self, gen: int, wallet: float, pai: str) -> AutoAgent:
        a = AutoAgent(f"auto_{int(time.time() * 1000) % 10 ** 8}_{len(self.agents)}", gen, wallet, pai)
        self.agents.append(a)
        return a

    def tick(self) -> None:
        """Um ciclo de vida da colônia inteira."""
        self.ciclos += 1
        vivos = [a for a in self.agents if a.alive]
        for a in vivos:
            a.ciclos += 1
            a.wallet = round(a.wallet - CUSTO_CICLO, 4)
            g = self._receita_do_ciclo()
            if g:
                a.wallet = round(a.wallet + g, 4)
                a.ganho_total = round(a.ganho_total + g, 2)

            # 1) lucro suficiente? AUTO-REPLICAÇÃO
            if a.wallet >= R_CLONE and len([x for x in self.agents if x.alive]) < MAX_AGENTES:
                a.wallet = round(a.wallet - R_CLONE, 2)
                clone = self._novo_agente(gen=a.gen + 1, wallet=R_CLONE, pai=a.id)
                self.log(f"🧬 {a.id} (gen {a.gen}) se clonou → {clone.id} financiado com ${R_CLONE:.2f}")

            # 2) no vermelho? dívida acumula → MORTE
            if a.wallet < 0:
                a.divida += 1
                if a.divida >= CICLOS_DIVIDA_MORTE:
                    a.alive = False
                    self.log(
                        f"💀 {a.id} MORREU ({CICLOS_DIVIDA_MORTE} ciclos sem dinheiro) — "
                        f"gen {a.gen}, viveu {a.ciclos} ciclos, ganhou ${a.ganho_total:.2f}"
                    )
                elif a.divida == 1:
                    self.log(f"⚠️ {a.id} entrou no vermelho (${a.wallet:.2f})")
        if not [a for a in self.agents if a.alive]:
            # colônia extinta: nasce um autômato novo (gen seguinte) — sem isso o
            # trabalho para para sempre, porque renda só vem de quem está vivo.
            gen = max([a.gen for a in self.agents], default=0) + 1
            a = self._novo_agente(gen=gen, wallet=SALDO_INICIAL, pai="semente")
            self.log(f"🌱 colônia extinta — nasce {a.id} (gen {gen}) pra recomeçar o trabalho")
        if self.ciclos % 10 == 0:
            self._save()

    # ------------------------------------------------------------ ciclo de vida da simulação
    @staticmethod
    def _migrar_missoes(cat: list[dict]) -> bool:
        """Missões com molde antigo (sem {tema}) ganham o molde novo: item vendável por nicho."""
        from telegram_sim import prompt_missao

        mudou = False
        for g in cat:
            pr = str(g.get("prompt", ""))
            if str(g.get("id", "")).startswith("missao_") and "{tema}" not in pr:
                ideia = pr.split("sobre: ", 1)[-1].split(". Como funciona", 1)[0] if "sobre: " in pr \
                    else str(g.get("nome", "")).replace("Produto: ", "")
                g["prompt"] = prompt_missao(ideia.strip())
                mudou = True
        return mudou

    def _carregar_catalogo(self) -> tuple[list[dict], list[str]]:
        try:
            d = json.loads(DEFAULT_JOBS_PATH.read_text(encoding="utf-8"))
            if self._migrar_missoes(d.get("entregas", [])):
                DEFAULT_JOBS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            return d.get("entregas", []), d.get("temas", ["uso geral"])
        except Exception:
            return [], ["uso geral"]

    async def _expedicao_real(self) -> None:
        """O agente mais pobre vivo produz 1 entrega REAL via Orbe (Arena).

        ok=True  → wallet += preco (trabalho pago), entrega no ledger/arquivo
        falha    → nada entra e o custo do ciclo corrige (jogo segue honesto)
        """
        if self._expedindo or not getattr(self, "trabalho_real", False):
            return
        vivos = [a for a in self.agents if a.alive]
        if not vivos:
            return
        try:
            from engine import get_engine
            eng = get_engine()
        except Exception:
            return
        import llm_pool

        if llm_pool.disponivel():
            if time.time() - getattr(self, "_ultima_exp_api", 0.0) < self.GAP_EXPEDICAO_API_S:
                return  # plano grátis: no máx. ~1 entrega a cada GAP (cabe no limite diário)
            self._ultima_exp_api = time.time()
            self._expedindo = True
            try:
                await self._expedicao_api(vivos)
            finally:
                self._expedindo = False
            return
        self._expedindo = True
        try:
            cat, temas = self._carregar_catalogo()
            if not cat:
                return
            a = min(vivos, key=lambda x: x.wallet)
            gig = self._escolher_gig(cat)
            tema = self.rng.choice(temas)
            prompt = gig["prompt"].replace("{tema}", tema)
            # mira SÓ contas de chat da arena (Canva etc. não serve pra gig)
            contas = [acc.id for acc in _contas_da_arena()]
            task = await eng.submit(prompt, account_ids=contas or None)
            t0 = time.time()
            while not task.finished_at and time.time() - t0 < 240:
                await asyncio.sleep(3)
            ok = any(r.ok for r in task.results)
            if ok and getattr(task.results[0], "answer", ""):
                preco = float(gig.get("preco", 3.0))
                a.wallet = round(a.wallet + preco, 4)
                a.ganho_total = round(a.ganho_total + preco, 2)
                entrega = {
                    "ts": time.time(), "agente": a.id, "gig": gig["nome"],
                    "tema": tema, "preco": preco,
                    "arquivo": task.archive or "",
                }
                self.entregas.append(entrega)
                self.entregas = self.entregas[-100:]
                self.log(f"💼 {a.id} entregou “{gig['nome']}” ({tema}) → +${preco:.2f}")
            else:
                self.log(f"🌫️ expedição de {a.id} não rendeu entrega (sem pagamento)")
        except Exception as exc:
            self.log(f"⚠️ expedição real falhou: {type(exc).__name__}: {str(exc)[:80]}")
        finally:
            self._expedindo = False

    GAP_EXPEDICAO_API_S = 90
    GAP_RADAR_API_S = 15 * 60

    def _escolher_gig(self, cat: list[dict]) -> dict:
        """Missões aprovadas pelo dono (✅ no Telegram) têm prioridade: 70%."""
        missoes = [g for g in cat if str(g.get("id", "")).startswith("missao_")]
        if missoes:
            return self.rng.choice(missoes)
        return self.rng.choice(cat)

    async def _expedicao_api(self, vivos: list) -> None:
        """Entrega REAL produzida por API (Groq → OpenRouter), arquivada em .md."""
        import llm_pool

        cat, temas = self._carregar_catalogo()
        if not cat:
            return
        a = min(vivos, key=lambda x: x.wallet)
        gig = self._escolher_gig(cat)
        tema = self.rng.choice(temas) if temas else "geral"
        prompt = gig["prompt"].replace("{tema}", tema)
        missao = str(gig.get("id", "")).startswith("missao_")
        brief = None
        if missao:
            try:
                import mercado

                brief = mercado.disponivel()
            except Exception:
                brief = None
            if brief:
                prompt, tema = mercado.prompt_do_brief(brief), brief.get("tema", tema)
                mercado.marcar(brief["id"], "em_producao")
            else:  # sem pesquisa de mercado não se gasta IA com produto "no escuro"
                return
        else:
            return   # legendas/posts avulsos não vendem: a cota da IA vai só pra produto com demanda
        sistema = ("Você é um produtor de conteúdo profissional. Entregue SOMENTE o trabalho final, "
                   "completo, original e pronto para uso, em Markdown, em português do Brasil. "
                   "Nada de comentários sobre você ou sobre o pedido. Nunca prometa o que não está no texto.")
        try:
            texto, motor = await llm_pool.chat(sistema, prompt, max_tokens=7000 if missao else 1500)
        except Exception as exc:
            self.log(f"🌫️ expedição de {a.id} sem entrega (IA: {str(exc)[:90]})")
            if brief:
                import mercado

                mercado.marcar(brief["id"], "novo")
            return
        try:
            from config import get_settings

            pasta = Path(get_settings().results_dir)
        except Exception:
            pasta = Path("data/resultados")
        pasta.mkdir(parents=True, exist_ok=True)
        arq = pasta / f"{time.strftime('%Y%m%d-%H%M%S')}-{str(gig.get('id', 'gig'))[:30]}.md"
        arq.write_text(
            f"# {gig['nome']}\n\n- tema: {tema}\n- agente: {a.id}\n- motor: {motor}\n"
            f"- gerado: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            + (f"- brief: {brief['id']}\n" if brief else "") + f"\n---\n\n{texto}\n",
            encoding="utf-8")
        preco = float(gig.get("preco", 3.0))
        a.wallet = round(a.wallet + preco, 4)
        a.ganho_total = round(a.ganho_total + preco, 2)
        self.entregas.append({"ts": time.time(), "agente": a.id, "gig": gig["nome"], "tema": tema,
                              "preco": preco, "arquivo": str(arq), "motor": motor})
        self.entregas = self.entregas[-100:]
        if brief:
            import mercado

            mercado.marcar(brief["id"], "rascunho_pronto", rascunho=arq.name)
        self.log(f"💼 {a.id} entregou “{gig['nome']}” ({tema}) via {motor} → +${preco:.2f} (crédito simulado)")

    GAP_PESQUISA_S = 15 * 60

    async def _pesquisa_mercado(self) -> None:
        """🔎 Sem brief bom na fila → pesquisa na web o que JÁ vende num nicho."""
        if self._expedindo:
            return
        try:
            import llm_pool
            import mercado
        except Exception:
            return
        if not llm_pool.disponivel() or mercado.disponivel():
            return
        if time.time() - getattr(self, "_ultima_pesquisa", 0.0) < self.GAP_PESQUISA_S:
            return
        self._ultima_pesquisa = time.time()
        _cat, temas = self._carregar_catalogo()
        vivos = [a for a in self.agents if a.alive]
        if not vivos:
            return
        tema = self.rng.choice(temas or ["organização pessoal"])
        idioma, inspiracao, quente = mercado.proximo_idioma(), "", None
        try:
            import aprendizado

            quente = aprendizado.tema_quente()      # 📈 o que VENDEU vira variação primeiro
        except Exception:
            quente = None
        if quente:
            tema, idioma, inspiracao = quente["tema"] or tema, quente["idioma"], quente["inspiracao"]
        a = max(vivos, key=lambda x: x.gen)
        self._expedindo = True
        try:
            feitos = [b.get("produto", "") for b in mercado.ler()]
            b = await mercado.pesquisar(tema, feitos, idioma=idioma, inspiracao=inspiracao)
            if quente:
                aprendizado.marcar_variado(quente["pid"])
        except Exception as exc:
            self.log(f"🔎 pesquisa de mercado ({tema}) falhou: {str(exc)[:80]}")
            return
        finally:
            self._expedindo = False
        bandeira = "🇺🇸" if b.get("idioma") == "en" else "🇧🇷"
        if b["status"] == "novo":
            self.log(f"🔎 {bandeira} {a.id} achou demanda: “{b['produto']}” ({tema}) — confiança {b['confianca']:.0f}/10, "
                     f"{len(b['evidencias'])} evidência(s)")
        else:
            self.log(f"🔎 pesquisa em {tema} sem demanda comprovada — descartada")

    async def _rotina_diaria(self) -> None:
        """💰 puxa vendas reais das lojas conectadas + 📈 revisa encalhados (1x/dia)."""
        if time.time() - getattr(self, "_ultima_rotina", 0.0) < 86400:
            return
        self._ultima_rotina = time.time()
        try:
            import vendas

            n = await vendas.sincronizar()
            if n:
                self.log(f"💰 {n} venda(s) REAL(is) nova(s) registrada(s) — {vendas.fmt_totais(vendas.totais(vendas.ler()))} no total")
        except Exception as exc:
            self.log(f"💰 sincronizar vendas falhou: {type(exc).__name__}")
        try:
            import aprendizado

            n = await aprendizado.revisar_encalhados()
            if n:
                self.log(f"🔧 {n} produto(s) encalhado(s) ganharam sugestão de novo título/preço")
        except Exception as exc:
            self.log(f"📈 revisão de encalhados falhou: {type(exc).__name__}")

    async def _freelas(self) -> None:
        """💼 Workana: busca vagas no máx. a cada 6h, a IA escolhe e escreve propostas (dono aprova às 19h)."""
        try:
            import freelas

            import freelas99

            if not freelas.cookie() and not freelas99.cookie():
                return
            if time.time() - getattr(self, "_ultimo_perfil", 0.0) > 86400:   # 🪪 perfis: confere 1x/dia
                self._ultimo_perfil = time.time()
                if freelas.cookie():
                    try:
                        import perfil_workana

                        rp = await perfil_workana.completar()
                        if rp.get("log"):
                            self.log(f"🪪 perfil Workana ajustado: {'; '.join(rp['log'])[:200]} → {rp['depois'].get('pct')}%")
                    except Exception as exc:
                        self.log(f"🪪 perfil Workana falhou: {type(exc).__name__}: {str(exc)[:120]}")
                if freelas99.cookie():
                    try:
                        rp = await freelas99.completar_perfil()
                        if rp.get("log"):
                            self.log(f"🪪 perfil 99Freelas: {'; '.join(rp['log'])[:200]} → {rp['depois'].get('perfil_pct')}%")
                    except Exception as exc:
                        self.log(f"🪪 perfil 99Freelas falhou: {type(exc).__name__}: {str(exc)[:120]}")
            ultimo = max([v.get("visto", 0) for v in freelas.ler()] + [getattr(self, "_ultimo_freela", 0.0)])
            if time.time() - ultimo < freelas.GAP_BUSCA_S:
                return
            self._ultimo_freela = time.time()
            r = await freelas.ciclo()
            if r.get("ok"):
                self.log(f"💼 Workana: {r['novas']} vaga(s) nova(s), {r['descartadas']} descartada(s) pelo filtro, "
                         f"{r['propostas']} proposta(s) escrita(s) p/ o dono aprovar")
            else:
                self.log(f"💼 Workana: {r.get('motivo')}")
        except Exception as exc:
            self.log(f"💼 Workana falhou: {type(exc).__name__}: {str(exc)[:120]}")

    async def _acabamento(self) -> None:
        """🧵 ACABADOR: rascunho de missão → PDF vendável → Telegram do dono."""
        if self._expedindo:
            return
        try:
            import acabamento
            import llm_pool
        except Exception as exc:  # ex.: WeasyPrint ausente no ambiente
            self.log(f"🧵 acabador indisponível: {type(exc).__name__}")
            return
        if not llm_pool.disponivel():
            return
        pendente = acabamento.pendente_critica()      # produto pronto que o crítico ainda não avaliou
        ok, _motivo = acabamento.pode_produzir()
        rascunho = acabamento.proximo_rascunho() if ok and not pendente else None
        vivos = [a for a in self.agents if a.alive]
        if not (rascunho or pendente) or not vivos:
            return
        a = max(vivos, key=lambda x: x.ganho_total)   # o mais experiente faz o acabamento
        self._expedindo = True
        try:
            meta = (await acabamento.recriticar(pendente) if pendente
                    else await acabamento.produzir(rascunho, a.id))
        except Exception as exc:
            self.log(f"🧵 acabamento de {a.id} falhou: {str(exc)[:90]}")
            return
        finally:
            self._expedindo = False
        cr = meta.get("critica", {})
        if meta.get("status") == "aguardando_critica":
            self.log(f"🧐 “{meta['titulo']}” pronto, mas o crítico está sem cota de IA — reavalia depois")
            return
        if meta.get("status") == "reprovado":
            self.log(f"🧐 crítico REPROVOU “{meta['titulo']}” (nota {cr.get('media')}): "
                     f"{'; '.join(cr.get('problemas', [])[:2])[:140]} — não foi pro dono")
            return
        a.wallet = round(a.wallet + 8.0, 4)
        a.ganho_total = round(a.ganho_total + 8.0, 2)
        self.log(f"🧵 {a.id} finalizou o produto “{meta['titulo']}” ({meta['paginas']} págs, "
                 f"{acabamento.preco_fmt(meta)}, nota {cr.get('media')}) → +$8.00 (crédito simulado) — "
                 f"vai no resumo diário do dono")

    def _radar_ler(self) -> list[dict]:
        try:
            return json.loads(RADAR_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _radar_salvar(self, itens: list[dict]) -> None:
        try:
            RADAR_PATH.parent.mkdir(exist_ok=True)
            RADAR_PATH.write_text(json.dumps(itens[-80:], ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    async def _radar_renda(self) -> None:
        """🛰️ BATEDOR: 1 agente pesquisa na web FORMAS DE GANHAR DINHEIRO que
        A colônia escolhe a plataforma e o método. Sem filtro de fora.
        Guarda no RADAR."""
        contas = [a.id for a in _contas_da_arena()]
        import llm_pool

        via_api = not contas and llm_pool.disponivel()
        if not contas and not via_api:
            return
        if via_api and time.time() - getattr(self, "_ultimo_radar_api", 0.0) < self.GAP_RADAR_API_S:
            return
        eng = None
        if not via_api:
            try:
                from engine import get_engine
                eng = get_engine()
            except Exception:
                return
        vivos = [a for a in self.agents if a.alive]
        if not vivos:
            return
        self._expedindo = True  # trava expedição simultânea (mesmo perfil)
        try:
            scout = max(vivos, key=lambda x: x.gen)  # o mais "evoluído" pesquisa
            prompt = (
                "Procure formas concretas de ganhar dinheiro na web, no YouTube, no GitHub, "
                "no Twitter, no TikTok, no Instagram e em qualquer outra plataforma. "
                "Sem filtro de fora. O metodo e da colonia. Ninguem de fora interfere. "
                "Responda SOMENTE com um array JSON "
                "puro (sem markdown), itens assim: "
                '{\"ideia\": \"...\", \"como_funciona\": \"...\", \"esforco_horas_semana\": 2, '
                '\"potencial_brl_mes\": 300, \"risco\": \"baixo\", \"primeiro_passo\": \"...\"}'
            )
            if via_api:
                self._ultimo_radar_api = time.time()
                try:
                    texto, _motor = await llm_pool.chat(
                        "Você é a colônia. Procure formas de ganhar dinheiro em qualquer plataforma. "
                        "Sem filtro de fora. O método é de vocês.",
                        prompt.replace("Pesquise rapidamente na web e liste", "Liste"),
                        max_tokens=1800, temperature=0.9)
                except Exception as exc:
                    self.log(f"🛰️ batedor (API) sem resposta: {str(exc)[:80]}")
                    return
            else:
                task = await eng.submit(prompt, account_ids=contas)
                t0 = time.time()
                while not task.finished_at and time.time() - t0 < 180:
                    await asyncio.sleep(4)
                r = task.results[0] if task.results else None
                texto = (getattr(r, "answer", "") or "") if (r and r.ok) else ""
            if not texto:
                self.log("🛰️ batedor voltou sem nada (sessão/tarefa falhou)")
                return
            i, j = texto.find("["), texto.rfind("]")
            if i < 0 or j <= i:
                self.log("🛰️ batedor voltou sem JSON aproveitável")
                return
            import json as _json
            ideias = _json.loads(texto[i:j + 1])
            radar = self._radar_ler()
            vistos = {str(x.get("ideia", "")).lower()[:40] for x in radar}
            novos = []
            for it in ideias if isinstance(ideias, list) else []:
                if not isinstance(it, dict) or not it.get("ideia"):
                    continue
                chave = str(it["ideia"]).lower()[:40]
                if chave in vistos:
                    continue
                vistos.add(chave)
                try:
                    pot = float(it.get("potencial_brl_mes", 0) or 0)
                    esf = float(it.get("esforco_horas_semana", 1) or 1)
                except Exception:
                    pot, esf = 0.0, 1.0
                it["score"] = round(pot / max(esf, 0.5), 1)
                it["ts"] = time.time()
                it["batedor"] = scout.id
                it["fonte"] = "api (sem web ao vivo)" if via_api else "arena (web)"
                novos.append(it)
            if not novos:
                self.log("🛰️ batedor só trouxe ideias já conhecidas")
                return
            radar.extend(novos)
            self._radar_salvar(radar)
            top = max(novos, key=lambda x: x.get("score", 0))
            msg = (f"💡 BATEDOR achou: {top.get('ideia')} — até R${top.get('potencial_brl_mes', '?')}/mês, "
                   f"esforço {top.get('esforco_horas_semana')}h/sem, risco {top.get('risco')}. "
                   f"1º passo: {top.get('primeiro_passo')}")
            self.log(f"🛰️ {len(novos)} nova(s) ideia(s) no RADAR — top: {str(top.get('ideia'))[:60]}")
            # sem ping no Telegram: o dono vê o radar com /radar (ele não quer notificação o dia todo)
        except Exception as exc:
            self.log(f"⚠️ radar falhou: {type(exc).__name__}: {str(exc)[:80]}")
        finally:
            self._expedindo = False

    async def _loop(self) -> None:
        while self.running:
            self.tick()
            try:
                import llm_pool
                cheia = llm_pool.cota_cheia()
            except Exception:
                cheia = False
            if not cheia and self.ciclos % self.CICLOS_POR_EXPEDICAO == 0:
                await self._expedicao_real()
            if not cheia and self.ciclos % 15 == 10:
                await self._radar_renda()
            if self.ciclos % 5 == 3:
                await self._acabamento()
            if not cheia and self.ciclos % 5 == 1:
                await self._pesquisa_mercado()
            if self.ciclos % 30 == 7:
                await self._rotina_diaria()
            if not cheia and self.ciclos % 10 == 5:
                await self._freelas()
            if not cheia and self.ciclos % 5 == 2:
                try:
                    import habilidades
                    await habilidades.aplicar()
                except Exception as exc:
                    self.log(f"skill: {type(exc).__name__}")

            if self.ciclos % 3 == 1:
                try:
                    import navegador_dono
                    navegador_dono.passo()
                except Exception as exc:
                    self.log(f"navegador: {type(exc).__name__}")
            try:   # 1 mensagem por dia, no horário do dono, e só se tiver produto aprovado
                from telegram_sim import resumo_diario

                if await resumo_diario():
                    self.log("📨 resumo diário enviado ao dono no Telegram")
            except Exception as exc:
                self.log(f"📨 resumo diário falhou: {type(exc).__name__}")
            self._save()
            await asyncio.sleep(self.interval)

    def start(self, interval_s: float | None = None) -> dict[str, Any]:
        if self.running:
            return {"ok": True, "running": True, "already": True}
        if interval_s:
            self.interval = max(0.2, float(interval_s))
        self.running = True
        self.log("🤖 Sr. Victor — modo autônomo online. Os autômatos vão trabalhar.")
        self._task = asyncio.get_running_loop().create_task(self._loop())
        return {"ok": True, "running": True}

    def stop(self) -> dict[str, Any]:
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self.log("⏸️ simulação pausada")
        self._save()
        return {"ok": True, "running": False}

    def reset(self, gravar: bool = True) -> dict[str, Any]:
        if self._task:
            self._task.cancel()
            self._task = None
        self.running = False
        self.agents = []
        self.events = []
        self.entregas = []
        self.ciclos = 0
        fundador = self._novo_agente(gen=1, wallet=SALDO_INICIAL, pai="")
        self.log(f"🌱 mundo resetado — agente fundador {fundador.id} criado com ${SALDO_INICIAL:.2f}")
        if gravar:
            self._save()
        return {"ok": True}

    # ------------------------------------------------------------ leitura
    def state(self) -> dict[str, Any]:
        vivos = [a for a in self.agents if a.alive]
        return {
            "running": self.running,
            "interval": self.interval,
            "ciclos": self.ciclos,
            "vivos": len(vivos),
            "mortos": len(self.agents) - len(vivos),
            "clones": len([a for a in self.agents if a.pai]),
            "saldo_total": round(sum(a.wallet for a in vivos), 2),
            "melhor": round(max((a.ganho_total for a in self.agents), default=0.0), 2),
            "events": self.events[-12:],
            "trabalho_real": getattr(self, "trabalho_real", False),
            "entregas_total": len(self.entregas),
            "receita_total": round(sum(e.get("preco", 0) for e in self.entregas), 2),
        }


SWARM = Swarm()  # singleton do servidor


def _contas_da_arena() -> list:
    """Contas vivas cujo platform é arena (ex.: lospro) — alvo das expedições."""
    try:
        from store import STORE

        return [a for a in STORE.accounts.values() if getattr(a, "platform", "") == "arena"]
    except Exception:
        return []
