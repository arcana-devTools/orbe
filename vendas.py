"""💰 Livro-caixa de VENDAS REAIS — só entra aqui dinheiro que existiu de verdade.

Regra de transparência do dono: crédito simulado da colônia NUNCA vem pra cá.
Cada venda tem loja + prova (id do pedido/recibo) e não duplica.

Entradas:
- conectores automáticos por loja (lista CONECTORES) — o do Etsy entra quando a loja existir;
- registro manual pelo painel/API (POST /api/vendas), marcado como origem "manual".
O resumo das 19h no Telegram mostra o que entrou desde o último resumo.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

VENDAS = Path("data/vendas.json")
SIMBOLO = {"BRL": "R$", "USD": "US$", "EUR": "€", "USDT": "USDT"}

# cada conector: async () -> list[dict(loja, valor, moeda, prova, produto_id?, titulo?)]
CONECTORES: list[Callable[[], Awaitable[list[dict]]]] = []


def ler() -> list[dict]:
    try:
        return json.loads(VENDAS.read_text(encoding="utf-8"))
    except Exception:
        return []


def _salvar(itens: list[dict]) -> None:
    VENDAS.parent.mkdir(parents=True, exist_ok=True)
    VENDAS.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


def registrar(loja: str, valor: float, moeda: str, prova: str = "", produto_id: str = "",
              titulo: str = "", origem: str = "conector") -> dict | None:
    """Grava 1 venda real. Devolve None se já existia (mesma loja + prova) ou valor inválido."""
    loja, moeda = str(loja).strip().lower(), str(moeda).strip().upper()
    try:
        valor = round(float(valor), 2)
    except (TypeError, ValueError):
        return None
    if not loja or valor <= 0 or not moeda:
        return None
    itens = ler()
    if prova and any(v.get("loja") == loja and v.get("prova") == prova for v in itens):
        return None
    venda = {"id": f"v{int(time.time() * 1000)}", "ts": time.time(), "loja": loja, "valor": valor,
             "moeda": moeda, "prova": str(prova)[:200], "produto_id": produto_id, "titulo": titulo[:120],
             "origem": origem}
    itens.append(venda)
    _salvar(itens)
    if produto_id:     # o aprendizado usa isso: produto que vende vira variações
        try:
            import acabamento

            p = acabamento.PRODUTOS / produto_id / "meta.json"
            if p.exists():
                m = json.loads(p.read_text(encoding="utf-8"))
                m["vendas"] = int(m.get("vendas", 0)) + 1
                m["ultima_venda"] = venda["ts"]
                p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
    try:
        import discord_aviso
        discord_aviso.avisar(venda)
    except Exception:
        pass
    return venda


def totais(itens: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for v in itens:
        out[v["moeda"]] = round(out.get(v["moeda"], 0.0) + float(v["valor"]), 2)
    return out


def fmt_totais(t: dict[str, float]) -> str:
    if not t:
        return "R$ 0"
    return " + ".join(f"{SIMBOLO.get(m, m)} {v:.2f}".replace(".00", "") for m, v in sorted(t.items()))


def desde(ts: float) -> list[dict]:
    return [v for v in ler() if v.get("ts", 0) > ts]


def resumo_txt(desde_ts: float) -> str:
    novas, todas = desde(desde_ts), ler()
    if not todas:
        return "💰 Vendas reais: nenhuma ainda (R$ 0) — lojas ainda não conectadas."
    linhas = [f"💰 {len(novas)} venda(s) real(is) desde o último resumo: {fmt_totais(totais(novas))}"
              if novas else "💰 Nenhuma venda nova desde o último resumo."]
    for v in novas[:5]:
        linhas.append(f"  • {v['loja']}: {SIMBOLO.get(v['moeda'], v['moeda'])} {v['valor']} — {v.get('titulo') or v.get('prova')}")
    linhas.append(f"Total real desde o início: {fmt_totais(totais(todas))} ({len(todas)} venda(s))")
    return "\n".join(linhas)


def _conectores_padrao() -> None:
    """Conectores conhecidos se registram sozinhos (sem credencial, devolvem vazio)."""
    for mod in ("kiwify", "uiclap"):
        if any(getattr(c, "__module__", "") == mod for c in CONECTORES):
            continue
        try:
            m = __import__(mod)
            f = getattr(m, "conector", None)
            if callable(f):
                CONECTORES.append(f)
        except Exception:
            continue


async def sincronizar() -> int:
    """Roda os conectores das lojas e grava o que for novo. Devolve quantas vendas novas."""
    n = 0
    _conectores_padrao()
    for con in CONECTORES:
        try:
            for v in await con():
                if registrar(v.get("loja", ""), v.get("valor", 0), v.get("moeda", ""), v.get("prova", ""),
                             v.get("produto_id", ""), v.get("titulo", "")):
                    n += 1
        except Exception:
            continue
    return n


def lojas() -> dict[str, Any]:
    """Saúde de cada loja com conector (sem credencial aparece como pendente)."""
    saida: dict[str, Any] = {}
    try:
        import kiwify

        saida["kiwify"] = kiwify.estado()
    except Exception as exc:
        saida["kiwify"] = {"ok": False, "motivo": f"{type(exc).__name__}"}
    return saida


def status() -> dict[str, Any]:
    todas = ler()
    _conectores_padrao()
    return {"vendas": len(todas), "total": totais(todas), "total_txt": fmt_totais(totais(todas)),
            "conectores": len(CONECTORES), "lojas": lojas(), "ultimas": todas[-10:]}
