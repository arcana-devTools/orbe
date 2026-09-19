"""
CLI do Orbe — mesmo motor do painel, direto no terminal.

    python cli.py "pesquise tendências de agentes de IA e resuma"
    python cli.py --platforms chatgpt,perplexity "compare os dois"
    python cli.py --accounts            lista contas
    python cli.py --platforms-list      lista adapters instalados
    python cli.py --login acc_xxx       abre a plataforma para logar
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from browser import MANAGER
from engine import get_engine
from models import Account, TaskState
from store import STORE


async def _run(
    goal: str,
    platforms: list[str] | None,
    quiet: bool,
    account_ids: list[str] | None = None,
    accounts_limit: int = 1,
) -> int:
    eng = get_engine()
    await MANAGER.start()
    if not MANAGER.enabled:
        print(f"[erro] navegador indisponível: {MANAGER.disabled_reason}", file=sys.stderr)
        print("       instale com: python -m playwright install chromium", file=sys.stderr)
        return 2
    try:
        task = await eng.submit(goal, platforms, account_ids, accounts_limit)
        print(f"[task] {task.id}")
        last = ""
        while task.state not in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELED):
            await asyncio.sleep(1)
            if not quiet:
                line = " | ".join(f"{r.platform}:{'ok' if r.ok else 'x'}" for r in task.results)
                if line and line != last:
                    print(f"  · {task.state.value} {line}")
                    last = line
        print(f"\n[state] {task.state.value}")
        for r in task.results:
            mark = "ok" if r.ok else f"FALHOU ({r.error})"
            print(f"\n--- {r.platform} [{mark}] {r.elapsed_s}s ---\n{r.answer[:1200]}")
        if task.synthesis:
            print("\n================ CONSOLIDADO ================\n")
            print(task.synthesis)
        return 0 if task.state == TaskState.DONE and any(r.ok for r in task.results) else 1
    finally:
        await MANAGER.stop()


def main() -> int:
    p = argparse.ArgumentParser(description="Orbe — agente que pilota outras IAs")
    p.add_argument("goal", nargs="?", help="objetivo em linguagem natural")
    p.add_argument("--platforms", default="", help="lista separada por vírgula (ex.: chatgpt,claude)")
    p.add_argument("--accounts", action="store_true", help="lista as contas configuradas")
    p.add_argument("--platforms-list", action="store_true", help="lista os adapters instalados")
    p.add_argument("--login", metavar="ACCOUNT_ID", help="abre a plataforma no perfil da conta para logar")
    p.add_argument("--check-all", action="store_true",
                   help="confere se a sessão de cada conta está viva (ok/logged_out)")
    p.add_argument("--add-platform", metavar="URL_OU_NOME",
                   help="cria uma plataforma nova pela URL (ex.: https://poe.com)")
    p.add_argument("--contas", type=int, default=1,
                   help="quantas contas usar POR plataforma (1 = primeira, 0 = todas)")
    p.add_argument("--contas-ids", default="",
                   help="ids de contas específicas, separados por vírgula (manda sobre --contas)")
    p.add_argument("--add-account", metavar="PLATAFORMA:ROTULO",
                   help="cria conta (ex.: chatgpt:pessoal)")
    p.add_argument("--set-login", metavar="ACCOUNT_ID",
                   help="guarda usuário/senha no cofre para login automático")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    if args.accounts:
        if not STORE.accounts:
            print("nenhuma conta. Crie pelo painel ou: POST /api/accounts")
            return 0
        for a in STORE.accounts.values():
            print(f"{a.id}  {a.platform:14} {a.label:12} perfil={a.profile} status={a.status.value}")
        return 0

    if args.platforms_list:
        eng = get_engine()
        for spec in eng.registry.list():
            accs = ", ".join(a.label for a in STORE.accounts_for_platform(spec.id)) or "-"
            print(f"{spec.id:16} {spec.name:16} {spec.category:10} contas: {accs}  ({spec.source})")
        return 0

    if args.add_account:
        plat, _, label = args.add_account.partition(":")
        acc = Account(platform=plat.strip(), label=(label.strip() or "conta 1"))
        STORE.add_account(acc)
        print(f"criada: {acc.id}  {acc.platform}  perfil={acc.profile}")
        print("agora rode: python cli.py --login " + acc.id)
        return 0

    if args.set_login:
        import getpass
        from secrets_vault import VAULT
        if args.set_login not in STORE.accounts:
            print("conta não encontrada", file=sys.stderr)
            return 1
        user = input("usuário/e-mail: ").strip()
        pw = getpass.getpass("senha (não aparece na tela): ")
        VAULT.put(args.set_login, user, pw)
        print("salvo criptografado em data/secrets/vault.json")
        return 0

    if args.login:
        async def _login() -> int:
            await MANAGER.start()
            try:
                r = await get_engine().open_login(args.login)
                print(r)
                return 0 if r.get("ok") else 1
            finally:
                await MANAGER.stop()
        return asyncio.run(_login())

    if args.add_platform:
        eng = get_engine()
        spec = eng.orch.ensure_adapter(args.add_platform)
        eng.registry.reload()
        print(f"plataforma criada: {spec.id}  url={spec.url}")
        print("agora crie a conta:  python cli.py --add-account " + spec.id + ":pessoal")
        return 0

    if args.check_all:
        async def _check() -> int:
            await MANAGER.start()
            try:
                rows = await get_engine().check_all_accounts()
                for r in rows:
                    extra = f"  erro={r['error']}" if r["error"] else ""
                    print(f"{r['status']:12} {r['platform']:14} {r['label']:12} "
                          f"({r['elapsed_s']}s){extra}")
                return 0
            finally:
                await MANAGER.stop()
        if not STORE.accounts:
            print("nenhuma conta registrada")
            return 0
        return asyncio.run(_check())

    if not args.goal:
        p.print_help()
        return 2

    plats = [x.strip() for x in args.platforms.split(",") if x.strip()] or None
    ids = [x.strip() for x in args.contas_ids.split(",") if x.strip()] or None
    return asyncio.run(_run(args.goal, plats, args.quiet, ids, max(0, args.contas)))


if __name__ == "__main__":
    raise SystemExit(main())
