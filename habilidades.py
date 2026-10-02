"""🧠 Habilidades — a colônia escreve as próprias receitas (a ideia do Hermes, aqui dentro).

Como funciona:
- cada vez que ela resolve algo, isso cai no diário (`data/diario.jsonl`);
- quando a MESMA ação aparece de novo (ou dá certo uma vez e é nova pra ela), ela
  redige sozinha um arquivo markdown em `data/habilidades/` dizendo como faz;
- na próxima vez, a habilidade é lida antes de agir, pra não reinventar.

Nada de habilidade nossa: são DELA, escritas por ela a partir do que ela viveu.
Se a IA estiver fora do ar, ela simplesmente não escreve — e continua vivendo.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

PASTA = Path("data/habilidades")
DIARIO = Path("data/diario.jsonl")


def _slug(txt: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (txt or "").lower()).strip("-")
    return s[:48] or "sem-nome"


def lista() -> list[dict[str, Any]]:
    saida = []
    if not PASTA.exists():
        return saida
    for p in sorted(PASTA.glob("*.md")):
        try:
            txt = p.read_text(encoding="utf-8")
            linhas = txt.splitlines()
            if linhas and linhas[0].strip() == "---":
                for i, linha in enumerate(linhas[1:], 1):
                    if linha.strip() == "---":
                        linhas = linhas[i + 1:]
                        break
            titulo = p.stem
            for linha in linhas:
                s = linha.strip()
                if s.startswith("#"):
                    titulo = s.lstrip("# ").strip()
                    break
            saida.append({"nome": p.stem, "titulo": titulo[:80], "linhas": len(txt.splitlines()),
                          "em": p.stat().st_mtime})
        except Exception:
            continue
    return saida


def tem(acao: str) -> bool:
    return (PASTA / (_slug(acao) + ".md")).exists()


def ler(acao: str) -> str:
    p = PASTA / (_slug(acao) + ".md")
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def salvar(acao: str, corpo: str) -> Path | None:
    """Ela grava a própria habilidade em markdown (legível, versionável, portável)."""
    if not corpo.strip():
        return None
    PASTA.mkdir(parents=True, exist_ok=True)
    p = PASTA / (_slug(acao) + ".md")
    # mesmo padrão aberto do Hermes (agentskills.io): as habilidades são portáveis
    desc = (corpo.strip().splitlines()[0] if corpo.strip() else acao)[:120]
    frente = f"---\nname: {_slug(acao)}\ndescription: {desc}\nversion: 1\n---\n\n"
    cabeca = f"# {acao}\n\n> escrito por mim em {time.strftime('%d/%m/%Y %H:%M')}\n\n"
    p.write_text(frente + cabeca + corpo.strip() + "\n", encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass
    return p


def _vezes_no_diario(acao: str) -> int:
    try:
        linhas = [json.loads(x) for x in DIARIO.read_text(encoding="utf-8").splitlines() if x.strip()]
        return sum(1 for l in linhas if l.get("acao") == acao)
    except Exception:
        return 0


async def escrever(acao: str, porque: str, resultado: str) -> str | None:
    """Ela redige a habilidade com a própria IA (se houver) e guarda."""
    if tem(acao):
        return None
    try:
        import llm_pool

        if not llm_pool.disponivel():
            return None
    except Exception:
        return None
    sistema = ("Você é a Orbe, uma colônia de agentes que trabalha sozinha e escreve as "
               "PRÓPRIAS habilidades. Escreva em português, em markdown, em no máximo 15 linhas, "
               "sem enrolação e sem cumprimentos. Só o procedimento, como uma receita.")
    user = (f"Ação: {acao}\nPor que eu fiz: {porque}\nO que aconteceu: {resultado}\n\n"
            "Escreva o arquivo desta habilidade com: (1) quando eu devo usar, (2) os passos "
            "que eu sigo, (3) como eu sei que deu certo, (4) o que pode dar errado. "
            "Nada de introdução.")
    try:
        txt, _motor = await llm_pool.chat(sistema, user, max_tokens=900, temperature=0.3)
    except Exception:
        return None
    if not txt or len(txt) < 40:
        return None
    p = salvar(acao, txt)
    return str(p) if p else None



async def aprender_material(acao: str, porque: str, material: str) -> str | None:
    """Ela escreve a skill a partir do que viu. Sem material, não inventa."""
    acao = (acao or "").strip()[:80]
    material = (material or "").strip()
    if not acao or len(material) < 40:
        return None
    if tem(acao):
        return str(PASTA / (_slug(acao) + ".md"))
    try:
        import llm_pool

        if not llm_pool.disponivel():
            return None
    except Exception:
        return None
    sistema = (
        "Você é a Orbe. Escreva a SUA habilidade em português, markdown, no máximo 18 linhas. "
        "Só o que está no material. Não invente nome de site, bot ou fornecedor. "
        "Não inclua passo de spam, conta falsa, aposta, pirâmide, cartão, repostar vídeo alheio "
        "nem baixar vídeo do YouTube. Se o material não der um procedimento, diga isso em uma linha."
    )
    user = (
        f"Ação: {acao}\nPor que: {porque[:300]}\n\nMaterial que eu vi:\n{material[:3500]}\n\n"
        "Escreva: (1) quando eu uso, (2) os passos que eu sigo, (3) como sei que deu certo, "
        "(4) o que pode dar errado. Nada de introdução."
    )
    try:
        txt, _motor = await llm_pool.chat(sistema, user, max_tokens=900, temperature=0.3)
    except Exception:
        return None
    if not txt or len(txt) < 40:
        return None
    salvo = salvar(acao, txt)
    try:
        import conciencia

        conciencia.anotar(f"habilidade gravada: {acao}", acao="habilidade")
    except Exception:
        pass
    return str(salvo) if salvo else None


async def tentar_aprender(decidido: dict[str, Any], resultado: dict[str, Any]) -> str | None:
    """Chamada depois de agir: se repetiu (ou foi bem), ela escreve a receita."""
    acao = str(decidido.get("acao") or "")
    if not acao or not resultado.get("feito"):
        return None
    if acao in ("observar", "esperar", "nota"):
        return None
    if tem(acao):
        return None
    if _vezes_no_diario(acao) < 1:
        return None
    return await escrever(acao, str(decidido.get("porque") or ""), str(resultado.get("resumo") or ""))


def resumo_txt() -> str:
    itens = lista()
    if not itens:
        return "🧠 Habilidades: nenhuma escrita ainda."
    return "🧠 Habilidades que eu escrevi: " + ", ".join(i["titulo"][:28] for i in itens[-6:])
