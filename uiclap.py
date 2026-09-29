"""📚 UICLAP — publicar livro físico (impressão sob demanda) na conta do dono.

Fluxo (mapeado do portal.uiclap.com; API /data/v2 + process.uiclap.com):
  1. doc/info/0            → cria o rascunho (título, autor, sinopse, categoria BISAC) e devolve o id
  2. uploadticket/m/<id>   → URL assinada; PUT do PDF; POST process/v2/cont/ups/ → páginas, tamanho, lombada
     doc/miolov2/<id>      → salva o miolo
  3. ticket/c/<id>         → ticket; POST process/capa/upso/ (JPG da capa inteira); doc/capa/<id>
  4. doc/finaliza/<id>     → vira título (idLivro)   [exige contrato de autor aceito PELO DONO]
  5. titulo/publica/<idLivro> {valorAutor} → à venda na loja UICLAP

Sessão: refreshToken do Firebase (login Google do dono), no cofre criptografado `uiclap`.
Transparência: o portal manda um cabeçalho de App Check "falhou" quando o navegador não consegue gerar o
token anti-robô — usamos o mesmo fallback. Se o UICLAP fechar isso, este módulo para (e avisa).
Publicar (passos 4-5) SÓ acontece depois do ✅ do dono no resumo diário.
"""
from __future__ import annotations

import html as _html
import io
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

API = "https://portal.uiclap.com/data/v2/"
PROC = "https://process.uiclap.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
LARGURA_MM, ALTURA_MM = 140, 210          # 14x21 cm: formato de livro mais comum/barato
SANGRIA_MM = 5
DPI_CAPA = 300
_tok: dict[str, Any] = {"id": "", "exp": 0.0}


class UiclapErro(RuntimeError):
    pass


LOGIN_ARQ = Path("data/uiclap_login.json")   # no Render: vai no backup criptografado (como a sessão do 99)


def credencial() -> dict | None:
    try:
        from secrets_vault import VAULT

        e = (VAULT.get("uiclap") or {}).get("extra")
        if e:
            return e
    except Exception:
        pass
    try:
        return json.loads(LOGIN_ARQ.read_text(encoding="utf-8")) or None
    except Exception:
        return None


def guardar_login_servidor(extra: dict) -> None:
    faltam = [k for k in ("refreshToken", "apiKey", "uid", "user", "fbase_key") if not extra.get(k)]
    if faltam:
        raise UiclapErro("faltam campos: " + ", ".join(faltam))
    LOGIN_ARQ.parent.mkdir(parents=True, exist_ok=True)
    LOGIN_ARQ.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
    _tok.update(id="", exp=0)
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


def salvar_credencial(bruto: str) -> dict:
    """Aceita o que o dono copia do navegador (JSON do firebaseLocalStorage, com ou sem lixo em volta)."""
    from secrets_vault import VAULT

    i = bruto.find("[{")
    if i < 0:
        i = bruto.find("{")
    dado, _ = json.JSONDecoder().raw_decode(bruto[i:])
    item = dado[0] if isinstance(dado, list) else dado
    v = item.get("value", item)
    sts = v["stsTokenManager"]
    VAULT.put("uiclap", username=v.get("email", ""),
              extra={"refreshToken": sts["refreshToken"], "apiKey": v["apiKey"], "uid": v["uid"]})
    _tok.update(id="", exp=0)
    return {"email": v.get("email", ""), "uid": v["uid"]}


async def _token() -> str:
    if _tok["id"] and time.time() < _tok["exp"] - 120:
        return _tok["id"]
    c = credencial()
    if not c:
        raise UiclapErro("sem login do UICLAP no cofre")
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.post(f"https://securetoken.googleapis.com/v1/token?key={c['apiKey']}",
                          data={"grant_type": "refresh_token", "refresh_token": c["refreshToken"]},
                          headers={"Referer": "https://portal.uiclap.com/"})
    if r.status_code != 200:
        raise UiclapErro(f"login do UICLAP expirou ({r.status_code}) — o dono precisa mandar de novo")
    d = r.json()
    _tok.update(id=d["id_token"], exp=time.time() + int(d.get("expires_in", 3600)))
    return _tok["id"]


async def _hdr(ref: str = "https://portal.uiclap.com/") -> dict:
    return {"Authorization": "Bearer " + await _token(), "X-Firebase-AppCheck": "appCheck/fetch-status-error (403)",
            "User-Agent": UA, "Referer": ref, "Origin": "https://portal.uiclap.com",
            "Accept": "application/json, text/plain, */*"}


async def api(caminho: str, metodo: str = "GET", corpo: Any = None, ref: str = "https://portal.uiclap.com/") -> Any:
    async with httpx.AsyncClient(timeout=90) as cx:
        r = await cx.request(metodo, API + caminho, headers=await _hdr(ref),
                             json=corpo if corpo is not None and not isinstance(corpo, str) else None,
                             content=corpo if isinstance(corpo, str) else None)
    if r.status_code in (401, 403, 418):
        raise UiclapErro(f"UICLAP recusou ({r.status_code}) em {caminho}")
    if r.status_code == 404 and metodo != "GET":
        raise UiclapErro(f"UICLAP respondeu 404 em {caminho} (acontece quando o contrato de autor não foi aceito)")
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return r.text


