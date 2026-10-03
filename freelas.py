"""💼 FREELAS (Workana) — a colônia acha vagas que CONSEGUE entregar e escreve a proposta.

Fluxo: buscar vagas (sessão do dono, só leitura, poucas vezes por dia) → filtro objetivo →
IA escolhe as melhores → IA escreve proposta honesta → resumo das 19h com ✅/❌ → (envio quando
o Workana liberar o perfil do dono) → entrega feita pela colônia, aprovada pelo dono.

Regras:
- Nada de trabalho acadêmico (TCC, dissertação, monografia…) — é fraude acadêmica.
- Nada que a colônia não entrega: áudio, vídeo, locução, design, reunião/chamada, vaga por hora.
- Proposta honesta: sem inventar experiência/portfólio; diz que usa IA com revisão.
- Sessão (cookie) do dono fica no backup CRIPTOGRAFADO; nunca no git.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

SESSAO = Path("data/workana_sessao.txt")
VAGAS = Path("data/freelas.json")
BASE = "https://www.workana.com"
BUSCAS = ["/jobs?language=pt&category=writing-translation",
          "/jobs?language=pt&category=writing-translation&page=2",
          "/jobs?language=pt&category=sales-marketing",
          "/jobs?language=pt&category=admin-support"]
ESTADO = Path("data/workana_estado.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
GAP_BUSCA_S = 15 * 60
MAX_PROPOSTAS_DIA = 3

_FORA = re.compile(
    r"\b(?:tcc|monografia|disserta[çc][ãa]o|teses?|artigo cient[íi]fico|acad[êe]mic[oa]s?|escrita acad[êe]mica|"
    r"faculdade|resenha acad[êe]mica|abnt|transcri[çc][ãa]o|transcrever|[áa]udios?|v[íi]deos?|reels|shorts|youtube|"
    r"locu[çc][ãa]o|narra[çc][ãa]o|podcasts?|design|designer|logotipo|canva|photoshop|ilustra[çc][ãa]o|"
    r"reuni[ãa]o|reuni[õo]es|chamadas?|presencial|telefone|atendimento|atendente|call center|ao vivo|"
    r"simult[âa]nea|int[ée]rprete|interpreta[çc][ãa]o|juramentada|"
    r"franc[êe]s|alem[ãa]o|espanhol|italiano|japon[êe]s|chin[êe]s|mandarim|russo|coreano|[áa]rabe|"
    r"gerenciar redes|social media manager|ghost ?writer de livro inteiro|"
    r"reviews?|avalia[çc](?:ão|ões) (?:de|sobre) produtos|opini(?:ão|ões) sobre produtos|"
    r"coment[áa]rios? (?:positivos|em massa)|seguidores|curtidas)\b", re.I)


# ------------------------------------------------------------------ sessão
def cookie() -> str:
    try:
        return SESSAO.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def salvar_cookie(valor: str) -> None:
    SESSAO.parent.mkdir(parents=True, exist_ok=True)
    SESSAO.write_text(valor.strip(), encoding="utf-8")
    try:
        SESSAO.chmod(0o600)
        __import__("state_backup").sujo()
    except Exception:
        pass


def _hdr(json_: bool = True) -> dict:
    h = {"Cookie": cookie(), "User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}
    if json_:
        h.update({"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/plain, */*"})
    return h


async def sessao_ok() -> bool:
    if not cookie():
        return False
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cx:
            r = await cx.get(f"{BASE}/dashboard", headers=_hdr(False))
        return r.status_code == 200 and "/login" not in str(r.url) and "logout" in r.text.lower()
    except Exception:
        return False


# ------------------------------------------------------------------ vagas
def ler() -> list[dict]:
    try:
        return json.loads(VAGAS.read_text(encoding="utf-8"))
    except Exception:
        return []


def _salvar(itens: list[dict]) -> None:
    VAGAS.parent.mkdir(parents=True, exist_ok=True)
    VAGAS.write_text(json.dumps(itens[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


def _txt(v: Any) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", str(v or "")))).strip()


def _num(s: Any) -> int:
    m = re.search(r"(\d+)", str(s if s is not None else ""))
    return int(m.group(1)) if m else 0


def _orcamento(s: str) -> tuple[str, int]:
    """'R$ 260 - 500' → ('BRL', 260); 'USD 50 - 100' → ('USD', 50); 'Menos de R$ 50' → ('BRL', 0)."""
    moeda = "USD" if re.search(r"USD|US\$", s or "") else "BRL"
    nums = [int(x.replace(".", "")) for x in re.findall(r"\d[\d.]*", s or "")]
    return moeda, (min(nums) if nums and not re.search(r"menos", s or "", re.I) else 0)


def normalizar(j: dict) -> dict:
    moeda, minimo = _orcamento(str(j.get("budget", "")))
    skills = j.get("skills") or []
    if isinstance(skills, str):
        skills = re.findall(r"'anchorText': '([^']+)'", skills)
    else:
        skills = [s.get("anchorText", "") for s in skills if isinstance(s, dict)]
    return {"slug": j.get("slug", ""), "titulo": _txt(j.get("title")), "descricao": _txt(j.get("description"))[:1500],
            "orcamento": _txt(j.get("budget")), "moeda": moeda, "minimo": minimo,
            "propostas": _num(j.get("totalBids")), "publicado": _txt(j.get("postedDate")),
            "por_hora": str(j.get("isHourly")).lower() == "true",
            "pagamento_verificado": str(j.get("hasVerifiedPaymentMethod")).lower() == "true",
            "skills": skills, "url": f"{BASE}/job/{j.get('slug', '')}"}


def filtro_objetivo(v: dict) -> str:
    """A colônia olha a vaga. Sem filtro de fora."""
    return ""


async def buscar() -> list[dict]:
    novas, conhecidas = [], {v["slug"] for v in ler()}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cx:
        for q in BUSCAS:
            r = await cx.get(BASE + q, headers=_hdr())
            if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                raise RuntimeError(f"Workana respondeu {r.status_code} (sessão expirou?)")
            res = r.json().get("results", {})
            res = res.get("results", []) if isinstance(res, dict) else res
            for j in res:
                v = normalizar(j)
                if v["slug"] and v["slug"] not in conhecidas:
                    conhecidas.add(v["slug"])
                    v["visto"] = time.time()
                    v["motivo"] = filtro_objetivo(v)
                    v["status"] = "descartada" if v["motivo"] else "candidata"
                    novas.append(v)
    itens = ler() + novas
    _salvar(itens)
    return novas


# ------------------------------------------------------------------ IA: escolher + propor
def _json(txt: str) -> Any:
    i, j = min([p for p in (txt.find("["), txt.find("{")) if p >= 0] or [-1]), max(txt.rfind("]"), txt.rfind("}"))
    return json.loads(txt[i:j + 1]) if i >= 0 and j > i else {}


async def escolher(max_escolhas: int = 3) -> list[dict]:
    """IA ranqueia as candidatas: só fica o que dá pra entregar SÓ com texto, bem feito."""
    import llm_pool

    itens = ler()
    cands = [v for v in itens if v["status"] == "candidata"][-12:]
    if not cands:
        return []
    lista = "\n".join(f"{i}. [{v.get('plataforma', 'workana')}] {v['titulo']} | {v['orcamento']} | {v['propostas']} propostas | "
                      f"{v['descricao'][:350]}" for i, v in enumerate(cands))
    user = ("Vagas de freelance (Workana). Nossa equipe entrega SÓ TEXTO feito por IA com revisão: artigos, "
            "revisão/correção, tradução PT↔EN, descrições de produto, copy de anúncio, posts, e-mails, roteiros "
            "escritos. NÃO fazemos: acadêmico, áudio/vídeo, design, reuniões, trabalho contínuo por hora, nada que "
            "exija conhecimento técnico que possa causar dano (jurídico/médico/financeiro assinados), NEM reviews/avaliações/"
            "opiniões de produtos (não usamos os produtos: seria avaliação falsa).\n"
            f"{lista}\n\nPara cada vaga dê nota 0-10 de CHANCE de entregarmos com excelência e sermos escolhidos. "
            'Responda SOMENTE JSON: [{"i": n, "nota": 0-10, "motivo": "curto", "prazo_dias": n, '
            '"preco_sugerido": inteiro na moeda da vaga}]')
    txt, _ = await llm_pool.chat("Você é um freelancer sênior realista e criterioso. Responda só JSON.",
                                 user, max_tokens=1500, temperature=0.2)
    try:
        notas = _json(txt)
    except Exception:
        notas = []
    if isinstance(notas, dict):     # às vezes vem {"vagas": [...]}
        notas = next((x for x in notas.values() if isinstance(x, list)), [])
    notas = [n for n in notas if isinstance(n, dict)] if isinstance(notas, list) else []
    escolhidas = []
    for n in notas:
        try:
            v = cands[int(_num(n.get("i")) if not isinstance(n.get("i"), int) else n["i"])]
        except Exception:
            continue
        m = re.search(r"\d+(?:[.,]\d+)?", str(n.get("nota", "0")))
        v["nota"] = float(m.group(0).replace(",", ".")) if m else 0.0
        v["motivo_ia"] = str(n.get("motivo", ""))[:160]
        v["prazo_dias"] = _num(n.get("prazo_dias")) or 3
        v["preco_sugerido"] = _num(str(n.get("preco_sugerido", "")).replace(".", "")) or v["minimo"]
        corte = 8 if v.get("plataforma") == "99freelas" else 7        # 99: cada proposta custa 3 conexões
        v["status"] = "escolhida" if v["nota"] >= corte else "descartada"
        if v["status"] == "descartada":
            v["motivo"] = f"IA deu nota {v['nota']:.0f}: {v['motivo_ia']}"
    for v in cands:   # a IA não citou → não serve
        if v["status"] == "candidata":
            v["status"], v["motivo"] = "descartada", "IA não recomendou"
    escolhidas = sorted([v for v in cands if v["status"] == "escolhida"], key=lambda x: -x["nota"])[:max_escolhas]
    for v in cands:
        if v["status"] == "escolhida" and v not in escolhidas:
            v["status"], v["motivo"] = "descartada", "fora do top do dia"
    _salvar(itens)
    return escolhidas


async def escrever_proposta(v: dict) -> str:
    import llm_pool

    user = (f"Vaga: {v['titulo']}\nOrçamento: {v['orcamento']}\nDescrição: {v['descricao']}\n\n"
            f"Escreva a proposta (português do Brasil, 90-160 palavras) para esta vaga no Workana. Regras: "
            "comece pelo problema do cliente (não por 'Olá, meu nome é'); diga em 3-4 passos concretos COMO "
            f"vai fazer; prazo {v.get('prazo_dias', 3)} dias; ofereça uma amostra curta grátis (1 parágrafo) "
            "para ele avaliar; termine com UMA pergunta objetiva sobre o projeto. Honestidade: perfil novo, sem "
            "avaliações ainda — NÃO invente experiência, clientes, portfólio ou números. Diga de forma natural "
            "que trabalha com ferramentas de IA e revisão humana cuidadosa. Sem emojis. Só o texto da proposta.")
    txt, _ = await llm_pool.chat("Você escreve propostas de freelance curtas, específicas e honestas.",
                                 user, max_tokens=900, temperature=0.5)
    return sem_emoji(re.sub(r"\n{3,}", "\n\n", txt.strip()))[:1800]


def estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salvar_estado(d: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


async def checar_liberacao() -> bool | None:
    """True = Workana já deixa mandar proposta. Guarda quando liberou (p/ avisar o dono 1 vez)."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cx:
            r = await cx.get(f"{BASE}/jobs?language=pt", headers=_hdr(False))
        if "logout" not in r.text.lower():
            return None
        em_revisao = "perfil est\\u00e1 em revis" in r.text or "perfil está em revis" in r.text
    except Exception:
        return None
    est = estado()
    est["em_revisao"], est["checado"] = em_revisao, time.time()
    if not em_revisao and not est.get("liberado_em"):
        est["liberado_em"] = time.time()
    _salvar_estado(est)
    return not em_revisao


