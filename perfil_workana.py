"""🪪 AGENTE DE PERFIL (Workana) — a colônia completa o perfil do dono, com honestidade.

O Workana só deixa mandar proposta com perfil completo. Seções (peso no %):
  descrição 10 • foto 10 • 3 habilidades 30 • portfólio 30 • idiomas 20 (já feito pelo dono)

Regras de honestidade (inegociáveis):
- nada de experiência, cliente, número ou formação inventados;
- o perfil diz que o trabalho usa IA com revisão cuidadosa;
- portfólio = AMOSTRAS feitas pela colônia, rotuladas como "amostra / projeto próprio";
- foto: só foto REAL do dono (ou um logo). Nunca rosto gerado por IA.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

import freelas

REGISTRO = Path("data/workana_perfil.json")
HABILIDADES = [("article-writing", "Escrita de artigos"), ("proofreading", "Correção de textos"),
               ("translation-1", "Tradução")]      # as 3 que o dono escolheu no cadastro
EXPERIENCIA = 1                                     # "1 ano" — o que o dono declarou


def _registro() -> dict:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar(d: dict) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


async def _pagina(cx: httpx.AsyncClient) -> tuple[str, dict, str]:
    """(url do perfil, initials do componente, csrf) — lidos da página do próprio dono."""
    r = await cx.get(f"{freelas.BASE}/jobs?language=pt")
    m = re.search(r'"profileUrl":\s*"([^"]+?freelancer\\?/[0-9a-f]+)"', _html.unescape(r.text))
    if not m:
        raise RuntimeError("sessão do Workana inválida (não achei o perfil)")
    url = m.group(1).replace("\\/", "/")
    t = (await cx.get(url)).text
    i = t.find("<profile-freelancer")
    a = t.find(':initials="', i) + 11
    ini = json.loads(_html.unescape(t[a:t.find('"', a)]))
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', t).group(1)
    return url, ini, csrf


def _cliente() -> httpx.AsyncClient:
    """Cliente com pote de cookies: o Workana gira o 'dcstcookieii' a cada resposta."""
    jar = httpx.Cookies()
    for par in freelas.cookie().split(";"):
        if "=" in par:
            k, v = par.split("=", 1)
            jar.set(k.strip(), v.strip(), domain=".workana.com")
    base = {k: v for k, v in freelas._hdr(False).items() if k != "Cookie"}
    return httpx.AsyncClient(timeout=40, follow_redirects=True, cookies=jar, headers=base)


def _hdr(cx: httpx.AsyncClient, csrf: str, ref: str) -> dict:
    h = {"X-Csrf-Token": csrf, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/plain, */*",
         "Content-Type": "application/json", "Origin": freelas.BASE, "Referer": ref}
    dcst = None
    for c in cx.cookies.jar:
        if c.name == "dcstcookieii":
            dcst = c.value
    if dcst:
        h["x-dcst"] = dcst
    return h


def secoes(ini: dict) -> dict[str, Any]:
    pc = ini.get("profileCompleteness", {}).get("initials", {})
    if not isinstance(pc, dict) or not pc:          # Workana esconde a caixa quando o perfil está 100%
        return {"pct": 100, "faltando": []}
    return {"pct": pc.get("profileCompletion"),
            "faltando": [s["text"] for s in pc.get("sections", []) if not s.get("done")]}


# ------------------------------------------------------------------ textos (IA da colônia)
_PROIBIDO = re.compile(r"\d+\s*%|por cento|ilimitad|garant(o|ia) (de )?resultado|facebook analytics|"
                       r"anos de experi[êe]ncia|\bclientes? satisfeit|\bj[áa] atendi|formad[oa] em", re.I)
_REGRAS = (" REGRAS: nenhum número/estatística/percentual (não dá pra provar); não cite nomes de ferramentas "
           "ou apps; nada de 'ilimitado' — no máximo '2 rodadas de ajustes'; nada de promessa de resultado.")


def _limpo(txt: str) -> str:
    """'' = ok; senão o trecho proibido encontrado."""
    m = _PROIBIDO.search(txt or "")
    return m.group(0) if m else ""


async def _com_checagem(fn, *args) -> Any:
    ultimo = ""
    for _ in range(3):
        out = await fn(*args)
        corpo = out if isinstance(out, str) else " ".join(a["description"] for a in out)
        ultimo = _limpo(corpo)
        if not ultimo:
            return out
    raise RuntimeError(f"texto reprovado 3x pela checagem de honestidade ('{ultimo}')")
async def _escrever_bio(nome: str) -> str:
    import llm_pool

    user = (f"Escreva o 'Sobre mim' do perfil de freelancer no Workana de {nome}, brasileiro (Santa Catarina). "
            "FATOS (use só estes): começando agora na plataforma, sem avaliações ainda; serviços: redação de "
            "artigos e posts de blog, revisão/correção de textos em português, tradução inglês↔português, "
            "descrições de produto; trabalha com ferramentas de inteligência artificial e faz revisão humana "
            "cuidadosa de tudo antes de entregar; oferece uma amostra curta grátis antes de fechar; responde "
            "rápido; faz até 2 rodadas de ajustes. PROIBIDO inventar anos de experiência, "
            "clientes, empresas, formação, números ou resultados. Tom: profissional, direto, caloroso. "
            "120-180 palavras, 3 parágrafos curtos + lista de 4 serviços com '- '. Sem emojis, sem título. "
            "Só o texto." + _REGRAS)
    txt, _ = await llm_pool.chat("Você escreve perfis de freelancer honestos que convertem.", user,
                                 max_tokens=900, temperature=0.5)
    return txt.strip()[:2500]


async def _escrever_amostras() -> list[dict]:
    import llm_pool

    user = ("Crie 2 AMOSTRAS de portfólio para um redator/revisor/tradutor iniciante no Workana. "
            "1) um artigo de blog curto (250-350 palavras) em português sobre um tema útil do dia a dia de "
            "pequenos negócios; 2) uma tradução: um parágrafo em inglês (60-90 palavras, texto original seu, "
            "tipo descrição de produto) seguido da tradução para português natural. "
            "Responda SOMENTE JSON: [{\"nome\": \"título curto do item\", \"texto\": \"conteúdo completo\"}, ...]. "
            "No texto da tradução use 'Original (EN):' e 'Tradução (PT):'." + _REGRAS)
    txt, _ = await llm_pool.chat("Você é um redator profissional. Responda só JSON válido.", user,
                                 max_tokens=2500, temperature=0.6)
    dados = freelas._json(txt)
    if not isinstance(dados, list) or len(dados) < 2:
        raise RuntimeError("IA não devolveu as amostras")
    skills = [["article-writing", "proofreading"], ["translation-1", "proofreading"]]
    out = []
    for d, sk in zip(dados[:2], skills):
        texto = str(d.get("texto", "")).strip()
        out.append({"name": ("Amostra: " + str(d.get("nome", "")).strip())[:90],
                    "description": ("Amostra de escrita (projeto próprio, não é trabalho de cliente). "
                                    "Feita com apoio de IA e revisada.\n\n" + texto)[:4000],
                    "skills": sk})
    return out


# ------------------------------------------------------------------ aplicar no Workana
async def completar(aplicar: bool = True) -> dict[str, Any]:
    reg = _registro()
    log: list[str] = []
    async with _cliente() as cx:
        url, ini, csrf = await _pagina(cx)
        antes = secoes(ini)
        h = lambda: _hdr(cx, csrf, url)  # noqa: E731  (x-dcst muda a cada resposta)
        nome = str(ini.get("companyVisibleName", "")).split(" ")[0].capitalize() or "Victor"

        # 1) descrição
        box = ini["commonBoxInitials"]["description"]
        if not (box.get("rawText") or "").strip():
            bio = reg.get("bio") if reg.get("bio") and not _limpo(reg["bio"]) else await _com_checagem(_escrever_bio, nome)
            reg["bio"] = bio
            if aplicar:
                r = await cx.put(box["editUrl"], headers=h(), json={box.get("section", "description"): bio})
                log.append(f"descrição: HTTP {r.status_code}")
                if r.status_code >= 400:
                    log.append(r.text[:200])

        # 2) habilidades (mantém as que já existem)
        ws = ini["workerSkillData"]
        tem = {row["slug"]: row.get("years_experience", EXPERIENCIA) for row in ws.get("rows", [])}
        novas = [{"slug": s, "name": n, "experience": EXPERIENCIA} for s, n in HABILIDADES if s not in tem]
        if novas and aplicar:
            corpo = novas + [{"slug": s, "experience": e} for s, e in tem.items()]
            r = await cx.put(ws["misc"]["updateSkillsUrl"], headers=h(), json=corpo)
            log.append(f"habilidades +{len(novas)}: HTTP {r.status_code}")
            if r.status_code >= 400:
                log.append(r.text[:200])

        # 3) portfólio (amostras rotuladas)
        pi = ini["portfolioInitials"]
        r = await cx.get(pi["getPortfoliosUrl"], headers=h())
        try:
            itens = r.json()
            itens = itens.get("items", itens.get("portfolios", itens)) if isinstance(itens, dict) else itens
        except Exception:
            itens = []
        if not itens:
            amostras = reg.get("amostras")
            if not amostras or _limpo(" ".join(a["description"] for a in amostras)):
                amostras = await _com_checagem(_escrever_amostras)
            reg["amostras"] = amostras
            if aplicar:
                for a in amostras:
                    corpo = {**a, "date_from": time.strftime("%m-%Y"), "images": {"cover": [], "gallery": []},
                             "pdfs": []}
                    r = await cx.post(pi["addModal"]["ctas"]["success"]["link"], headers=h(), json=corpo)
                    log.append(f"portfólio '{a['name'][:40]}': HTTP {r.status_code}")
                    if r.status_code >= 400:
                        log.append(r.text[:200])

        # 4) histórico profissional — SÓ o fato verdadeiro: autônomo desde que abriu a conta
        if not ini["commonBoxInitials"].get("experienceList", {}).get("items") and aplicar:
            corpo = {"position": "Redator, revisor e tradutor freelancer", "company": "Autônomo",
                     "startAt": time.strftime("%Y-%m-01"), "endAt": None, "currentlyWorkingHere": True,
                     "description": ("Início da atuação como freelancer: redação de artigos e posts, revisão de "
                                     "textos em português, tradução inglês-português e descrições de produto. "
                                     "Trabalho com ferramentas de IA e revisão cuidadosa antes da entrega.")}
            r = await cx.post(ini["commonBoxInitials"]["experienceForm"]["form"]["addUrl"], headers=h(), json=corpo)
            log.append(f"histórico: HTTP {r.status_code}")
            if r.status_code >= 400:
                log.append(r.text[:300])

        _, ini2, _ = await _pagina(cx)
        depois = secoes(ini2)
    reg.update({"ultimo": time.time(), "log": log, "antes": antes, "depois": depois})
    _guardar(reg)
    return {"antes": antes, "depois": depois, "log": log}