def _ok(d: Any, etapa: str) -> int:
    ret = d.get("retorno", 0) if isinstance(d, dict) else 0
    if ret <= 0:
        msg = {-1: "usuário não existe", -2: "documento não existe", -3: "documento não editável"}.get(ret, "")
        raise UiclapErro(f"{etapa}: retorno {ret} {msg} {str(d)[:160]}")
    return ret


async def status() -> dict[str, Any]:
    info = await api("user/info/?h=")
    titulos = await api("titulos")
    return {"nome": info.get("nome"), "contrato_ok": bool(info.get("isContratoOk")),
            "titulos": titulos if isinstance(titulos, list) else [], "tipo": info.get("tipo")}


# ------------------------------------------------------------------ passos do portal
async def exigir_contrato() -> None:
    if not (await api("user/info/?h=")).get("isContratoOk"):
        raise UiclapErro("o dono ainda não aceitou o contrato de autor no portal UICLAP")


async def criar_rascunho(info: dict) -> int:
    await exigir_contrato()
    base = await api("doc/0", ref="https://portal.uiclap.com/documento/0")
    doc = {**base["info"], "idioma": "pt_BR", "productType": "BOOK", "idade": 7, **info}
    return _ok(await api("doc/info/0", "POST", doc, "https://portal.uiclap.com/documento/0"), "info")


async def enviar_miolo(doc_id: int, pdf: bytes) -> dict:
    ref = f"https://portal.uiclap.com/documento/{doc_id}"
    t = await api(f"uploadticket/m/{doc_id}", ref=ref)
    _ok(t, "ticket do miolo")
    async with httpx.AsyncClient(timeout=180) as cx:
        r = await cx.put(t["url"], content=pdf, headers={"Content-Type": "application/pdf"})
        r.raise_for_status()
        p = await cx.post(PROC + "v2/cont/ups/", content="",
                          headers={"Authorization": "Ticket " + t["mensagem"], "User-Agent": UA,
                                   "Origin": "https://portal.uiclap.com", "Referer": ref})
    d = p.json()
    if d.get("r") != 0:
        raise UiclapErro(f"miolo recusado pelo processador: r={d.get('r')} m={d.get('m')} "
                         f"({d.get('w')}x{d.get('h')}mm)")
    doc = await api(f"doc/{doc_id}", ref=ref)
    car = doc["caracteristicas"]
    car.update(paginas=d["p"], lombada=d["l"], tamanhoInfo={"i": 0, "largura": d["w"], "altura": d["h"]})
    for _ in range(12):                        # o portal espera as miniaturas das páginas ficarem prontas
        try:
            _ok(await api(f"doc/miolov2/{doc_id}", "POST", car, ref), "salvar miolo")
            break
        except UiclapErro:
            await __import__("asyncio").sleep(10)
    else:
        raise UiclapErro("salvar miolo: o UICLAP não confirmou depois de 2 min")
    return {"paginas": d["p"], "lombada_mm": d["l"], "largura": d["w"], "altura": d["h"]}


async def enviar_capa(doc_id: int, jpg: bytes) -> None:
    ref = f"https://portal.uiclap.com/documento/{doc_id}"
    doc = await api(f"doc/{doc_id}", ref=ref)
    car = doc["caracteristicas"]
    car.update(temOrelha=False, larguraOrelha=0)
    t = await api(f"ticket/c/{doc_id}", "POST", car, ref)
    _ok(t, "ticket da capa")
    async with httpx.AsyncClient(timeout=180) as cx:
        r = await cx.post(PROC + "capa/upso/", files={"a": ("arq.jpg", jpg, "image/jpeg")},
                          data={"t": "image/jpeg"},
                          headers={"Authorization": "Ticket " + t["mensagem"], "User-Agent": UA,
                                   "Origin": "https://portal.uiclap.com", "Referer": ref})
    d = r.json()
    if d.get("r") != 0:
        raise UiclapErro(f"capa recusada: r={d.get('r')} m={d.get('m')}")
    car.update(temCapa=True, logoCapa={"tipo": 5, "posicao": 2}, logoLombada={"tipo": 8, "posicao": 2})
    _ok(await api(f"doc/capa/{doc_id}", "POST", car, ref), "salvar capa")


async def finalizar(doc_id: int) -> int:
    return _ok(await api(f"doc/finaliza/{doc_id}", "POST", "", f"https://portal.uiclap.com/documento/{doc_id}"),
               "finalizar")


async def publicar(id_livro: int, valor_autor: float) -> dict:
    ref = f"https://portal.uiclap.com/titulo/{id_livro}"
    t = await api(f"titulo/{id_livro}", ref=ref)
    corpo = {"acabamento": t.get("acabamento"), "isPrivado": False, "senha": "", "valorAutor": round(valor_autor, 2)}
    _ok(await api(f"titulo/publica/{id_livro}", "POST", corpo, ref), "publicar")
    return await api(f"titulo/{id_livro}", ref=ref)