async def ciclo() -> dict[str, Any]:
    """1 rodada: busca → filtra → escolhe → escreve propostas. Respeita o intervalo entre buscas."""
    import freelas99

    if not cookie() and not freelas99.cookie():
        return {"ok": False, "motivo": "sem sessão do Workana nem do 99Freelas"}
    novas, erros = [], []
    if cookie():
        await checar_liberacao()
        try:
            novas += await buscar()
        except Exception as exc:
            erros.append(f"Workana: {exc}")
    if freelas99.cookie():
        try:
            novas += await freelas99.buscar()
        except Exception as exc:
            erros.append(f"99Freelas: {exc}")
    feitas = sum(1 for v in ler() if v.get("proposta") and time.time() - v.get("proposta_em", 0) < 86400)
    try:
        esc = await escolher(max(0, MAX_PROPOSTAS_DIA - feitas)) if feitas < MAX_PROPOSTAS_DIA else []
    except Exception as exc:
        return {"ok": False, "novas": len(novas), "motivo": f"IA falhou ao escolher: {type(exc).__name__}: {str(exc)[:160]}"}
    for v in esc:
        try:
            v["proposta"] = await escrever_proposta(v)
            v["proposta_em"] = time.time()
            v["status"] = "aguardando_dono"
        except Exception as exc:
            v["status"], v["motivo"] = "candidata", f"proposta falhou: {type(exc).__name__}"
    itens = ler()
    por_slug = {v["slug"]: v for v in esc}
    itens = [por_slug.get(v["slug"], v) for v in itens]
    _salvar(itens)
    return {"ok": True, "novas": len(novas), "descartadas": sum(1 for v in novas if v["status"] == "descartada"),
            "propostas": len([v for v in esc if v.get("proposta")]), "erros": erros}


