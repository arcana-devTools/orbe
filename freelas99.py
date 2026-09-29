"""💼 99FREELAS — mesma lógica do Workana (freelas.py), mas aqui já dá pra ENVIAR proposta.

- Sem revisão de perfil; proposta custa 3 conexões (plano grátis: 10/mês + 10 bônus ao completar perfil).
- Projetos "exclusivos" (< 24h) só aceitam Premium → a colônia ignora e pega quando abrirem.
- Endpoints (JS do site): POST JSON /services/user/editarPerfil  •  POST JSON /services/project/enviarProposta
- Sessão do dono: data/99_sessao.txt (backup criptografado; nunca no git).
- Honestidade: perfil e propostas passam pela mesma checagem do perfil do Workana.
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

SESSAO = Path("data/99_sessao.txt")
BASE = "https://www.99freelas.com.br"
BUSCAS = ["/projects?categoria=escrita", "/projects?categoria=escrita&page=2", "/projects?categoria=traducao"]
CUSTO_CONEXOES = 3
TITULO = "Redator, revisor e tradutor (inglês ↔ português)"
HABILIDADES = [231, 733, 18, 1878, 1876, 1260, 1388, 1785]   # Redação de Artigos, Revisão de Texto, Tradução,
#   Redação de Conteúdo, Redação de Blogs, Descrição de Produtos, Escrita para Web, Português (Brasil)
AREAS = [31, 33, 35, 125]                                      # Redação, Edição & Revisão, Tradução-Inglês, Copywriting
EXPERIENCIA = ("Comecei a atuar como freelancer em 2026, com redação de artigos e posts, revisão de textos em "
               "português, tradução inglês-português e descrições de produto. Trabalho com ferramentas de IA e "
               "faço revisão cuidadosa antes de cada entrega.")


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


def _cliente() -> httpx.AsyncClient:
    jar = httpx.Cookies()
    for par in cookie().split(";"):
        if "=" in par:
            k, v = par.split("=", 1)
            jar.set(k.strip(), v.strip(), domain="www.99freelas.com.br")
    return httpx.AsyncClient(timeout=40, follow_redirects=True, cookies=jar,
                             headers={"User-Agent": freelas.UA, "Accept-Language": "pt-BR,pt;q=0.9"})


def _json_hdr(ref: str) -> dict:
    return {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/plain, */*; q=0.01", "Origin": BASE, "Referer": ref}


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


async def painel() -> dict[str, Any]:
    """Logado? conexões disponíveis? % do perfil?"""
    async with _cliente() as cx:
        t = (await cx.get(f"{BASE}/dashboard")).text
    v = _txt(t)
    con = re.search(r"Conexões disponíveis:\s*(\d+)", v)
    pct = re.search(r"Perfil preenchido \((\d+)%\)", v)
    return {"logado": "/logout" in t, "conexoes": int(con.group(1)) if con else None,
            "perfil_pct": int(pct.group(1)) if pct else 100}


# ------------------------------------------------------------------ vagas
def _itens(t: str) -> list[dict]:
    out = []
    for li in re.findall(r'(<li class="[^"]*result-item.*?)(?=<li class="[^"]*result-item|</ul>)', t, re.S):
        idp = re.search(r'data-id="(\d+)"', li)
        href = re.search(r'href="(/project/[^"?]+)', li)
        if not idp or not href:
            continue
        info = _txt((re.search(r'class="item-text information">(.*?)</hgroup>', li, re.S) or [None, ""])[1])
        desc = re.search(r'data-content="([^"]*)"', li)
        titulo = re.search(r'data-nome="([^"]*)"', li)
        partes = [p.strip() for p in info.split("|")]
        out.append({"slug": f"99-{idp.group(1)}", "id99": int(idp.group(1)), "plataforma": "99freelas",
                    "titulo": _html.unescape(titulo.group(1)) if titulo else "",
                    "descricao": _txt(desc.group(1) if desc else "")[:1500],
                    "orcamento": "Aberto (99Freelas)", "moeda": "BRL", "minimo": 0,
                    "propostas": freelas._num((re.search(r"Propostas:\s*(\d+)", info) or [None, "0"])[1]),
                    "publicado": "", "por_hora": False, "pagamento_verificado": False,
                    "skills": partes[:1], "nivel": partes[1] if len(partes) > 1 else "",
                    "exclusivo": "exclusive" in li, "url": BASE + href.group(1)})
    return out


async def buscar() -> list[dict]:
    """Projetos novos de Escrita/Tradução. Exclusivos ficam de fora (voltam quando abrirem)."""
    itens = freelas.ler()
    conhecidas = {v["slug"] for v in itens}
    novas = []
    async with _cliente() as cx:
        for q in BUSCAS:
            r = await cx.get(BASE + q)
            if "/logout" not in r.text:
                raise RuntimeError("sessão do 99Freelas expirou")
            for v in _itens(r.text):
                if v["exclusivo"] or v["slug"] in conhecidas:
                    continue
                conhecidas.add(v["slug"])
                v["visto"] = time.time()
                v["motivo"] = freelas.filtro_objetivo(v) or ("concorrência alta (30+ propostas)"
                                                              if v["propostas"] >= 30 else "")
                v["status"] = "descartada" if v["motivo"] else "candidata"
                novas.append(v)
    freelas._salvar(itens + novas)
    return novas


# ------------------------------------------------------------------ enviar proposta (só com ✅ do dono)
async def enviar(v: dict) -> dict[str, Any]:
    async with _cliente() as cx:
        url_bid = v["url"].replace("/project/", "/project/bid/")
        t = (await cx.get(url_bid)).text
        if 'id="proposta"' not in t:
            return {"ok": False, "motivo": "o 99Freelas não mostrou o formulário (projeto fechado/exclusivo?)"}
        minimo = int((re.search(r'data-min="(\d+)"', t) or [None, "1000"])[1])
        oferta = max(v.get("preco_sugerido") or 0, minimo / 100, 10)
        corpo = {"idProjeto": v["id99"], "isAdmin": False, "oferta": f"{oferta:.2f}",
                 "oferta_htmlid": "oferta", "duracaoEstimada": int(v.get("prazo_dias") or 3),
                 "duracaoEstimada_htmlid": "duracao-estimada", "proposta": v.get("proposta", "")[:3000],
                 "proposta_htmlid": "proposta", "promover": False, "promover_htmlid": "promover",
                 "confirmarAcao": True, "confirmarAcao_htmlid": "confirmar-envio-proposta",
                 "novaProposta": True, "valorMinimoCents": minimo}
        r = await cx.post(f"{BASE}/services/project/enviarProposta", headers=_json_hdr(url_bid),
                          content=json.dumps(corpo))
    d = resposta(r.text)
    ok = r.status_code == 200 and (d.get("status") or {}).get("id") == 1
    return {"ok": ok, "http": r.status_code, "resposta": d, "oferta": oferta}


def resposta(txt: str) -> dict:
    """O 99Freelas responde JSON url-encoded: %7B%22status%22%3A%7B%22id%22%3A1%7D... (id 1 = sucesso)."""
    from urllib.parse import unquote_plus

    for cand in (txt, unquote_plus(txt or "")):
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {"raw": (txt or "")[:300]}


# ------------------------------------------------------------------ perfil
async def completar_perfil(aplicar: bool = True) -> dict[str, Any]:
    import perfil_workana as PW

    reg = PW._registro()
    antes = await painel()
    log: list[str] = []
    async with _cliente() as cx:
        t = (await cx.get(f"{BASE}/profile/edit")).text
        nome = _html.unescape((re.search(r'id="nome"[^>]*value="([^"]*)"', t) or
                               re.search(r'value="([^"]*)"[^>]*id="nome"', t) or [None, ""])[1])
        nick = (re.search(r'id="nickname"[^>]*value="([^"]*)"', t) or
                re.search(r'value="([^"]*)"[^>]*id="nickname"', t) or [None, ""])[1]
        titulo = _html.unescape((re.search(r'id="titulo-profissional"[^>]*value="([^"]*)"', t) or [None, ""])[1])
        sobre = _txt((re.search(r'<textarea id="descricao"[^>]*>(.*?)</textarea>', t, re.S) or [None, ""])[1])
        resumo = _txt((re.search(r'<textarea id="resumo-experiencia-profissional"[^>]*>(.*?)</textarea>', t, re.S)
                       or [None, ""])[1])
        tipo = int((re.search(r'info-id-tipo-usuario"[^>]*value="(\d+)"', t) or [None, "2"])[1])
        hab = [int(x) for x in re.findall(r"\d+", (re.search(r"habilidadesDoFreelancer\s*=\s*\[([^\]]*)\]", t)
                                                   or [None, ""])[1])]
        areas = [int(x) for x in re.findall(r'id="chk(\d+)"[^>]*checked', t)]
        if len(nome) < 6:
            return {"ok": False, "motivo": "nome público com menos de 6 letras — o dono precisa ajustar no site"}
        if not sobre:
            bio = reg.get("bio99")
            if not bio or PW._limpo(bio):
                bio = await PW._com_checagem(_bio, nome.split(" ")[0])
            reg["bio99"] = bio
            sobre = bio
        corpo = {"tipoUsuario": {"id": tipo}, "nome": nome, "nome_htmlid": "nome", "nickname": nick,
                 "nickname_htmlid": "nickname", "tituloProfissional": titulo or TITULO,
                 "tituloProfissional_htmlid": "titulo-profissional", "sobreMim": sobre, "sobreMim_htmlid": "descricao",
                 "resumoExperienciaProfissional": resumo or EXPERIENCIA,
                 "resumoExperienciaProfissional_htmlid": "resumo-experiencia-profissional",
                 "habilidades": hab or HABILIDADES, "habilidades_htmlid": "habilidades",
                 "areasDeInteresse": areas or AREAS, "areasDeInteresse_htmlid": "areas-interesse",
                 "editarComoModerador": False}
        precisa = not (titulo and resumo and hab and areas) or corpo["sobreMim"] != _txt(
            (re.search(r'<textarea id="descricao"[^>]*>(.*?)</textarea>', t, re.S) or [None, ""])[1])
        if precisa and aplicar:
            r = await cx.post(f"{BASE}/services/user/editarPerfil", headers=_json_hdr(f"{BASE}/profile/edit"),
                              content=json.dumps(corpo))
            ok = (resposta(r.text).get("status") or {}).get("id") == 1
            log.append(f"perfil: {'salvo' if ok else 'FALHOU'} (HTTP {r.status_code}) {'' if ok else r.text[:160]}")
    PW._guardar(reg)
    depois = await painel()
    return {"antes": antes, "depois": depois, "log": log}


async def _bio(nome: str) -> str:
    import llm_pool
    import perfil_workana as PW

    user = (f"Escreva o 'Conte-nos sobre você' do perfil de freelancer no 99Freelas de {nome}, brasileiro "
            "(Santa Catarina). FATOS (use só estes): começando agora como freelancer, sem avaliações ainda; "
            "serviços: redação de artigos e posts de blog, revisão/correção de textos em português, tradução "
            "inglês↔português, descrições de produto; usa ferramentas de inteligência artificial e revisa tudo "
            "com cuidado antes de entregar; oferece uma amostra curta grátis; responde rápido; até 2 rodadas de "
            "ajustes. PROIBIDO inventar anos de experiência, clientes, empresas, formação, números ou resultados, "
            "e PROIBIDO informar contato, e-mail, telefone ou links. 120-180 palavras, 3 parágrafos curtos + lista "
            "de 4 serviços com '- '. Sem emojis, sem título. Só o texto." + PW._REGRAS)
    txt, _ = await llm_pool.chat("Você escreve perfis de freelancer honestos que convertem.", user,
                                 max_tokens=900, temperature=0.5)
    return txt.strip()[:4500]
