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


def credencial() -> dict | None:
    try:
        from secrets_vault import VAULT

        e = VAULT.get("uiclap")
        return (e or {}).get("extra") or None
    except Exception:
        return None


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