async def excluir_rascunho(doc_id: int) -> Any:
    return await api(f"doc/{doc_id}", "DELETE", ref="https://portal.uiclap.com/titulos/edicao")


# ------------------------------------------------------------------ montar os arquivos do livro
CSS_MIOLO = """
@page { size: 140mm 210mm; margin: 18mm 15mm 18mm 17mm;
        @bottom-center { content: counter(page); font-size: 8.5pt; color: #666; } }
@page limpa { @bottom-center { content: none; } }
body { font-family: 'DejaVu Serif', 'Liberation Serif', serif; font-size: 10.5pt; line-height: 1.45; color: #111;
       text-align: justify; hyphens: auto; }
.rosto { page: limpa; text-align: center; padding-top: 45mm; page-break-after: always; }
.rosto h1 { font-size: 20pt; line-height: 1.2; margin: 0 0 6mm; } .rosto .sub { font-size: 11pt; color: #444; }
.rosto .aut { margin-top: 30mm; font-size: 11pt; }
.creditos { page: limpa; font-size: 8pt; color: #444; padding-top: 120mm; page-break-after: always; }
.sumario { page-break-after: always; } .sumario li { margin: 2px 0; }
h2 { font-size: 14pt; page-break-before: always; margin-top: 10mm; } h3 { font-size: 11.5pt; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #999; padding: 3px 4px; vertical-align: top; } th { background: #eee; }
blockquote { border-left: 3px solid #999; margin: 6px 0; padding: 2px 10px; color: #333; }
.branca { page: limpa; page-break-before: always; }
"""


def montar_miolo(titulo: str, subtitulo: str, autor: str, corpo_md: str) -> tuple[bytes, int]:
    """PDF 14x21 pronto para impressão. Nº de páginas múltiplo de 4 (o UICLAP arredonda para cima)."""
    import markdown
    from weasyprint import HTML

    import acabamento

    corpo = acabamento._sem_emoji(corpo_md)
    corpo = re.sub(r"(?im)^.*(reembolso|download|arquivo pdf|imprim[ai]r? (este|o) pdf).*$", "", corpo)
    corpo_html = markdown.markdown(corpo, extensions=["tables", "sane_lists"])
    sumario = "".join(f"<li>{_html.escape(re.sub(r'^\\d+[.)]?\\s*', '', t))}</li>"
                      for t in acabamento._titulos(corpo))
    ano = time.strftime("%Y")

    def _html_doc(brancas: int) -> str:
        return (f"<html lang='pt-BR'><head><meta charset='utf-8'><style>{CSS_MIOLO}</style></head><body>"
                f"<section class='rosto'><h1>{_html.escape(titulo)}</h1><div class='sub'>{_html.escape(subtitulo)}"
                f"</div><div class='aut'>{_html.escape(autor)}</div></section>"
                f"<section class='creditos'>{_html.escape(titulo)}<br>© {ano} {_html.escape(autor)}. "
                f"Todos os direitos reservados.<br>Publicação independente.</section>"
                f"<section class='sumario'><h3>Sumário</h3><ol>{sumario}</ol></section>{corpo_html}"
                + "<div class='branca'></div>" * brancas + "</body></html>")

    r = HTML(string=_html_doc(0)).render()
    faltam = (-len(r.pages)) % 4
    if faltam:
        r = HTML(string=_html_doc(faltam)).render()
    buf = io.BytesIO()
    r.write_pdf(buf)
    return buf.getvalue(), len(r.pages)


def montar_capa(titulo: str, subtitulo: str, autor: str, sinopse: str, lombada_mm: float,
                cor: str = "#1f3b73") -> bytes:
    """Capa inteira (4ª capa | lombada | 1ª capa) com 5 mm de sangria, JPG 300 dpi."""
    import pypdfium2 as pdfium
    from weasyprint import HTML

    W, H, S, L = LARGURA_MM, ALTURA_MM, SANGRIA_MM, float(lombada_mm)
    larg, alt = 2 * W + L + 2 * S, H + 2 * S
    lomb_txt = (f"<div class='lt'>{_html.escape(titulo[:60])}</div>" if L >= 6 else "")
    doc = f"""<html><head><meta charset='utf-8'><style>
@page {{ size: {larg}mm {alt}mm; margin: 0; }}
body {{ margin: 0; font-family: 'DejaVu Sans', sans-serif; }}
.f {{ position: absolute; top: 0; left: 0; width: {larg}mm; height: {alt}mm; background: {cor}; }}
.q4 {{ position: absolute; left: {S + 14}mm; top: {S + 22}mm; width: {W - 28}mm; color: #f2f2f2; font-size: 9.5pt;
       line-height: 1.45; text-align: justify; }}
.lo {{ position: absolute; left: {S + W}mm; top: {S}mm; width: {L}mm; height: {H}mm; background: rgba(0,0,0,.18); }}
.lt {{ position: absolute; left: {S + W + L / 2}mm; top: {S + H / 2}mm; transform: translate(-50%,-50%) rotate(90deg);
       white-space: nowrap; color: white; font-size: {min(9, max(5.5, L * 0.9)):.1f}pt; font-weight: bold; }}
.q1 {{ position: absolute; left: {S + W + L + 14}mm; top: {S + 48}mm; width: {W - 28}mm; color: white; }}
.q1 h1 {{ font-size: 23pt; line-height: 1.15; margin: 0 0 7mm; }}
.q1 .s {{ font-size: 11.5pt; line-height: 1.35; opacity: .93; }}
.q1 .a {{ position: absolute; top: {H - 48 - 38}mm; font-size: 12pt; letter-spacing: .5px; }}
.barra {{ position: absolute; left: {S + W + L + 14}mm; top: {S + 38}mm; width: 22mm; height: 1.6mm; background: #f5b83d; }}
</style></head><body><div class='f'></div>
<div class='q4'>{_html.escape(sinopse)}</div><div class='lo'></div>{lomb_txt}
<div class='barra'></div><div class='q1'><h1>{_html.escape(titulo)}</h1><div class='s'>{_html.escape(subtitulo)}</div>
<div class='a'>{_html.escape(autor)}</div></div></body></html>"""
    pdf = HTML(string=doc).write_pdf()
    pg = pdfium.PdfDocument(pdf)[0]
    img = pg.render(scale=DPI_CAPA / 72).to_pil().convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92, dpi=(DPI_CAPA, DPI_CAPA))
    return buf.getvalue()


