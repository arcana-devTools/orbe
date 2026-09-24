"""
ENGINE — executa o plano: abre o perfil certo, roda cada rota, salva resultado.

Concorrência: um semáforo global (MAX_CONCURRENT_TASKS) + uma trava por perfil,
porque quase nenhuma IA aceita duas sessões simultâneas na mesma conta.
"""
from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Any, Callable, Optional

from adapters import Registry, check_login, run_browser_step

# Google (set/2026): o campo de e-mail é type=text name=identifier
EMAIL_SEL = '#identifierId, input[name="identifier"]'
PASS_SEL = 'input[type="password"][name="Passwd"], input[type="password"]'

# 2FA (set/2026): o Google pode mostrar o campo do código direto OU uma tela de
# escolha do método ("Receber um código para fazer login" / "Tentar outro jeito").
# O código NUNCA vai por e-mail: chega por SMS no celular ou no app Autenticador.
# Prioridade do assistente: SMS > app Autenticador > prompt ("confirme no celular").
CHALLENGE_TXT = (
    "verificação em duas etapas",
    "2-step verification",
    "confirme que é você",
    "confirm it's you",
    "escolha como quer receber",
    "choose how to get",
    "receber um código",
    "get a code",
    "tentar outro jeito",
    "try another way",
)
METHOD_PREFS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sms", ("sms", "mensagem de texto", "text message", "text you a code")),
    ("totp", ("autenticador", "authenticator")),
    (
        "prompt",
        (
            "confirme que é você",
            "confirm it's you",
            "verifique o seu telefone",
            "google prompt",
            "your phone",
        ),
    ),
)
TRY_OTHER_SEL = (
    'button:has-text("Tentar outro jeito"), button:has-text("Try another way"), '
    '[role="link"]:has-text("Tentar outro jeito"), '
    '[role="link"]:has-text("Try another way")'
)
_CONTINUE_BTNS = (
    "Continuar",
    "Avançar",
    "Próxima",
    "Enviar",
    "Continue",
    "Next",
    "Send",
)


def is_challenge_text(t: str) -> bool:
    """O texto parece tela de desafio 2FA do Google?"""
    tl = (t or "").lower()
    return any(k in tl for k in CHALLENGE_TXT)


def method_for_text(t: str) -> str:
    """Dado o texto da tela/lista de métodos, qual escolher (sms > totp > prompt)."""
    tl = (t or "").lower()
    for name, words in METHOD_PREFS:
        if any(w in tl for w in words):
            return name
    return ""
from archive import archive_task
from browser import MANAGER
from config import get_settings
from events import BUS
from models import AccountStatus, StepResult, Task, TaskState
from orchestrator import Orchestrator
from secrets_vault import VAULT
from store import STORE

_s = get_settings()