def sem_emoji(txt: str) -> str:
    txt = re.sub(r"([0-9])\ufe0f?\u20e3", r"\1.", txt or "")                  # 1️⃣ → 1.
    txt = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\ufe0f]", "", txt)
    return re.sub(r"[ \t]+\n", "\n", txt).strip()


def pendentes() -> list[dict]:
    """Propostas p/ o resumo. O filtro roda de novo: regra nova vale até p/ proposta já escrita."""
    itens, mudou, out = ler(), False, []
    for v in itens:
        if v.get("status") != "aguardando_dono" or v.get("notificado"):
            continue
        if v.get("proposta") and sem_emoji(v["proposta"]) != v["proposta"]:
            v["proposta"], mudou = sem_emoji(v["proposta"]), True
        motivo = filtro_objetivo(v)
        if motivo:
            v["status"], v["motivo"], mudou = "descartada", motivo, True
        else:
            out.append(v)
    if mudou:
        _salvar(itens)
    return out


def marcar(slug_ini: str, status: str) -> dict | None:
    itens = ler()
    alvo = next((v for v in itens if v["slug"].startswith(slug_ini)), None)
    if alvo:
        alvo["status"] = status
        alvo[f"{status}_em"] = time.time()
        _salvar(itens)
    return alvo


def status() -> dict[str, Any]:
    itens = ler()
    cont: dict[str, int] = {}
    for v in itens:
        cont[v["status"]] = cont.get(v["status"], 0) + 1
    est = estado()
    return {"sessao": bool(cookie()), "perfil_em_revisao": est.get("em_revisao"),
            "liberado_em": est.get("liberado_em"), "vagas_vistas": len(itens), "por_status": cont,
            "aguardando_dono": [{"titulo": v["titulo"], "orcamento": v["orcamento"], "nota": v.get("nota"),
                                 "url": v["url"], "proposta": v.get("proposta", "")} for v in pendentes()],
            "descartes_recentes": [f"{v['titulo'][:60]} — {v.get('motivo', '')[:90]}"
                                   for v in itens if v["status"] == "descartada"][-10:]}