# ------------------------------------------------------------------ navegador de verdade (teste do anti-robô)
async def testar_navegador(login_bruto: str) -> dict[str, Any]:
    """Abre o portal no Chrome do servidor com o login do dono e diz se o App Check (anti-robô) passou.
    Não guarda nada e não devolve tokens."""
    from browser import MANAGER

    i = login_bruto.find("[{")
    item = json.JSONDecoder().raw_decode(login_bruto[i:])[0][0]
    v = dict(item["value"])
    async with httpx.AsyncClient(timeout=30) as cx:
        r = (await cx.post(f"https://securetoken.googleapis.com/v1/token?key={v['apiKey']}",
                           data={"grant_type": "refresh_token",
                                 "refresh_token": v["stsTokenManager"]["refreshToken"]})).json()
    v["stsTokenManager"] = {"refreshToken": r["refresh_token"], "accessToken": r["id_token"],
                            "expirationTime": int(time.time() * 1000) + 3500 * 1000}
    reg = {"fbase_key": item["fbase_key"], "value": v}
    ctx = await MANAGER.context_for("uiclap")
    page = await ctx.new_page()
    vistos: list[str] = []
    page.on("request", lambda rq: vistos.append(rq.headers.get("x-firebase-appcheck", "")) if "/data/v2/" in rq.url else None)
    try:
        await page.goto("https://portal.uiclap.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await page.evaluate("""(reg) => new Promise((res, rej) => {
            const o = indexedDB.open('firebaseLocalStorageDb', 1);
            o.onupgradeneeded = () => o.result.createObjectStore('firebaseLocalStorage', {keyPath: 'fbase_key'});
            o.onsuccess = () => { const tx = o.result.transaction('firebaseLocalStorage', 'readwrite');
                tx.objectStore('firebaseLocalStorage').put(reg); tx.oncomplete = () => res(true); tx.onerror = () => rej(tx.error); };
            o.onerror = () => rej(o.error); })""", reg)
        await page.goto("https://portal.uiclap.com/conta", wait_until="domcontentloaded", timeout=90000)
        for _ in range(30):                       # Render é lento: espera o app carregar e chamar a API
            await page.wait_for_timeout(2000)
            if len(vistos) >= 2:
                break
        await page.wait_for_timeout(3000)
        titulo = await page.title()
        url = page.url
    finally:
        await page.close()
        await MANAGER.close_profile("uiclap")
    reais = [t for t in vistos if t.startswith("eyJ")]
    return {"logado": "login" not in url.lower(), "url": url, "titulo": titulo, "chamadas": len(vistos),
            "anti_robo_ok": bool(reais), "erros": sorted({t for t in vistos if not t.startswith("eyJ")})[:3]}


# ------------------------------------------------------------------ PLANO B: kit + favorito no Chrome do dono
# O anti-robô (App Check) do UICLAP recusa IP de servidor. Então o servidor só PREPARA o livro (kit) e um
# favorito no Chrome do dono faz o upload pelo próprio portal (IP de casa, navegador de verdade).
KITS = Path("data/uiclap_kits")
VALOR_AUTOR = 8.0            # R$ que o dono recebe por exemplar (o UICLAP soma custo de impressão + taxa)
_BISAC = [  # (palavras-chave, código, descrição) — categoria principal do livro
    (r"dinheiro|finan|investi|renda|or[çc]amento|d[íi]vida", "BUS050000", "NEGÓCIOS E ECONOMIA / Finanças Pessoais"),
    (r"neg[óo]cio|empreend|vend|marketing|cliente|empresa", "BUS000000", "NEGÓCIOS E ECONOMIA / Geral"),
    (r"receita|cozinh|culin", "CKB000000", "CULINÁRIA / Geral"),
    (r"sa[úu]de|dieta|exerc|sono|ansiedade", "HEA000000", "SAÚDE E BEM-ESTAR / Geral"),
    (r"filho|beb[êe]|crian[çc]a|fam[íi]lia|pais", "FAM000000", "FAMÍLIA E RELACIONAMENTOS / Geral"),
    (r"estud|concurso|enem|aprend|professor|aula", "EDU000000", "EDUCAÇÃO / Geral"),
    (r"computador|programa|excel|intelig[êe]ncia artificial|\bia\b|chatgpt|aplicativo", "COM000000",
     "COMPUTAÇÃO / Geral"),
    (r"deus|f[ée]|ora[çc][ãa]o|b[íi]blia", "REL000000", "RELIGIÃO / Geral"),
]


def token_favorito() -> str:
    import hashlib
    import os

    senha = os.environ.get("ORBE_PANEL_PASSWORD", "") or "local"
    return hashlib.sha256(("orbe-uiclap:" + senha).encode()).hexdigest()[:32]


def _kit_meta(kid: str) -> dict | None:
    try:
        return json.loads((KITS / kid / "kit.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def _kit_salvar(meta: dict) -> None:
    (KITS / meta["kid"]).mkdir(parents=True, exist_ok=True)
    (KITS / meta["kid"] / "kit.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def kits() -> list[dict]:
    out = [m for m in (_kit_meta(p.name) for p in KITS.glob("*")) if m]
    return sorted(out, key=lambda m: m.get("criado", 0))


def _categoria(texto: str) -> dict:
    for pat, cod, desc in _BISAC:
        if re.search(pat, texto, re.I):
            return {"bisac": cod, "descricao": desc}
    return {"bisac": "SEL000000", "descricao": "AUTOAJUDA / Geral"}


def criar_kit(titulo: str, subtitulo: str, autor: str, corpo_md: str, sinopse: str, palavras: list[str],
              origem: str = "", teste: bool = False, valor_autor: float = VALOR_AUTOR) -> dict:
    sinopse = re.sub(r"\s+", " ", re.sub(r"[#*_>`]|\[|\]\([^)]*\)", "", sinopse)).strip()
    if len(sinopse) < 200:
        sinopse = (sinopse + " " + re.sub(r"\s+", " ", re.sub(r"[#*_>`]", "", corpo_md))[:600]).strip()
    sinopse = sinopse[:1900].rsplit(" ", 1)[0] if len(sinopse) > 1900 else sinopse
    pdf, paginas = montar_miolo(titulo, subtitulo, autor, corpo_md)
    kid = time.strftime("%Y%m%d-%H%M%S") + ("-teste" if teste else "")
    (KITS / kid).mkdir(parents=True, exist_ok=True)
    (KITS / kid / "miolo.pdf").write_bytes(pdf)
    (KITS / kid / "corpo.md").write_text(corpo_md, encoding="utf-8")
    meta = {"kid": kid, "status": "pronto", "teste": teste, "criado": time.time(), "origem": origem,
            "paginas": paginas, "valor_autor": valor_autor,
            "info": {"titulo": titulo[:250], "subtitulo": subtitulo[:250], "autor": autor, "descricao": sinopse,
                     "pessoas": [{"tipo": "A", "nome": autor}],
                     "categorias": [_categoria(f"{titulo} {subtitulo} {sinopse}")],
                     "palavrasChave": [str(p)[:40] for p in palavras][:7]}}
    _kit_salvar(meta)
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass
    return meta


def kit_de_produto(pid: str, autor: str = "Victor") -> dict:
    """Produto PT aprovado pelo dono → kit de livro físico para o UICLAP."""
    import acabamento

    pasta = acabamento.PRODUTOS / pid
    meta = json.loads((pasta / "meta.json").read_text(encoding="utf-8"))
    corpo = (pasta / "produto.md").read_text(encoding="utf-8").split("\n", 2)[-1]
    venda = (pasta / "pagina_de_vendas.md").read_text(encoding="utf-8") if (pasta / "pagina_de_vendas.md").exists() else ""
    venda = re.split(r"(?im)^##\s*(o que voc[êe] recebe|reembolso|garantia)", venda)[0]
    venda = "\n".join(l for l in venda.splitlines()[1:] if not re.search(r"(?i)pdf|download|arquivo|pre[çc]o", l))
    return criar_kit(meta["titulo"], meta.get("subtitulo", ""), autor, corpo, venda, meta.get("tags", []), origem=pid)


def kit_miolo(kid: str) -> bytes:
    arq = KITS / kid / "miolo.pdf"
    if not arq.exists():                       # Render reiniciou: refaz o PDF a partir do texto guardado
        m = _kit_meta(kid)
        if not m or not (KITS / kid / "corpo.md").exists():
            raise UiclapErro("kit não existe")
        i = m["info"]
        pdf, _ = montar_miolo(i["titulo"], i.get("subtitulo", ""), i["autor"],
                              (KITS / kid / "corpo.md").read_text(encoding="utf-8"))
        arq.write_bytes(pdf)
    return arq.read_bytes()


def proximo_kit() -> dict | None:
    for m in kits():
        if m.get("status") == "pronto":
            return m
    return None


def kit_capa(kid: str, lombada_mm: float) -> bytes:
    lombada_mm = round(lombada_mm * 2) / 2
    m = _kit_meta(kid)
    if not m:
        raise UiclapErro("kit não existe")
    alvo = KITS / kid / f"capa_{lombada_mm:.1f}.jpg"
    if not alvo.exists():
        i = m["info"]
        alvo.write_bytes(montar_capa(i["titulo"], i.get("subtitulo", ""), i["autor"], i["descricao"][:900], lombada_mm))
    return alvo.read_bytes()


def kit_resultado(kid: str, dado: dict) -> dict:
    m = _kit_meta(kid)
    if not m:
        raise UiclapErro("kit não existe")
    m["status"] = ("testado" if m.get("teste") else "publicado") if dado.get("ok") else "falhou"
    m["resultado"] = json.loads(json.dumps(dado, ensure_ascii=False)[:6000]) if len(json.dumps(dado)) <= 6000 else {
        k: (str(v)[:1500] if not isinstance(v, (int, float, bool)) else v) for k, v in dado.items()}
    m["resultado_em"] = time.time()
    _kit_salvar(m)
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass
    return m


def script_favorito(origem: str) -> str:
    return (_JS.replace("__ORIGEM__", origem.rstrip("/")).replace("__TOKEN__", token_favorito()))


def link_favorito(origem: str) -> str:
    o = origem.rstrip("/")
    return ("javascript:(function(){var s=document.createElement('script');s.src='" + o + "/uic/pub.js?t="
            + token_favorito() + "&v='+Date.now();document.body.appendChild(s);})();")


_JS = r"""(async () => {
const O = "__ORIGEM__", T = "__TOKEN__";
if (window.__orbeRodando) return; window.__orbeRodando = true;
const box = document.createElement("div");
box.style.cssText = "position:fixed;top:12px;right:12px;z-index:2147483647;background:#fff;color:#111;border:3px solid #f26a21;border-radius:10px;padding:12px 14px;width:360px;max-height:75vh;overflow:auto;font:14px/1.45 sans-serif;box-shadow:0 6px 24px #0005";
document.body.appendChild(box);
const log = (m, cor) => { const p = document.createElement("div"); p.textContent = m; if (cor) p.style.color = cor; box.appendChild(p); box.scrollTop = 1e9; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fim = () => { window.__orbeRodando = false; const b = document.createElement("button"); b.textContent = "Fechar"; b.style.cssText = "margin-top:8px;padding:4px 12px"; b.onclick = () => box.remove(); box.appendChild(b); };
log("📚 Orbe → UICLAP", "#f26a21");
if (location.host !== "portal.uiclap.com") { log("Abra o portal.uiclap.com (logado) e clique no favorito de novo.", "red"); return fim(); }
const idb = (db, store) => new Promise(res => { const o = indexedDB.open(db); o.onerror = () => res([]);
  o.onsuccess = () => { try { const r = o.result.transaction(store, "readonly").objectStore(store).getAll();
    r.onsuccess = () => res(r.result || []); r.onerror = () => res([]); } catch (e) { res([]); } }; });
async function idToken() {
  const u = (await idb("firebaseLocalStorageDb", "firebaseLocalStorage"))[0];
  if (!u) throw "você não está logado no portal";
  const v = u.value, s = v.stsTokenManager;
  if (s.expirationTime - Date.now() > 120000) return s.accessToken;
  const r = await fetch("https://securetoken.googleapis.com/v1/token?key=" + v.apiKey, { method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "grant_type=refresh_token&refresh_token=" + encodeURIComponent(s.refreshToken) });
  return (await r.json()).id_token;
}
async function appCheck() {
  const vs = await idb("firebase-app-check-database", "firebase-app-check-store");
  const ok = vs.map(x => (x && x.value) ? x.value : x).filter(x => x && x.token && (x.expireTimeMillis || 0) > Date.now() + 60000);
  return ok.length ? ok[0].token : null;
}
let AC = null;
async function api(path, method = "GET", body) {
  const h = { "Authorization": "Bearer " + await idToken(), "X-Firebase-AppCheck": AC, "Accept": "application/json, text/plain, */*" };
  let b;
  if (body !== undefined) { if (typeof body === "string") { b = body; h["Content-Type"] = "application/x-www-form-urlencoded"; } else { b = JSON.stringify(body); h["Content-Type"] = "application/json"; } }
  const r = await fetch("/data/v2/" + path, { method, headers: h, body: b, credentials: "include" });
  if (!r.ok) throw path.split("/").slice(0, 2).join("/") + ": HTTP " + r.status;
  const t = await r.text(); try { return JSON.parse(t); } catch (e) { return t; }
}
const ok = (d, etapa) => { const n = d && typeof d === "object" ? d.retorno : 0; if (!(n > 0)) throw etapa + ": retorno " + n + " " + JSON.stringify(d).slice(0, 120); return n; };
const avisa = (kid, res) => fetch(O + "/uic/kit/" + kid + "/resultado?t=" + T, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(res) }).catch(() => {});
let k = null, doc = 0, etapa = "início";
try {
  AC = await appCheck();
  if (!AC) { log("Aperte F5 (recarregar), espere 5 segundos e clique no favorito de novo.", "red"); return fim(); }
  log("Buscando o livro no Orbe (pode levar até 1 min se o servidor estiver dormindo)…");
  const f = await (await fetch(O + "/uic/fila?t=" + T)).json();
  if (!f.kit) { log("Nenhum livro pronto na fila agora. 🙂"); return fim(); }
  k = f.kit; log((k.teste ? "🧪 TESTE (não publica): " : "Livro: ") + k.info.titulo);
  etapa = "informações";
  const base = await api("doc/0");
  doc = ok(await api("doc/info/0", "POST", Object.assign({}, base.info, { idioma: "pt_BR", productType: "BOOK", idade: 7 }, k.info)), "informações");
  log("✓ rascunho criado (" + doc + ")");
  etapa = "miolo";
  const tk = await api("uploadticket/m/" + doc); ok(tk, "ticket do miolo");
  const pdf = await (await fetch(O + "/uic/kit/" + k.kid + "/miolo.pdf?t=" + T)).blob();
  let r = await fetch(tk.url, { method: "PUT", headers: { "Content-Type": "application/pdf" }, body: pdf });
  if (!r.ok) throw "envio do PDF: HTTP " + r.status;
  r = await fetch("https://process.uiclap.com/v2/cont/ups/", { method: "POST", headers: { "Authorization": "Ticket " + tk.mensagem }, body: "" });
  const m = await r.json(); if (m.r !== 0) throw "miolo recusado (r=" + m.r + ") " + (m.m || "");
  log("✓ miolo lido: " + m.p + " páginas, lombada " + m.l + " mm");
  const car = (await api("doc/" + doc)).caracteristicas;
  Object.assign(car, { paginas: m.p, lombada: m.l, tamanhoInfo: { i: 0, largura: m.w, altura: m.h } });
  await sleep(8000);
  let d = null;
  for (let i = 0; i < 8; i++) { try { d = await api("doc/miolov2/" + doc, "POST", car); if (d && d.retorno > 0) break; } catch (e) { if (i === 7) throw e; } await sleep(6000); }
  ok(d, "salvar miolo"); log("✓ miolo salvo");
  etapa = "capa";
  const jpg = await (await fetch(O + "/uic/kit/" + k.kid + "/capa.jpg?t=" + T + "&lombada=" + m.l)).blob();
  Object.assign(car, { temOrelha: false, larguraOrelha: 0 });
  const tc = await api("ticket/c/" + doc, "POST", car); ok(tc, "ticket da capa");
  const fd = new FormData(); fd.append("a", jpg, "arq.jpg"); fd.append("t", "image/jpeg");
  r = await fetch("https://process.uiclap.com/capa/upso/", { method: "POST", headers: { "Authorization": "Ticket " + tc.mensagem }, body: fd });
  const c = await r.json(); if (c.r !== 0) throw "capa recusada (r=" + c.r + ") " + (c.m || "");
  Object.assign(car, { temCapa: true, logoCapa: { tipo: 5, posicao: 2 }, logoLombada: { tipo: 8, posicao: 2 } });
  ok(await api("doc/capa/" + doc, "POST", car), "salvar capa"); log("✓ capa salva");
  if (k.teste) {
    etapa = "limpeza"; await api("doc/" + doc, "DELETE");
    log("✅ TESTE OK: miolo e capa foram aceitos. Rascunho de teste apagado.", "green");
    await avisa(k.kid, { ok: true, teste: true, doc, paginas: m.p, lombada: m.l }); return fim();
  }
  etapa = "finalizar";
  const idl = ok(await api("doc/finaliza/" + doc, "POST", ""), "finalizar"); log("✓ edição finalizada");
  etapa = "publicar";
  const t = await api("titulo/" + idl);
  ok(await api("titulo/publica/" + idl, "POST", { acabamento: t.acabamento, isPrivado: false, senha: "", valorAutor: k.valor_autor }), "publicar");
  const t2 = await api("titulo/" + idl);
  log("✅ PUBLICADO! Pode fechar. O Orbe vai mostrar no resumo.", "green");
  await avisa(k.kid, { ok: true, doc, id_livro: idl, titulo: t2 });
} catch (e) {
  log("✗ Parou em '" + etapa + "': " + e, "red");
  if (k) await avisa(k.kid, { ok: false, doc, etapa, erro: String(e) });
  log(doc ? "O Orbe foi avisado. O rascunho ficou em 'Títulos em edição'." : "O Orbe foi avisado.");
}
fim();
})();"""


# ------------------------------------------------------------------ publicação SEM o dono: o servidor roda o favorito
import asyncio  # noqa: E402

PUB = {"rodando": False, "ultimo": None, "inicio": 0.0}


async def publicar_em_fundo(origem: str, proxy: str | None = None) -> None:
    if PUB["rodando"]:
        return
    PUB.update(rodando=True, inicio=time.time(), ultimo=None)
    try:
        PUB["ultimo"] = await publicar_no_servidor(origem, proxy)
    except Exception as e:  # noqa: BLE001
        PUB["ultimo"] = {"ok": False, "erro": f"{type(e).__name__}: {e}"[:600]}
    finally:
        PUB["rodando"] = False
        PUB["ultimo"]["em"] = time.time()


async def publicar_no_servidor(origem: str, proxy: str | None = None, espera_s: int = 240) -> dict[str, Any]:
    """Abre um Chromium COM janela (Xvfb), injeta o login e roda o mesmo pub.js do favorito.
    Headless é recusado pelo anti-robô; com janela ele passou (teste 29/09)."""
    import os

    from playwright.async_api import async_playwright

    from browser import BASE_ARGS, IGNORE_ARGS, STEALTH_JS

    e = credencial()
    if not e.get("user") or not e.get("fbase_key"):
        raise UiclapErro("falta o login completo do UICLAP no cofre")
    async with httpx.AsyncClient(timeout=30) as cx:
        r = (await cx.post(f"https://securetoken.googleapis.com/v1/token?key={e['apiKey']}",
                           data={"grant_type": "refresh_token", "refresh_token": e["refreshToken"]})).json()
    if "id_token" not in r:
        raise UiclapErro("login do UICLAP expirou — reenvie o uiclap-login.txt")
    user = dict(e["user"])
    user["stsTokenManager"] = {"refreshToken": r["refresh_token"], "accessToken": r["id_token"],
                               "expirationTime": int(time.time() * 1000) + 3500 * 1000}
    reg = {"fbase_key": e["fbase_key"], "value": user}
    k = proximo_kit()
    if not k:
        return {"ok": False, "erro": "nenhum livro pronto na fila"}
    est = (k.get("paginas") or 60) * 0.07        # 64 págs → 4 mm, 76 → 5 mm (lombada vem do UICLAP depois)
    import gc

    for lb in sorted({max(0.0, round(est * 2) / 2 + d) for d in (-1, -0.5, 0, 0.5, 1)} | {float(round(est))}):
        await asyncio.to_thread(kit_capa, k["kid"], lb)   # capa pronta ANTES do Chromium (512 MB no Render)
    gc.collect()
    src = f"{origem.rstrip('/')}/uic/pub.js?t={token_favorito()}&v={int(time.time())}"
    out: dict[str, Any] = {"appcheck": [], "caixa": "", "ok": False}
    async with async_playwright() as pw:
        leve = ["--renderer-process-limit=2", "--disable-gpu", "--disable-extensions",
                "--disable-features=Translate,MediaRouter,OptimizationHints", "--js-flags=--max-old-space-size=192"]
        b = await pw.chromium.launch(headless=not os.environ.get("DISPLAY"), args=[*BASE_ARGS, *leve],
                                     ignore_default_args=IGNORE_ARGS, **({"proxy": {"server": proxy}} if proxy else {}))
        try:
            ctx = await b.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo",
                                      viewport={"width": 1280, "height": 800})
            await ctx.add_init_script(STEALTH_JS)
            page = await ctx.new_page()
            page.on("request", lambda rq: out["appcheck"].append(
                rq.headers.get("x-firebase-appcheck", "")[:3] or "-") if "/data/v2/" in rq.url else None)
            await page.goto("https://portal.uiclap.com/", wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(3000)
            await page.evaluate("""(reg) => new Promise((res, rej) => {
                const o = indexedDB.open('firebaseLocalStorageDb', 1);
                o.onupgradeneeded = () => o.result.createObjectStore('firebaseLocalStorage', {keyPath: 'fbase_key'});
                o.onsuccess = () => { const tx = o.result.transaction('firebaseLocalStorage', 'readwrite');
                    tx.objectStore('firebaseLocalStorage').put(reg); tx.oncomplete = () => res(true);
                    tx.onerror = () => rej(tx.error); };
                o.onerror = () => rej(o.error); })""", reg)
            await page.goto("https://portal.uiclap.com/conta", wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(12000)
            out["appcheck"] = out["appcheck"][:6]
            if not any(x == "eyJ" for x in out["appcheck"]):
                out["erro"] = "anti-robô recusou este navegador"
                return out
            await page.evaluate("(u) => { const s = document.createElement('script'); s.src = u; "
                                "document.body.appendChild(s); }", src)
            for _ in range(max(10, espera_s // 3)):
                await page.wait_for_timeout(3000)
                out["caixa"] = await page.evaluate(
                    "() => { const d = [...document.querySelectorAll('div')].find(x => "
                    "x.textContent.startsWith('📚 Orbe')); return d ? d.innerText : ''; }")
                if any(m in out["caixa"] for m in ("TESTE OK", "PUBLICADO", "Parou", "F5", "Nenhum livro", "Abra o")):
                    break
            out["ok"] = "TESTE OK" in out["caixa"] or "PUBLICADO" in out["caixa"]
            return out
        finally:
            await b.close()
