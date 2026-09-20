"""
ORQUESTRADOR — o "cérebro" que decide QUEM faz o quê.

Recebe um objetivo em linguagem natural e devolve um plano de rotas:
   [{account_id, platform, prompt, depends_on}]

Dois modos:
  * LLM  : usa uma API compatível com OpenAI (OpenRouter/Groq/Ollama/...) quando
           você configura LLM_API_KEY. Faz decomposição de verdade e síntese.
  * Local: sem chave nenhuma, usa regras + fan-out (mesma pergunta para todas
           as IAs configuradas) e síntese local. Sempre funciona offline.

Também cria adapters sob demanda: se você pedir uma IA que não existe em
platforms/, ele gera um adapter genérico na hora e salva em platforms/ para as
próximas vezes.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from adapters import AdapterSpec, Registry, slug
from config import get_settings
from events import BUS
from models import Account, AccountStatus
from store import STORE

_s = get_settings()

KEYWORDS: dict[str, list[str]] = {
    "chatgpt": ["chatgpt", "gpt", "openai", "codar", "código", "code", "resumir", "escrever"],
    "gemini": ["gemini", "google", "imagem", "vídeo", "video", "planilha", "docs"],
    "claude": ["claude", "anthropic", "documento longo", "contrato", "análise longa"],
    "perplexity": ["pesquisar", "pesquisa", "buscar na web", "notícia", "fonte", "referência", "perplexity"],
    "grok": ["grok", "twitter", "x.com", "tendência"],
    "deepl": ["traduzir", "tradução", "translate"],
    "youtube": ["youtube", "vídeo", "video", "assistir", "transcrição"],
    "github": ["github", "repositório", "repo", "commit", "issue", "pull request"],
    "google-search": ["googlar", "procurar no google", "busca simples"],
    "canva": ["canva", "design", "post", "apresentação", "slide"],
    "notion": ["notion", "anotar", "nota", "kanban"],
}

PLATFORM_LABELS = {
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "claude": "Claude",
    "perplexity": "Perplexity",
    "grok": "Grok",
    "deepl": "DeepL",
    "youtube": "YouTube",
    "github": "GitHub",
    "google-search": "Google Search",
    "canva": "Canva",
    "notion": "Notion",
}


class Orchestrator:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    # ------------------------------------------------------------ planejamento
    async def plan(
        self,
        goal: str,
        prefer: Optional[list[str]] = None,
        account_ids: Optional[list[str]] = None,
        accounts_limit: int = 1,
        per_account: Optional[dict[str, str]] = None,
    ) -> list[dict[str, str]]:
        """Monta as rotas (quem executa o quê).

        prefer          restringe as plataformas.
        account_ids     contas específicas escolhidas pelo usuário. Quando vem
                        preenchido, ele MANDA: ignoramos `prefer` e o limite, e a
                        mesma tarefa roda exatamente nessas contas.
        accounts_limit  quantas contas usar POR plataforma quando `account_ids`
                        está vazio: 1 = só a primeira (padrão, mais barato),
                        0 = todas as contas registradas e logadas.
        """
        if account_ids:
            return self._routes_for_accounts(account_ids, goal, per_account or {})

        if _s.llm_api_key:
            try:
                steps = await self._plan_with_llm(goal, prefer)
                if steps:
                    return self._assign_accounts(steps, accounts_limit)
            except Exception as exc:
                await BUS.warn(f"plano via LLM falhou, caindo para o modo local: {exc}")
        return self._plan_local(goal, prefer, accounts_limit)

    # --------------------------------------------------- escolha de contas
    def _routes_for_accounts(self, account_ids: list[str], goal: str, per_account: Optional[dict[str, str]] = None) -> list[dict[str, str]]:
        per_account = per_account or {}
        prompts = self._split_per_account(goal, len(account_ids))
        routes: list[dict[str, str]] = []
        for i, acc_id in enumerate(account_ids):
            acc = STORE.accounts.get(acc_id)
            if not acc:
                continue                      # id inexistente é ignorado, não derruba a tarefa
            routes.append(
                {
                    "platform": acc.platform,
                    "account_id": acc.id,
                    "prompt": per_account.get(acc_id) or prompts[i],
                    "instruction": "",
                }
            )
        return routes

    @staticmethod
    def _split_per_account(goal: str, n: int) -> list[str]:
        """Extrai instruções por conta da sintaxe "conta N: ..." no objetivo.

        Ex.:  conta 1: pesquise sobre o clima
              conta 2: pesquise sobre a chuva
        Contas sem linha própria recebem o texto global (linhas fora das
        diretivas). Sem a sintaxe, todas recebem o objetivo inteiro.
        Também aceita a forma INLINE numa linha só: "conta 1: X / conta 2: Y"
        (e separando por ";") — v0.12.
        """
        # inline -> uma diretiva por linha (só separa quando "/" ou ";" vem
        # ANTES de "conta N:", para não quebrar "/" legítimo dentro do texto)
        goal = re.sub(r"\s*[/;]\s*(conta\s+\d+\s*[:\-])", r"\n\1", goal, flags=re.I)
        prompts = [""] * n
        global_lines: list[str] = []
        cur = -1
        for line in goal.splitlines():
            m = re.match(r"^\s*conta\s+(\d+)\s*[:\-]\s*(.*)$", line, re.I)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < n:
                    cur = idx
                    if m.group(2).strip():
                        prompts[idx] = (prompts[idx] + " " + m.group(2).strip()).strip()
                    continue
                cur = -1
            if line.strip():
                if cur >= 0:
                    prompts[cur] = (prompts[cur] + " " + line.strip()).strip()
                else:
                    global_lines.append(line.strip())
        if not any(p.strip() for p in prompts):
            return [goal] * n
        base = " ".join(global_lines).strip()
        return [p.strip() or base or goal for p in prompts]

    def _assign_accounts(self, steps: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
        routes: list[dict[str, str]] = []
        for st in steps:
            pid = st["platform"]
            for acc_id in self._accounts_for(pid, limit):
                routes.append(
                    {
                        "platform": pid,
                        "account_id": acc_id,
                        "prompt": st.get("prompt", ""),
                        "instruction": st.get("instruction", ""),
                    }
                )
        return routes

    def _accounts_for(self, platform: str, limit: int = 1) -> list[str]:
        """Contas da plataforma que vão executar (limit=1 -> primeira; 0 -> todas)."""
        accts = STORE.accounts_for_platform(platform)
        if not accts:
            # nenhuma conta registrada ainda: cria uma automática (você loga depois)
            acc = Account(platform=platform, label="auto", profile=f"{slug(platform)}-auto")
            STORE.add_account(acc)
            return [acc.id]
        ids = [a.id for a in accts]
        return ids if limit <= 0 else ids[:limit]

    # ------------------------------------------------------------ planos
    def _plan_local(self, goal: str, prefer: Optional[list[str]], limit: int = 1) -> list[dict[str, str]]:
        text = goal.lower()
        matched = [pid for pid, kws in KEYWORDS.items() if any(k in text for k in kws)]
        if prefer:
            matched = [p for p in prefer if p in matched] or list(prefer)
        if not matched:
            # sem pista: manda para as plataformas que têm conta configurada
            platforms = sorted({a.platform for a in STORE.accounts.values()})
            matched = platforms or ["chatgpt"]
        return self._assign_accounts(
            [{"platform": pid, "prompt": goal, "instruction": ""} for pid in matched],
            limit,
        )

    async def _plan_with_llm(self, goal: str, prefer: Optional[list[str]]) -> list[dict[str, str]]:
        """Pede a decomposição ao LLM. As contas são atribuídas depois."""
        available = self._availability_text()
        sys_prompt = (
            "Você é o planejador de um agente que pilota outras IAs pelo navegador.\n"
            "Dado o objetivo do usuário, devolva APENAS um JSON com a chave 'steps', "
            "uma lista de objetos {\"platform\": str, \"prompt\": str, \"instruction\": str, \"depends_on\": int|null}.\n"
            "Regras: use apenas plataformas da lista disponível; divida o trabalho entre IAs quando fizer sentido; "
            "cada prompt deve ser autossuficiente (a IA de destino não vê a conversa); "
            "máximo 5 passos. Não escreva nada além do JSON."
        )
        user = f"OBJETIVO: {goal}\n\nDISPONÍVEL:\n{available}"
        if prefer:
            user += f"\n\nUse somente: {', '.join(prefer)}"
        raw = await self._chat(sys_prompt, user, temperature=0.2)
        data = self._extract_json(raw)
        steps = data.get("steps", []) if isinstance(data, dict) else []
        out: list[dict[str, str]] = []
        for st in steps[:_s.max_steps_per_task]:
            pid = str(st.get("platform", "")).strip()
            if not pid:
                continue
            out.append(
                {
                    "platform": pid,
                    "prompt": str(st.get("prompt", goal)),
                    "instruction": str(st.get("instruction", "")),
                }
            )
        return out

    def _availability_text(self) -> str:
        lines = []
        for spec in self.registry.list():
            accts = STORE.accounts_for_platform(spec.id)
            who = ", ".join(a.label for a in accts) or "sem conta configurada"
            lines.append(f"- {spec.id} ({spec.name}, categoria {spec.category}): contas: {who}")
        return "\n".join(lines) or "- nenhuma plataforma instalada"

    # ------------------------------------------------------------ síntese
    async def synthesize(self, goal: str, results: list[Any]) -> str:
        oks = [r for r in results if r.ok and r.answer]
        if not oks:
            failed = [f"- {r.platform}: {r.error}" for r in results if not r.ok]
            return "Nenhuma IA respondeu.\n\n" + "\n".join(failed)

        if len(oks) == 1:
            r = oks[0]
            return f"**{PLATFORM_LABELS.get(r.platform, r.platform)}** ({r.title})\n\n{r.answer}"

        if _s.llm_api_key:
            try:
                return await self._synthesize_llm(goal, oks)
            except Exception as exc:
                await BUS.warn(f"síntese via LLM falhou, usando síntese local: {exc}")
        return self._synthesize_local(goal, oks)

    def _synthesize_local(self, goal: str, oks: list[Any]) -> str:
        parts = [f"## Respostas coletadas para: {goal}\n"]
        for i, r in enumerate(oks, 1):
            label = PLATFORM_LABELS.get(r.platform, r.platform)
            parts.append(f"### {i}. {label} ({r.title})\n\n{r.answer}\n")
        parts.append(
            "---\n\n*Dica: configure `LLM_API_KEY` no `.env` para o Orbe cruzar essas respostas "
            "e gerar uma resposta única consolidada.*"
        )
        return "\n".join(parts)

    async def _synthesize_llm(self, goal: str, oks: list[Any]) -> str:
        blocks = []
        for r in oks:
            label = PLATFORM_LABELS.get(r.platform, r.platform)
            blocks.append(f"[{label}]\n{r.answer[:6000]}")
        sys_prompt = (
            "Você consolida respostas de várias IAs. Produza uma resposta final única, em português, "
            "organizada, sem repetir, apontando divergências quando houver e citando de qual IA veio "
            "cada afirmação importante."
        )
        user = f"OBJETIVO: {goal}\n\nRESPOSTAS:\n\n" + "\n\n---\n\n".join(blocks)
        return await self._chat(sys_prompt, user, temperature=0.3)

    # ------------------------------------------------------------ LLM client
    async def _chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        payload = {
            "model": _s.llm_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {_s.llm_api_key}"}
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(f"{_s.llm_base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _extract_json(raw: str) -> dict:
        try:
            return json.loads(raw)
        except Exception:
            pass
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}

    # ------------------------------------------------- adapter sob demanda
    def ensure_adapter(self, platform_or_url: str, name: str = "") -> AdapterSpec:
        """Garante que existe adapter para o alvo. Cria um genérico se preciso."""
        pid = platform_or_url.strip()
        if pid in self.registry.specs:
            return self.registry.specs[pid]

        url = pid if pid.startswith("http") else ""
        if not url:
            guess = f"https://www.{slug(pid).replace('-', '')}.com"
            url = guess
            pid = slug(pid)
        else:
            pid = slug(re.sub(r"^https?://", "", url).split("/")[0])

        display = name.strip() or pid.replace("-", " ").title()
        spec = AdapterSpec(
            id=pid,
            name=display,
            kind="browser",
            category="auto",
            url=url,
            new_chat_url=url,
            prompt_selector="",          # vazio = modo auto (descobre sozinho)
            submit={"key": "Enter"},
            answer_selector="",
            settle_ms=3000,
            max_wait_s=120,
            source=f"auto-{pid}.yaml",
        )
        data = {
            "id": spec.id,
            "name": spec.name,
            "kind": "browser",
            "category": "auto",
            "url": spec.url,
            "new_chat_url": spec.new_chat_url,
            "submit": {"key": "Enter"},
            "settle_ms": spec.settle_ms,
            "max_wait_s": spec.max_wait_s,
            "_nota": "Adapter criado automaticamente pelo Orbe. Edite os seletores para ficar preciso.",
        }
        path = _s.platforms_path() / f"auto-{pid}.yaml"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception:
            pass
        self.registry.specs[spec.id] = spec
        return spec