class Engine:
    def __init__(self, registry: Registry, orchestrator: Orchestrator) -> None:
        self.registry = registry
        self.orch = orchestrator
        self.sem = asyncio.Semaphore(max(1, _s.max_concurrent_tasks))
        self.tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------- público
    async def submit(
        self,
        goal: str,
        prefer: Optional[list[str]] = None,
        account_ids: Optional[list[str]] = None,
        accounts_limit: int = 1,
        per_account: Optional[dict[str, str]] = None,
    ) -> Task:
        task = Task(goal=goal)
        STORE.add_task(task)
        await BUS.info(f"tarefa recebida: {goal}", "engine", task.id)
        coro = self._run(task, prefer, account_ids=account_ids, accounts_limit=accounts_limit, per_account=per_account)
        self.tasks[task.id] = asyncio.create_task(coro)
        return task

    async def cancel(self, task_id: str) -> bool:
        t = self.tasks.get(task_id)
        if not t or t.done():
            return False
        t.cancel()
        return True

    # ------------------------------------------------------------- interno
    async def _run(
        self,
        task: Task,
        prefer: Optional[list[str]],
        per_account: Optional[dict[str, str]] = None,
        account_ids: Optional[list[str]] = None,
        accounts_limit: int = 1,
    ) -> None:
        try:
            task.state = TaskState.PLANNING
            STORE.touch(task)
            routes = await self.orch.plan(task.goal, prefer, account_ids, accounts_limit, per_account=per_account)
            if not routes:
                task.state = TaskState.FAILED
                task.error = "nenhuma rota possível (configure uma conta ou instale o Chromium)"
                STORE.touch(task)
                await BUS.error(task.error, "engine", task.id)
                return

            task.routing = routes
            task.plan = [
                f"{i + 1}. {r['platform']} — {r['prompt'][:90]}" for i, r in enumerate(routes)
            ]
            await BUS.step(
                "plano: " + " | ".join(f"{r['platform']}" for r in routes), "engine", task.id
            )

            task.state = TaskState.RUNNING
            STORE.touch(task)

            results = await asyncio.gather(
                *[self._run_route(task, i, r) for i, r in enumerate(routes)],
                return_exceptions=True,
            )
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    r = routes[i]
                    task.results.append(
                        StepResult(
                            account_id=r.get("account_id", ""),
                            platform=r.get("platform", "?"),
                            prompt=r.get("prompt", ""),
                            ok=False,
                            error=f"{type(res).__name__}: {res}",
                        )
                    )

            task.state = TaskState.SYNTHESIZING
            STORE.touch(task)
            task.synthesis = await self.orch.synthesize(task.goal, task.results)
            task.state = TaskState.DONE
            task.finished_at = time.time()
            await self._archive(task)
            STORE.touch(task)
            await BUS.ok(
                f"concluído: {sum(1 for r in task.results if r.ok)}/{len(task.results)} IAs responderam",
                "engine",
                task.id,
            )
        except asyncio.CancelledError:
            task.state = TaskState.CANCELED
            task.finished_at = time.time()
            await self._archive(task)
            STORE.touch(task)
            await BUS.warn("tarefa cancelada", "engine", task.id)
        except Exception as exc:
            task.state = TaskState.FAILED
            task.error = f"{type(exc).__name__}: {exc}"
            task.finished_at = time.time()
            await self._archive(task)
            STORE.touch(task)
            await BUS.error(task.error, "engine", task.id)

    async def _archive(self, task: Task) -> None:
        try:
            md = archive_task(task, STORE.results_dir)
            task.archive = md
        except Exception as exc:  # arquivamento nunca derruba a tarefa
            task.archive = ""
            task.error = (task.error + f" | archive falhou: {exc}").strip(" |")
            return
        # destino extra escolhido no painel: GitHub ou Drive (sessão da conta)
        dest = STORE.archive_dest
        if dest in ("", "local"):
            return
        kind, _, acc_id = dest.partition(":")
        acc = STORE.accounts.get(acc_id)
        if not acc:
            task.archive += f" | {kind}: conta não encontrada"
            return
        from sync import sync_files

        files = [Path(md), Path(md).with_suffix(".json")]
        res = await sync_files(kind, files, acc.profile)
        if res.get("ok"):
            task.archive += f" | {kind}: ✔ {res.get('url','')}"
        else:
            task.archive += f" | {kind}: ✘ {res.get('error','?')}"
        STORE.touch(task)

    async def _run_route(self, task: Task, index: int, route: dict[str, str]) -> StepResult:
        async with self.sem:
            platform = route.get("platform", "")
            account_id = route.get("account_id", "")
            prompt = route.get("prompt", task.goal)
            instruction = route.get("instruction", "")

            account = STORE.accounts.get(account_id)
            profile = account.profile if account else f"{platform}-auto"
            spec = self.orch.ensure_adapter(platform)

            started = time.time()
            result = StepResult(
                account_id=account_id, platform=platform, prompt=prompt, instruction=instruction
            )

            async with MANAGER.lock_for(profile):
                await BUS.step(f"[{platform}] abrindo perfil '{profile}'", platform, task.id)
                try:
                    ctx = await MANAGER.context_for(profile)
                except Exception as exc:
                    result.error = f"falha ao abrir navegador: {exc}"
                    await BUS.error(result.error, platform, task.id)
                    task.results.append(result)
                    STORE.touch(task)
                    return result

                page = await ctx.new_page()
                shot = Path(_s.shots_dir) / f"{task.id}-{index}.png"
                shot.parent.mkdir(parents=True, exist_ok=True)
                try:
                    await BUS.step(f"[{platform}] enviando prompt…", platform, task.id)
                    creds = VAULT.get(account_id) if account_id else None
                    data = await run_browser_step(
                        page,
                        spec,
                        prompt,
                        instruction=instruction,
                        screenshot_path=str(shot),
                        creds=creds,
                    )
                except Exception as exc:
                    data = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "answer": ""}
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass

            result.answer = (data.get("answer") or "")[:20000]
            result.ok = bool(data.get("ok"))
            result.error = data.get("error", "") or ""
            result.url = data.get("url", "") or ""
            result.title = data.get("title", "") or ""
            result.elapsed_s = round(time.time() - started, 1)
            result.raw = {k: v for k, v in data.items() if k not in ("answer",)}
            if shot.exists():
                result.screenshot = f"/shots/{shot.name}"

            if data.get("logged_out") and account:
                account.status = AccountStatus.LOGGED_OUT
                account.last_check = time.time()
                STORE.save_accounts()
                await BUS.warn(
                    f"[{platform}] conta '{account.label}' deslogada — use o botão LOGIN",
                    platform,
                    task.id,
                )

            if result.ok:
                await BUS.ok(
                    f"[{platform}] respondeu ({len(result.answer)} chars em {result.elapsed_s}s)",
                    platform,
                    task.id,
                )
            else:
                await BUS.error(f"[{platform}] falhou: {result.error}", platform, task.id)

            task.results.append(result)
            STORE.touch(task)
            return result

    # ------------------------------------------------- conferência geral
    async def check_account(self, account_id: str) -> dict[str, Any]:
        """Abre o perfil da conta, visita a plataforma e diz se a sessão está viva.

        É o botão CONFERIR TODAS do painel: não executa tarefa nenhuma, só
        reporta ok / logged_out / unknown por conta (e já salva o status).
        """
        account = STORE.accounts.get(account_id)
        if not account:
            return {"account_id": account_id, "ok": False, "status": "unknown",
                    "error": "conta não encontrada"}
        spec = self.registry.get(account.platform) or self.orch.ensure_adapter(account.platform)
        target = spec.new_chat_url or spec.url
        if not target:
            return {"account_id": account_id, "ok": False, "status": "unknown",
                    "error": "plataforma sem url"}

        started = time.time()
        error = ""
        async with MANAGER.lock_for(account.profile):
            try:
                ctx = await MANAGER.context_for(account.profile)
                page = await ctx.new_page()
                try:
                    await page.goto(target, wait_until="domcontentloaded",
                                    timeout=_s.step_timeout_ms * 2)
                    await page.wait_for_timeout(1500)
                    state = await check_login(page, spec)
                finally:
                    await page.close()
            except Exception as exc:
                state = "unknown"
                error = f"{type(exc).__name__}: {exc}"

        account.status = (
            AccountStatus.OK if state == "ok"
            else AccountStatus.LOGGED_OUT if state == "logged_out"
            else AccountStatus.UNKNOWN
        )
        account.last_check = time.time()
        STORE.save_accounts()
        await BUS.info(
            f"[{account.platform}/{account.label}] conferida: {state}"
            + (f" ({error})" if error else ""),
            "check",
        )
        return {
            "account_id": account_id,
            "platform": account.platform,
            "label": account.label,
            "status": state,
            "ok": state == "ok",
            "error": error,
            "elapsed_s": round(time.time() - started, 1),
        }

    async def check_all_accounts(self) -> list[dict[str, Any]]:
        """Conferência em lote: no máximo 2 perfis de Chrome abertos ao mesmo tempo."""
        sem = asyncio.Semaphore(2)

        async def one(acc: Account) -> dict[str, Any]:
            async with sem:
                return await self.check_account(acc.id)

        accounts = sorted(STORE.accounts.values(), key=lambda a: (a.platform, a.label))
        return list(await asyncio.gather(*[one(a) for a in accounts]))

    async def calibrate_account(self, account_id: str) -> dict[str, Any]:
        """Lê a tela logada da conta e lista o que é clicável/digitável.

        Serve para calibrar seletores sem F12: se o clique de 'Agent' (ou a
        caixa de prompt) não pegar, esse inventário mostra os textos e ids
        reais da página para ajustar o YAML.
        """
        account = STORE.accounts.get(account_id)
        if not account:
            return {"ok": False, "error": "conta não encontrada", "elements": []}
        spec = self.registry.get(account.platform) or self.orch.ensure_adapter(account.platform)
        target = spec.new_chat_url or spec.url

        js = """() => {
          const out = [];
          const els = document.querySelectorAll(
            'button, a, [role="menuitem"], [role="option"], [role="menu"], ' +
            'textarea, input, [contenteditable="true"]');
          els.forEach((el) => {
            const r = el.getBoundingClientRect();
            if (r.width < 4 || r.height < 4) return;
            const style = getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none') return;
            const text = (el.innerText || el.placeholder ||
                          el.getAttribute('aria-label') || '').trim().slice(0, 70);
            if (!text) return;
            out.push({
              tag: el.tagName.toLowerCase(),
              text,
              id: el.id || '',
              role: el.getAttribute('role') || '',
              cls: String(el.className).slice(0, 90),
            });
          });
          return out.slice(0, 120);
        }"""

        async with MANAGER.lock_for(account.profile):
            try:
                ctx = await MANAGER.context_for(account.profile)
                page = await ctx.new_page()
                try:
                    await page.goto(target, wait_until="domcontentloaded",
                                    timeout=_s.step_timeout_ms * 2)
                    await page.wait_for_timeout(2000)
                    elements = await page.evaluate(js)
                    url = page.url
                finally:
                    await page.close()
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "elements": []}
        await BUS.info(f"[{account.platform}/{account.label}] calibragem: "
                       f"{len(elements)} elementos visíveis", "calibrate")
        return {"ok": True, "url": url, "elements": elements}

    # --------------------------------------------------- login assistido
    async def _challenge_screen(self, page: Any) -> bool:
        """Estamos numa tela de desafio 2FA do Google? (URL de challenge ou
        texto de verificação em 2 etapas — só dentro do fluxo de login)."""
        try:
            url = (page.url or "").lower()
        except Exception:
            return False
        if "challenge" in url:
            return True
        if "accounts.google.com" not in url or "signin" not in url:
            return False  # já saiu do fluxo de login (ex.: myaccount)
        return is_challenge_text(await self._page_txt(page, 600))

    async def _pick_challenge(self, page: Any) -> str:
        """Na tela de desafio do Google: expande 'Tentar outro jeito' (se
        houver) e escolhe o método mais prático (SMS > Autenticador >
        prompt no celular). Devolve o método escolhido ('' = nenhum)."""
        try:
            other = page.locator(TRY_OTHER_SEL)
            if await other.count():
                await other.first.click(timeout=4000)
                await page.wait_for_timeout(1800)
        except Exception:
            pass
            txt = await self._page_txt(page, 2000)
            method = method_for_text(txt)
            if not method:
                return ""
            word = next(
                (w for w in dict(METHOD_PREFS)[method] if w in txt.lower()), ""
            )
            if not word:
                return ""
            # clique PRECISO: pega o tile/opção do método (role certo), não um
            # contêiner gigante (get_by_text pode "clicar" o body e não fazer nada)
            clicked = False
            for sel in (
                f'div[data-challengetype]:has-text("{word}")',
                f'[role="link"]:has-text("{word}")',
                f'[role="button"]:has-text("{word}")',
                f'[role="radio"]:has-text("{word}")',
                f'label:has-text("{word}")',
                f'li:has-text("{word}")',
            ):
                try:
                    loc = page.locator(sel).first
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=4000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                try:
                    await page.get_by_text(word, exact=False).last.click(timeout=4000)
                except Exception:
                    return ""
            await page.wait_for_timeout(1200)
        for b in _CONTINUE_BTNS:
            try:
                await page.locator(f'button:has-text("{b}")').first.click(
                    timeout=1500
                )
                break
            except Exception:
                continue
        await page.wait_for_timeout(2500)
        return method

    async def _assist_shot(self, page: Any, account: Account) -> str:
        """Print embutido em base64 (o disco do Render é efêmero: /shots some
        no próximo restart — data URI chega sempre no painel)."""
        try:
            import base64

            blob = await page.screenshot(type="png")
            return "data:image/png;base64," + base64.b64encode(blob).decode("ascii")
        except Exception:
            return ""

    _ASSIST: dict[str, dict[str, Any]] = {}

    async def _page_txt(self, page: Any, n: int = 220) -> str:
        try:
            t = await page.evaluate("() => (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ')")
            return (t or "").strip()[:n]
        except Exception:
            return ""

    async def assisted_login(
        self, account_id: str, email: str, password: str, code: str = ""
    ) -> dict[str, Any]:
        """Login GUI do Google (vale p/ Arena, Gemini, Google): você só digita
        no PAINEL; o Orbe preenche o Chrome. Se pedir 2FA, devolve need_code e
        você manda o código pelo painel também.

        Estratégia: 1) loga o PERFIL no Google direto (accounts.google.com);
        2) se a plataforma é a Arena, abre a Arena e clica em "continuar com
        Google" — com o perfil já logado, o Google só mostra o seletor de conta
        (um clique no seu e-mail)."""
        account = STORE.accounts.get(account_id)
        if not account:
            return {"ok": False, "error": "conta não encontrada"}
        async with MANAGER.lock_for(account.profile):
            ctx = await MANAGER.context_for(account.profile)
            st = self._ASSIST.get(account_id)
            page: Any = None
            resume = bool(st) and not st["page"].is_closed()
            picked = (st or {}).get("picked", "")
            if resume:
                page = st["page"]
                await page.wait_for_timeout(1500)
            else:
                page = await ctx.new_page()
                await page.goto(
                    "https://accounts.google.com/ServiceLogin",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2500)

            try:
                # 1) wizard do Google (se ainda não logado)
                if not code and page.locator(EMAIL_SEL).count():
                    await page.fill(EMAIL_SEL, email)
                    await page.click("#identifierNext")
                    try:
                        await page.wait_for_selector(PASS_SEL, timeout=20000)
                    except Exception:
                        txt = await self._page_txt(page)
                        self._ASSIST.pop(account_id, None)
                        return {
                            "ok": False,
                            "error": "o Google respondeu: " + (txt or "tela sem campo de senha"),
                            "shot": await self._assist_shot(page, account),
                        }
                    await page.fill(PASS_SEL, password)
                    await page.click("#passwordNext")
                    await page.wait_for_timeout(3500)
                # 2) desafio 2FA — o campo do código pode aparecer direto ou
                #    depois de escolher o método ("Tentar outro jeito" → SMS /
                #    Autenticador / prompt no celular). Até 4 rodadas.
                tries = 0
                for _ in range(4):
                    tel = page.locator('input[type="tel"]')
                    if await tel.count():
                        if not code:
                            # pode ser a tela do CÓDIGO (6 dígitos) ou a tela
                            # que pede o NÚMERO de telefone inteiro p/ enviar SMS
                            ttxt = (await self._page_txt(page, 600)).lower()
                            asks_phone = (
                                "número de telefone" in ttxt or "phone number" in ttxt
                            ) and "código" not in ttxt and "code" not in ttxt
                            self._ASSIST[account_id] = {
                                "page": page,
                                "picked": picked,
                            }
                            return {
                                "ok": False,
                                "need_code": not asks_phone,
                                "need_manual": asks_phone,
                                "hint": (
                                    (
                                        "📱 o Google quer o SEU NÚMERO de celular "
                                        "pra enviar o SMS — essa tela o assistente "
                                        "não preenche. Toque em “fechar” e use o "
                                        "botão LOGIN (manual): você clica na tela "
                                        "pelo Desktop virtual e digita o número."
                                    )
                                    if asks_phone
                                    else (
                                        "o código 2FA vai por SMS no seu CELULAR "
                                        "(ou do app Autenticador) — NÃO chega por "
                                        "e-mail. Digite os 6 dígitos e toque em "
                                        "entrar de novo."
                                    )
                                ),
                                "shot": await self._assist_shot(page, account),
                            }
                        await tel.first.fill(code)
                        try:
                            await page.click("#totpNext", timeout=5000)
                        except Exception:
                            await page.keyboard.press("Enter")
                        await page.wait_for_timeout(3500)
                        code = ""
                        picked = "code"
                        continue
                    if await self._challenge_screen(page):
                        if picked == "prompt":
                            # esperando o dono tocar "Sim, sou eu" no celular
                            await page.wait_for_timeout(3000)
                            if await self._challenge_screen(page):
                                self._ASSIST[account_id] = {
                                    "page": page,
                                    "picked": picked,
                                }
                                return {
                                    "ok": False,
                                    "need_code": True,
                                    "hint": (
                                        "toque “Sim, sou eu” no seu CELULAR "
                                        "pra confirmar; depois toque em entrar "
                                        "aqui de novo (sem código)."
                                    ),
                                    "shot": await self._assist_shot(page, account),
                                }
                            break
                        if tries >= 2:
                            self._ASSIST[account_id] = {
                                "page": page,
                                "picked": picked,
                            }
                            return {
                                "ok": False,
                                "need_code": True,
                                "hint": (
                                    "o Google pediu um método que o "
                                    "assistente não sabe preencher (chave "
                                    "física etc.). Faça login manual pelo "
                                    "/desktop (botão LOGIN)."
                                ),
                                "shot": await self._assist_shot(page, account),
                            }
                        tries += 1
                        m = await self._pick_challenge(page)
                        if m:
                            picked = m
                        continue
                    break
            except Exception as exc:
                self._ASSIST.pop(account_id, None)
                return {
                    "ok": False,
                    "error": f"o Google mudou algo no caminho: {exc}",
                    "shot": await self._assist_shot(page, account),
                }

            self._ASSIST.pop(account_id, None)

            # 3) Arena: com o perfil logado no Google, o OAuth vira 1 clique
            if account.platform == "arena":
                try:
                    await page.goto("https://arena.ai/", wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    for sel in (
                        'button:has-text("Sign in"), a:has-text("Sign in")',
                        'button:has-text("Google"), a:has-text("Google")',
                    ):
                        try:
                            await page.locator(sel).first.click(timeout=5000)
                            await page.wait_for_timeout(2000)
                        except Exception:
                            pass
                    # seletor de conta do Google ("Escolher uma conta")
                    try:
                        await page.get_by_text(email, exact=False).first.click(timeout=7000)
                        await page.wait_for_timeout(3000)
                    except Exception:
                        pass
                    # botões de consentimento OAuth, se aparecerem
                    for sel in ('button:has-text("Continuar")', 'button:has-text("Continue")', 'button:has-text("Allow")'):
                        try:
                            await page.locator(sel).first.click(timeout=2500)
                            await page.wait_for_timeout(1500)
                        except Exception:
                            pass
                except Exception:
                    pass

            await page.wait_for_timeout(2000)
            from adapters import check_login

            spec = self.registry.get(account.platform) or self.orch.ensure_adapter(
                account.platform
            )
            state = await check_login(page, spec)
            account.status = AccountStatus.OK if state == "ok" else (
                AccountStatus.LOGGED_OUT if state == "logged_out" else AccountStatus.UNKNOWN
            )
            account.last_check = time.time()
            STORE.save_accounts()
            shot = await self._assist_shot(page, account)
            try:
                await page.close()  # libera RAM; a sessão fica no perfil
            except Exception:
                pass
            tok = STORE.prefs.get("backup_token", "")
            if state == "ok" and tok:
                async def _auto_backup(acc: Account = account, t: str = tok) -> None:
                    try:
                        from profile_backup import backup_meta, backup_profile

                        await backup_profile(acc.profile, acc.id, acc.platform, t)
                        await backup_meta(t)
                    except Exception:
                        pass

                asyncio.create_task(_auto_backup())
            return {"ok": state == "ok", "status": state, "shot": shot}

    # --------------------------------------------------- login assistido (fim)

    # --------------------------------------------------- login assistido
    async def open_login(self, account_id: str) -> dict[str, Any]:
        """Abre a plataforma no perfil da conta para o usuário logar na mão.

        Com HEADLESS=false a janela aparece na sua tela e você loga normal
        (com 2FA/captcha). Em VPS headless, use o botão 'ver tela' do painel
        ou o streaming de screenshot em /api/accounts/{id}/screenshot.
        """
        account = STORE.accounts.get(account_id)
        if not account:
            return {"ok": False, "error": "conta não encontrada"}
        spec = self.registry.get(account.platform) or self.orch.ensure_adapter(account.platform)
        url = spec.new_chat_url or spec.url
        async with MANAGER.lock_for(account.profile):
            ctx = await MANAGER.context_for(account.profile)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            shot = Path(_s.shots_dir) / f"login-{account.id}.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(shot))
            from adapters import check_login

            state = await check_login(page, spec)
        account.status = AccountStatus.OK if state == "ok" else (
            AccountStatus.LOGGED_OUT if state == "logged_out" else AccountStatus.UNKNOWN
        )
        account.last_check = time.time()
        STORE.save_accounts()

        # anti-OOM (Render free = 512 MB): a janela de login se fecha sozinha
        # após 15 min — o login fica no perfil em disco (e no backup, se houver)
        async def _login_ttl(p: Any = page) -> None:
            await asyncio.sleep(15 * 60)
            try:
                if not p.is_closed():
                    await p.close()
            except Exception:
                pass

        asyncio.create_task(_login_ttl())

        if state == "ok":
            tok = STORE.prefs.get("backup_token", "")
            if tok:
                async def _auto_backup(acc: Account = account, t: str = tok) -> None:
                    try:
                        from profile_backup import backup_profile

                        r = await backup_profile(acc.profile, acc.id, acc.platform, t)
                        if r.get("ok"):
                            await BUS.ok(
                                f"backup: login de '{acc.label}' guardado no GitHub "
                                f"({r.get('kb')} KB, criptografado)"
                            )
                    except Exception:
                        pass

                asyncio.create_task(_auto_backup())
        return {
            "ok": True,
            "url": url,
            "status": account.status.value,
            "headless": _s.headless,
            "screenshot": f"/shots/{shot.name}",
        }


ENGINE: Optional[Engine] = None


def get_engine() -> Engine:
    global ENGINE
    if ENGINE is None:
        registry = Registry(_s.platforms_path())
        ENGINE = Engine(registry, Orchestrator(registry))
    return ENGINE

    # ------------------------------------------------ auto-setup Telegram ---
    async def telegram_autosetup(
        self, account_id: str, nome_bot: str = "Digest Orbe",
        usuario_bot: str = "", nome_canal: str = ""
    ) -> dict[str, Any]:
        """O ROBÔ cria o próprio bot no @BotFather (e tenta o canal) pilotando
        o Telegram Web com o perfil logado. Token é extraído e salvo direto
        no Piloto Automático. Se o perfil não está logado no Telegram,
        devolve need_login (usuário loga 1x pela tela ao vivo)."""
        import re as _re
        from autopilot import AUTOPILOT

        account = STORE.accounts.get(account_id)
        if not account:
            return {"ok": False, "error": "conta não encontrada"}
        async with MANAGER.lock_for(account.profile):
            ctx = await MANAGER.context_for(account.profile)
            page = await ctx.new_page()
            shot = ""

            async def _shot() -> str:
                try:
                    import base64
                    blob = await page.screenshot(type="png")
                    return "data:image/png;base64," + base64.b64encode(blob).decode("ascii")
                except Exception:
                    return ""

            try:
                await page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(6000)
                # logado? o app mostra a lista de chats; deslogado mostra formulário
                if page.locator("input[type='tel'], input[name='phone']").count():
                    return {"ok": False, "need_login": True,
                            "hint": "logue o Telegram nesse perfil 1x (botão LOGIN → tela ao vivo) e toque aqui de novo",
                            "shot": await _shot()}

                async def _mandar(txt: str) -> None:
                    inp = page.locator("div[contenteditable='true']").first
                    await inp.click(timeout=8000)
                    await inp.fill(txt)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(2500)

                # 1) abre o BotFather
                busca = page.locator("input[placeholder*='Search'], input[placeholder*='Pesquisar']").first
                await busca.click(timeout=10000)
                await busca.fill("BotFather")
                await page.wait_for_timeout(2000)
                await page.get_by_text("BotFather").first.click(timeout=8000)
                await page.wait_for_timeout(2000)

                # 2) /newbot → nome → @usuário (com sufixo aleatório se não veio)
                await _mandar("/newbot")
                await _mandar(nome_bot or "Digest Orbe")
                usuario = (usuario_bot or "orbe_digest_bot").strip()
                if not usuario.lower().endswith("bot"):
                    usuario = usuario + str(random.randint(100, 9999)) + "_bot"
                await _mandar(usuario)
                await page.wait_for_timeout(3000)

                # 3) extrai o token da resposta do BotFather
                txt = (await page.locator(".messages-container, #messages, body").last.inner_text(timeout=8000))
                m = _re.search(r"\b(\d{6,}:[A-Za-z0-9_-]{30,})\b", txt)
                if not m:
                    return {"ok": False,
                            "error": "BotFather não devolveu token (nome/@ já existe?)",
                            "shot": await _shot()}
                token = m.group(1)

                # 4) salva direto no Piloto Automático + testa
                AUTOPILOT.save(bot_token=token)
                chat_ok = await AUTOPILOT.send_telegram(
                    f"🤖 bot criado PELO ORBE sozinho ({usuario}) — canal em configuração…")

                # 5) canal (beta: a UI do Telegram varia; se falhar devolve o passo manual)
                canal = nome_canal or f"{nome_bot} — canal"
                canal_ok = False
                try:
                    await page.locator("button.btn-menu, .btn-new-channel, [title='Menu']").first.click(timeout=5000)
                    await page.get_by_text("New Channel", exact=False).first.click(timeout=5000)
                    inp = page.locator("div[contenteditable='true'], input[type='text']").first
                    await inp.fill(canal)
                    for lab in ("Next", "Avançar", "Continuar"):
                        try:
                            await page.get_by_text(lab, exact=True).first.click(timeout=2500)
                            break
                        except Exception:
                            continue
                    await page.wait_for_timeout(2000)
                    canal_ok = True
                except Exception:
                    pass

                AUTOPILOT.save(chat_id=usuario)
                return {
                    "ok": True, "bot_token": token, "usuario_bot": usuario,
                    "telegram_enviou": chat_ok, "canal_criado": canal_ok,
                    "hint": ("" if canal_ok else
                             "bot ✅ e token salvo no Piloto Automático! O canal criou pela UI — "
                             "se não apareceu, crie na mão na tela ao vivo (2 min) e cole o @canal no card 📡"),
                    "shot": await _shot(),
                }
            except Exception as exc:
                return {"ok": False, "error": f"Telegram mudou algo: {exc}", "shot": await _shot()}
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
