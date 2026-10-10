"""Dez agentes dos canais. Rodam no servidor, 24h, sem PC.

bilibili-cria / bilibili-analisa
youtube-cria / youtube-analisa
tiktok-cria / tiktok-analisa
cookies-renova / cookies-vigia
arena-acorda / telegram-informa

Não imprime cookie. Não pede cookie. Não inventa view.
Não republica peça recusada. Não edita o Short 13. Não publica sem sessão.
Cria, publica e só julga view depois de 24h. Não copia vídeo em alta.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path("data")
ESTADO = DATA / "canais_24h.json"
SESSOES = DATA / "canais_sessoes.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
YT_VIDEO = "h6Y-M4AgX6s"
BILI_BVID = "BV1TWHU6qEwa"
INSPIRA_POS_POST_S = 8 * 3600
CHECAGEM_S = 30 * 60
COOKIE_OK_S = 20 * 60
COOKIE_MORTO_S = 6 * 3600
VIGIA_S = 10 * 60

AGENTES = (
    "bilibili-cria",
    "bilibili-analisa",
    "youtube-cria",
    "youtube-analisa",
    "tiktok-cria",
    "tiktok-analisa",
    "cookies-renova",
    "cookies-vigia",
    "arena-acorda",
    "telegram-informa",
)


def _agora() -> int:
    return int(time.time())


def _http(url: str, cookie: str = "", data: bytes | None = None, method: str | None = None, timeout: int = 25, headers: dict | None = None) -> tuple[int, str, str]:
    headers = {"User-Agent": UA, "Accept": "application/json,text/html", **(headers or {})}
    if cookie:
        headers["Cookie"] = cookie
    if data is not None and "Content-Type" not in headers:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), r.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, getattr(e, "url", url) or url, e.read(20_000).decode("utf-8", "replace")
    except Exception:
        return 0, url, ""


def _ler(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gravar(path: Path, doc: dict) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sessoes() -> dict[str, str]:
    guardado = _ler(SESSOES)
    pares = dict(guardado.get("cookies") or {})
    for nome, env in (
        ("bilibili", "BILIBILI_COOKIE"),
        ("youtube", "YOUTUBE_STUDIO_COOKIE"),
        ("tiktok", "TIKTOK_STUDIO_COOKIE"),
        ("arena", "ARENA_COOKIE"),
        ("arena_yt", "ARENA_YT_COOKIE"),
    ):
        valor = os.environ.get(env, "").strip()
        if valor and not pares.get(nome):
            pares[nome] = valor
    return pares


def _guardar_sessoes(pares: dict[str, str], extra: dict | None = None) -> None:
    doc = _ler(SESSOES)
    doc["cookies"] = pares
    if extra:
        doc.update(extra)
    doc["atualizado"] = _agora()
    _gravar(SESSOES, doc)


def _estado() -> dict:
    doc = _ler(ESTADO)
    doc.setdefault("agentes", {nome: {"ultimo": "", "quando": 0} for nome in AGENTES})
    return doc


def _marcar(nome: str, texto: str, **campos) -> None:
    doc = _estado()
    doc["agentes"][nome] = {"ultimo": texto, "quando": _agora(), **campos}
    doc["vivo"] = _agora()
    _gravar(ESTADO, doc)


def estado_publico() -> dict:
    doc = _estado()
    canais = {k: v for k, v in doc.items() if k in ("bilibili", "youtube", "tiktok", "cookies", "monitor", "inspiracao", "estudo", "leitura_agora", "hipotese", "vizinhanca")}
    estudo = canais.get("estudo") or {}
    inspiracao = canais.get("inspiracao")
    if isinstance(inspiracao, dict) and (estudo.get("youtube") or {}).get("leu"):
        antiga = dict(inspiracao.get("youtube") or {})
        if antiga.get("leu") is False:
            antiga["nota"] = "nota antiga, substituida pelo estudo do proprio app"
            antiga["leu"] = None
            inspiracao = dict(inspiracao)
            inspiracao["youtube"] = antiga
            canais["inspiracao"] = inspiracao
    return {
        "vivo": doc.get("vivo") or 0,
        "sem_pc": True,
        "agentes": doc.get("agentes") or {},
        "canais": canais,
    }


def _csrf(cookie: str) -> str:
    for parte in cookie.split(";"):
        parte = parte.strip()
        if parte.startswith("bili_jct="):
            return parte.split("=", 1)[1]
    return ""


def _bilibili_nav(cookie: str) -> dict:
    code, _, corpo = _http("https://api.bilibili.com/x/web-interface/nav", cookie)
    try:
        doc = json.loads(corpo)
    except Exception:
        return {"ok": False, "motivo": f"http_{code or 'rede'}"}
    data = doc.get("data") or {}
    return {
        "ok": doc.get("code") == 0 and bool(data.get("isLogin")),
        "motivo": "ok" if doc.get("code") == 0 else str(doc.get("code")),
        "mid": data.get("mid") or 0,
    }


def _bilibili_arquivo(cookie: str) -> dict:
    url = "https://member.bilibili.com/x/web/archives?status=is_pubing,pubed,not_pubed&pn=1&ps=10&coop=1&interactive=1"
    code, _, corpo = _http(url, cookie, method="GET")
    try:
        doc = json.loads(corpo)
    except Exception:
        return {"ok": False, "motivo": f"http_{code or 'rede'}"}
    if doc.get("code") != 0:
        return {"ok": False, "motivo": str(doc.get("code"))}
    audits = ((doc.get("data") or {}).get("arc_audits") or [])
    if not audits:
        return {"ok": True, "vazio": True, "views": 0, "likes": 0, "estado": "sem_peca", "publico": False}
    item = audits[0]
    arc = item.get("Archive") or {}
    stat = item.get("stat") or {}
    estado = arc.get("state_desc") or ""
    lista = []
    for bruto in audits:
        um = bruto.get("Archive") or {}
        st = bruto.get("stat") or {}
        lista.append({
            "bvid": um.get("bvid") or "",
            "titulo": um.get("title") or "",
            "estado": um.get("state_desc") or "",
            "publico": um.get("state") == 0,
            "views": st.get("view") if "view" in st else None,
            "likes": st.get("like") if "like" in st else None,
            "moedas": st.get("coin") if "coin" in st else None,
            "favoritos": st.get("favorite") if "favorite" in st else st.get("fav") if "fav" in st else None,
            "ptime": um.get("ptime") or 0,
        })
    return {
        "ok": True,
        "bvid": arc.get("bvid") or "",
        "aid": arc.get("aid") or 0,
        "titulo": arc.get("title") or "",
        "estado": estado,
        "publico": arc.get("state") == 0,
        "views": stat.get("view") if "view" in stat else None,
        "likes": stat.get("like") if "like" in stat else None,
        "moedas": stat.get("coin") if "coin" in stat else None,
        "favoritos": stat.get("favorite") if "favorite" in stat else stat.get("fav") if "fav" in stat else None,
        "replies": stat.get("reply") or 0,
        "ptime": arc.get("ptime") or 0,
        "mid": (arc.get("author") or {}).get("mid") or 0,
        "lista": lista,
    }


def _bilibili_comentarios(cookie: str, aid: int) -> list[dict]:
    if not aid:
        return []
    url = "https://api.bilibili.com/x/v2/reply?type=1&sort=2&pn=1&ps=20&oid=" + str(aid)
    _, _, corpo = _http(url, cookie)
    try:
        doc = json.loads(corpo)
    except Exception:
        return []
    replies = ((doc.get("data") or {}).get("replies") or []) or []
    saida = []
    for item in replies:
        if not isinstance(item, dict):
            continue
        membro = item.get("member") or {}
        saida.append({
            "rpid": item.get("rpid"),
            "mid": membro.get("mid") or 0,
            "mensagem": str(item.get("content", {}).get("message") or "")[:180],
        })
    return saida


def _bilibili_responder(cookie: str, aid: int, rpid: int, texto: str) -> str:
    csrf = _csrf(cookie)
    if not csrf or not aid or not rpid:
        return "sem_csrf"
    corpo = urllib.parse.urlencode({
        "oid": aid,
        "type": 1,
        "root": rpid,
        "parent": rpid,
        "message": texto,
        "plat": 1,
        "csrf": csrf,
    }).encode()
    code, _, resp = _http("https://api.bilibili.com/x/v2/reply/add", cookie, data=corpo, method="POST")
    try:
        doc = json.loads(resp)
        return str(doc.get("code"))
    except Exception:
        return f"http_{code or 'rede'}"


def _youtube_do_html(html: str) -> dict | None:
    views = re.search(r'"viewCount":"(\d+)"', html)
    if not views:
        return None
    likes = re.search(r'"likeCount":"(\d+)"', html)
    titulo = re.search(r"<title>([^<]+)</title>", html)
    return {
        "ok": True,
        "video": YT_VIDEO,
        "titulo": (titulo.group(1).replace(" - YouTube", "") if titulo else "")[:120],
        "views": int(views.group(1)),
        "likes": int(likes.group(1)) if likes else None,
        "comentarios": None,
        "comentarios_respondidos": False,
        "motivo_comentario": "a pagina nao trouxe comentario novo",
    }


def _youtube_publico(cookie: str = "") -> dict:
    code, final, html = _http(
        f"https://www.youtube.com/watch?v={YT_VIDEO}",
        cookie,
        headers={"Accept-Language": "pt-BR", "Referer": "https://www.youtube.com/"},
    )
    if "accounts.google.com" in final or code != 200 or not html:
        return {"ok": False, "motivo": f"http_{code or 'rede'}"}
    achado = _youtube_do_html(html)
    if achado:
        return achado
    # A contagem fica depois dos primeiros 400 mil bytes. Lê o resto sem guardar cookie.
    req = urllib.request.Request(
        f"https://www.youtube.com/watch?v={YT_VIDEO}",
        headers={"User-Agent": UA, "Cookie": cookie, "Accept-Language": "pt-BR"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            bruto = r.read(1_400_000).decode("utf-8", "replace")
    except Exception:
        return {"ok": False, "motivo": "pagina_sem_viewcount"}
    achado = _youtube_do_html(bruto)
    return achado or {"ok": False, "motivo": "pagina_sem_viewcount", "video": YT_VIDEO}


def _youtube(cookie: str) -> tuple[str, str]:
    if not cookie:
        return "ausente", cookie
    jar = {}
    for parte in cookie.split(";"):
        if "=" in parte:
            nome, valor = parte.strip().split("=", 1)
            if valor:
                jar[nome] = valor
    sap = jar.get("SAPISID") or ""
    if not sap or "SID" not in jar:
        return "morto", cookie
    origin = "https://studio.youtube.com"
    ts = str(int(time.time()))
    auth = "SAPISIDHASH " + ts + "_" + hashlib.sha1(f"{ts} {sap} {origin}".encode()).hexdigest()
    code, final, headers, corpo = _abrir(
        "https://studio.youtube.com/youtubei/v1/account/account_menu?prettyPrint=false",
        cookie,
        data=json.dumps({"context": {"client": {"clientName": "WEB_CREATOR", "clientVersion": "1.20241001.00.00"}}}).encode(),
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Origin": origin,
            "Referer": origin + "/",
        },
    )
    if code != 200 or "must be signed in" in corpo.lower() or "accounts.google.com" in final:
        return "morto", cookie
    novo, _ = _juntar(cookie, headers)
    return "ok", novo


def _tiktok(cookie: str) -> tuple[str, str, dict]:
    if not cookie:
        return "ausente", cookie, {}
    code, _, headers, corpo = _abrir(
        "https://www.tiktok.com/api/user/detail/self/?aid=1988",
        cookie,
        headers={"Referer": "https://www.tiktok.com/tiktokstudio", "Accept": "application/json"},
    )
    novo, _ = _juntar(cookie, headers)
    if "<html" in corpo[:40].lower():
        return "morto", cookie, {}
    try:
        doc = json.loads(corpo)
    except Exception:
        return (f"http_{code or 'rede'}", cookie, {})
    if doc.get("status_code") not in (0, None) and not doc.get("userInfo"):
        return "morto", cookie, {}
    info = doc.get("userInfo") or {}
    stats = info.get("stats") or {}
    user = info.get("user") or {}
    return "ok", novo, {
        "conta": user.get("uniqueId") or "",
        "seguidores": stats.get("followerCount"),
        "curtidas": stats.get("heartCount"),
        "videos": stats.get("videoCount"),
    }


def _juntar(cookie: str, headers) -> tuple[str, bool]:
    jar: dict[str, str] = {}
    for parte in (cookie or "").split(";"):
        if "=" in parte:
            nome, valor = parte.strip().split("=", 1)
            if valor:
                jar[nome] = valor
    mudou = False
    bruto = headers.get_all("Set-Cookie") if headers is not None and hasattr(headers, "get_all") else []
    for linha in bruto or []:
        par = linha.split(";", 1)[0]
        if "=" not in par:
            continue
        nome, valor = par.split("=", 1)
        if not valor or nome.startswith("__Host-"):
            continue
        if jar.get(nome) != valor:
            jar[nome] = valor
            mudou = True
    header = "; ".join(f"{nome}={valor}" for nome, valor in jar.items())
    return header, mudou


def _abrir(url: str, cookie: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, str, object, str]:
    h = {"User-Agent": UA, "Accept": "application/json,text/html", "Referer": url}
    if cookie:
        h["Cookie"] = cookie
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.geturl(), r.headers, r.read(80_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, "", e.headers, e.read(8_000).decode("utf-8", "replace")
    except Exception:
        return 0, url, None, ""


def _arena(cookie: str) -> tuple[str, str]:
    if not cookie:
        return "ausente", cookie
    code, _, headers, corpo = _abrir(
        "https://arena.ai/api/me",
        cookie,
        headers={"Accept": "application/json", "Referer": "https://arena.ai/"},
    )
    novo, _ = _juntar(cookie, headers)
    if code == 200 and re.search(r'"email"\s*:\s*"[^"]+@', corpo):
        return "ok", novo
    if "User not found" in corpo:
        return "sem_usuario", cookie
    if code:
        return f"http_{code}", cookie
    return "rede", cookie


def ciclo_cookies() -> None:
    pares = _sessoes()
    nav = _bilibili_nav(pares.get("bilibili", ""))
    # OAuth no servidor substitui definitivamente o cookie morto do Studio.
    import youtube_api
    yt_estado = youtube_api.probe()
    yt = "ok" if yt_estado.get("ok") else str(yt_estado.get("motivo") or "oauth_ausente")
    tt, tt_cookie, tt_stats = _tiktok(pares.get("tiktok", ""))
    # O monitor e do servidor; nao repetir os chamados bloqueados da Arena.
    arena_estado, arena_cookie = "nao_utilizado_no_monitor", pares.get("arena", "")
    if tt == "ok" and tt_cookie:
        pares["tiktok"] = tt_cookie
    if arena_estado == "ok" and arena_cookie:
        pares["arena"] = arena_cookie
    _guardar_sessoes(pares, {"ultimo_probe": _agora(), "tiktok_stats": tt_stats if tt == "ok" else {}})
    vivos = [nome for nome, st in (("bilibili", "ok" if nav.get("ok") else ""), ("youtube", yt), ("tiktok", tt), ("arena", arena_estado)) if st == "ok"]
    _marcar(
        "cookies-renova",
        "guardou renovacao de " + ",".join(vivos) if vivos else "nenhuma sessao renovou",
        bilibili="ok" if nav.get("ok") else nav.get("motivo"),
        youtube=yt,
        tiktok=tt,
        arena=arena_estado,
    )
    doc = _estado()
    doc["cookies"] = {
        "bilibili": "ok" if nav.get("ok") else nav.get("motivo"),
        "youtube": yt,
        "youtube_modo": "oauth_oficial",
        "youtube_renovado_em": yt_estado.get("renovado_em"),
        "tiktok": tt,
        "arena": arena_estado,
        "quando": _agora(),
        "renova_sozinho": vivos,
    }
    if tt == "ok":
        doc["tiktok"] = {**tt_stats, "cookie": "ok", "quando": _agora(), "republicou": False}
    _gravar(ESTADO, doc)


def ciclo_vigia() -> None:
    doc = _estado()
    cookies = doc.get("cookies") or {}
    espera = COOKIE_OK_S
    if cookies.get("youtube") == "morto" or cookies.get("tiktok") == "morto" or str(cookies.get("arena_yt", "")).startswith("http_"):
        espera = COOKIE_MORTO_S
    proximo = _agora() + espera
    _marcar(
        "cookies-vigia",
        "proxima tentativa de cookie em " + str(espera // 60) + " min",
        proxima=proximo,
        inspiracao_s=espera,
    )


def _guardar_estudo(plataforma: str, estudo: dict) -> None:
    doc = _estado()
    doc.setdefault("estudo", {})[plataforma] = {
        "quando": estudo.get("quando"),
        "leu": bool(estudo.get("leu")),
        "modelos": estudo.get("modelos") or [],
        "vistos": len(estudo.get("titulos_vistos") or []),
        "licao": estudo.get("licao") or "",
        "nota": estudo.get("nota") or "",
    }
    _gravar(ESTADO, doc)


def _licao_bili(lista: list[dict]) -> str:
    import canais_oficio as oficio
    julgados = []
    for item in lista or []:
        texto = oficio.juizo(int(item.get("ptime") or 0), item.get("views"))
        if "gerou view sim" in texto:
            return "o ultimo original gerou view; mantenha a estrutura curta e invente outra historia"
        if "gerou view nao" in texto:
            julgados.append(texto)
    if julgados:
        return "o ultimo original nao gerou view em 24h; troque o gancho, historia nova"
    return "ainda sem julgamento de 24h do proprio canal"


def _num(valor):
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _tiktok_lista_html(corpo: str) -> list[dict]:
    if not corpo:
        return []
    marca = ""
    inicio = -1
    for candidato in ("&quot;item_list&quot;:", '"item_list":'):
        inicio = corpo.find(candidato)
        if inicio >= 0:
            marca = candidato
            break
    if inicio < 0:
        return []
    try:
        bruto = html.unescape(corpo[inicio + len(marca):])
        itens, _ = json.JSONDecoder().raw_decode(bruto)
    except Exception:
        return []
    agora = _agora()
    saida = []
    for item in itens[:12]:
        post_time = int(item.get("post_time") or 0)
        visibilidade = item.get("visibility")
        publico = visibilidade == 1 and not item.get("in_review") and bool(post_time) and post_time <= agora
        duracao = item.get("duration")
        saida.append({
            "id": str(item.get("item_id") or ""),
            "titulo": str(item.get("desc") or "").split("\n")[0][:80],
            "views": _num(item.get("play_count")),
            "likes": _num(item.get("like_count")),
            "comentarios": _num(item.get("comment_count")),
            "post_time": post_time,
            "create_time": int(item.get("create_time") or 0),
            "status": item.get("status"),
            "visibility": visibilidade,
            "publico": publico,
            "duracao_s": round(int(duracao) / 1000, 1) if duracao else None,
        })
    return saida


def _tiktok_studio(cookie: str) -> list[dict]:
    if not cookie:
        return []
    _, _, corpo = _http(
        "https://www.tiktok.com/tiktokstudio/content",
        cookie,
        timeout=40,
        headers={"Referer": "https://www.tiktok.com/tiktokstudio/content", "Accept": "text/html"},
    )
    return _tiktok_lista_html(corpo)


def _licao_tiktok(lista: list[dict]) -> str:
    import canais_oficio as oficio
    for item in lista or []:
        if not item.get("publico"):
            continue
        texto = oficio.juizo(int(item.get("post_time") or 0), item.get("views"))
        if "gerou view sim" in texto:
            return "o ultimo original julgado gerou view; mantenha a estrutura curta e invente outra historia"
        if "gerou view nao" in texto:
            return "o ultimo original julgado nao gerou view em 24h; troque o gancho, historia nova, nao copie titulo"
    return "ainda sem julgamento de 24h do proprio TikTok; use so o exemplo de estrutura"


def _tiktok_itens(cookie: str) -> list[dict]:
    if not cookie:
        return []
    urls = (
        "https://www.tiktok.com/api/recommend/item_list/?aid=1988&count=8",
        "https://www.tiktok.com/api/explore/item_list/?aid=1988&count=8&cursor=0",
    )
    for url in urls:
        _, _, corpo = _http(url, cookie, headers={"Referer": "https://www.tiktok.com/", "Accept": "application/json"})
        if not corpo or corpo[:1] not in "{[":
            continue
        try:
            doc = json.loads(corpo)
        except Exception:
            continue
        lista = doc.get("itemList") or doc.get("item_list") or []
        itens = []
        for item in lista[:8]:
            video = item.get("video") or {}
            stats = item.get("stats") or {}
            itens.append({
                "titulo": str(item.get("desc") or "")[:80],
                "views": stats.get("playCount"),
                "duracao_s": video.get("duration"),
            })
        if itens:
            return itens
    return []


def ciclo_bilibili_analisa() -> None:
    cookie = _sessoes().get("bilibili", "")
    arq = _bilibili_arquivo(cookie)
    if not arq.get("ok"):
        _marcar("bilibili-analisa", "sem leitura", motivo=arq.get("motivo"))
        return
    aid = int(arq.get("aid") or 0)
    comentarios = _bilibili_comentarios(cookie, aid)
    doc = _estado()
    respondidos = set(doc.get("bilibili_respondidos") or [])
    novos = 0
    meu = int(arq.get("mid") or 0)
    for item in comentarios:
        rpid = item.get("rpid")
        if not rpid or str(rpid) in respondidos:
            continue
        if meu and int(item.get("mid") or 0) == meu:
            continue
        codigo = _bilibili_responder(cookie, aid, int(rpid), "Obrigado por comentar.")
        if codigo == "0":
            respondidos.add(str(rpid))
            novos += 1
    doc = _estado()
    doc["bilibili_respondidos"] = sorted(respondidos)
    doc["bilibili"] = {
        "bvid": arq.get("bvid") or BILI_BVID,
        "estado": arq.get("estado"),
        "publico": arq.get("publico"),
        "views": arq.get("views"),
        "likes": arq.get("likes"),
        "moedas": arq.get("moedas"),
        "favoritos": arq.get("favoritos"),
        "comentarios": len(comentarios),
        "respostas_novas": novos,
        "quando": _agora(),
    }
    _gravar(ESTADO, doc)
    import canais_oficio as oficio
    juizos = [oficio.juizo(int(item.get("ptime") or 0), item.get("views")) for item in (arq.get("lista") or [])]
    doc["bilibili"]["juizo_24h"] = juizos
    _gravar(ESTADO, doc)
    estudo = oficio.inspirar("bilibili", licao=_licao_bili(arq.get("lista") or []))
    _guardar_estudo("bilibili", estudo)
    _marcar(
        "bilibili-analisa",
        f"views {arq.get('views')} likes {arq.get('likes')} comentarios {len(comentarios)} respostas {novos}. "
        + " | ".join(juizos[:3])
        + f". moedas {arq.get('moedas')} favoritos {arq.get('favoritos')}. Estudei {len(estudo.get('modelos') or [])} modelos do que funciona no Bilibili, sem copiar titulo.",
    )


def ciclo_bilibili_cria() -> None:
    import canais_oficio as oficio
    cookie = _sessoes().get("bilibili", "")
    nav = _bilibili_nav(cookie)
    if not nav.get("ok"):
        _marcar("bilibili-cria", "sem sessao, nao posto", proxima=_agora() + CHECAGEM_S)
        return
    arq = _bilibili_arquivo(cookie)
    if arq.get("ok") and not arq.get("publico") and not arq.get("vazio"):
        _marcar("bilibili-cria", "uma peca ainda nao publica, nao posto outra", estado=arq.get("estado"), proxima=_agora() + CHECAGEM_S)
        return
    if arq.get("ptime") and _agora() - int(arq.get("ptime") or 0) < oficio.DIA:
        _marcar("bilibili-cria", "ultima peca ainda nao fez 24h, nao posto outra", proxima=_agora() + CHECAGEM_S)
        return
    import canais_papel as papel
    if not papel.manha():
        doc = _estado()
        doc["hipotese"] = papel.hipotese(doc)
        _gravar(ESTADO, doc)
        _marcar("bilibili-cria", f"proximo so de manha, entre 9h e 11h, nao as 21h. papel {doc['hipotese'].get('papel')}. nao postei.", proxima=_agora() + CHECAGEM_S)
        return
    doc = _estado()
    if int((doc.get("bilibili_post") or {}).get("tentativa") or 0) > _agora() - oficio.DIA:
        _marcar("bilibili-cria", "ja tentei publicar hoje, nao repito o envio", proxima=_agora() + CHECAGEM_S)
        return
    notas = oficio.inspirar("bilibili", licao=_licao_bili(arq.get("lista") or []))
    _guardar_estudo("bilibili", notas)
    usados = {str(item.get("titulo") or "") for item in (arq.get("lista") or [])}
    peca = oficio.roteiro("bilibili", notas, usados)
    destino = oficio.PECAS / "bili-proxima.mp4"
    erro = oficio.render_mp4(destino, peca["titulo"], peca["fala"], peca)
    if erro:
        _marcar("bilibili-cria", erro, proxima=_agora() + CHECAGEM_S)
        return
    doc = _estado()
    doc["bilibili_post"] = {"tentativa": _agora(), "titulo": peca["titulo"]}
    _gravar(ESTADO, doc)
    resultado = oficio.bili_publicar(cookie, destino, peca["titulo"], peca["descricao"])
    if resultado.get("ok"):
        _marcar("bilibili-cria", f"publiquei {resultado.get('bvid')} {peca['titulo']}", bvid=resultado.get("bvid"))
        return
    _marcar("bilibili-cria", f"nao publiquei, {resultado.get('motivo')}", proxima=_agora() + oficio.DIA)


def ciclo_youtube_analisa() -> None:
    import youtube_rotina
    mensagem, campos, leitura = youtube_rotina.analisa()
    doc = _estado()
    doc["youtube"] = leitura
    if leitura.get("estudo"):
        doc.setdefault("estudo", {})["youtube"] = leitura["estudo"]
    _gravar(ESTADO, doc)
    _marcar("youtube-analisa", mensagem, **campos)


def ciclo_youtube_cria() -> None:
    import youtube_rotina
    mensagem, campos = youtube_rotina.cria()
    _marcar("youtube-cria", mensagem, **campos)


def _vizinhanca(cookie: str) -> str:
    doc = _estado()
    viz = doc.get("vizinhanca") or {}
    if _agora() - int(viz.get("quando") or 0) < 7 * 86400:
        return str(viz.get("nota") or "ja tentei a vizinhanca esta semana")
    autores = []
    for url in (
        "https://www.tiktok.com/api/recommend/item_list/?aid=1988&count=8",
        "https://www.tiktok.com/api/explore/item_list/?aid=1988&count=8&cursor=0",
    ):
        _, _, corpo = _http(url, cookie, headers={"Referer": "https://www.tiktok.com/", "Accept": "application/json"})
        if not corpo or corpo[:1] not in "{[":
            continue
        try:
            bruto = json.loads(corpo)
        except Exception:
            continue
        for item in (bruto.get("itemList") or bruto.get("item_list") or [])[:8]:
            autor = item.get("author") or {}
            ident = str(autor.get("secUid") or autor.get("id") or "")
            conta = str(autor.get("uniqueId") or "").lower()
            if conta == "historias.dameia.noite" or not ident:
                continue
            if ident not in {a.get("id") for a in autores}:
                autores.append({"id": ident, "duracao": (item.get("video") or {}).get("duration"), "aweme": str(item.get("id") or "")})
        if autores:
            break
    seguidos = list(viz.get("seguidos") or [])
    nota = "sem autor lido, nao segui ninguem"
    if autores and len(seguidos) < 3:
        novos = 0
        for autor in autores:
            if len(seguidos) >= 3 or novos >= 3:
                break
            if autor["id"] in seguidos:
                continue
            corpo = urllib.parse.urlencode({"sec_user_id": autor["id"], "type": 1, "aid": 1988}).encode()
            code, _, resp = _http(
                "https://www.tiktok.com/api/commit/follow/user/?aid=1988",
                cookie,
                data=corpo,
                headers={"Referer": "https://www.tiktok.com/", "Accept": "application/json"},
            )
            if code == 200 and '"status_code":0' in resp.replace(" ", ""):
                seguidos.append(autor["id"])
                novos += 1
            else:
                nota = "tiktok recusou o follow, nao repito esta semana"
                break
        else:
            nota = f"segui {novos}, parei em 3"
        if novos and nota.startswith("sem autor"):
            nota = f"segui {novos}, parei em 3"
    comentario = "sem comentario"
    alvo = next((a for a in autores if a.get("duracao") and a.get("aweme")), None)
    if alvo and nota != "tiktok recusou o follow, nao repito esta semana":
        try:
            segundos = int(alvo["duracao"])
        except (TypeError, ValueError):
            segundos = 0
        if segundos > 0:
            texto = f"A regra cabe em {segundos} segundos e o assunto nao vem no comeco."
            if "http" not in texto and "segue" not in texto.lower():
                corpo = urllib.parse.urlencode({"aweme_id": alvo["aweme"], "text": texto, "aid": 1988}).encode()
                code, _, resp = _http(
                    "https://www.tiktok.com/api/comment/publish/?aid=1988",
                    cookie,
                    data=corpo,
                    headers={"Referer": "https://www.tiktok.com/", "Accept": "application/json"},
                )
                comentario = "comentei um video" if code == 200 and '"status_code":0' in resp.replace(" ", "") else "comentario recusado, nao repito esta semana"
    doc = _estado()
    doc["vizinhanca"] = {"quando": _agora(), "seguidos": seguidos[:3], "nota": nota + "; " + comentario}
    _gravar(ESTADO, doc)
    return doc["vizinhanca"]["nota"]


def ciclo_tiktok_analisa() -> None:
    import canais_oficio as oficio
    st, cookie, stats = _tiktok(_sessoes().get("tiktok", ""))
    if st == "ok" and cookie:
        pares = _sessoes()
        pares["tiktok"] = cookie
        _guardar_sessoes(pares)
    lista = _tiktok_studio(cookie) if st == "ok" else []
    juizos = []
    if lista:
        for item in lista:
            if item.get("publico"):
                juizos.append(oficio.juizo(int(item.get("post_time") or 0), item.get("views")))
    doc = _estado()
    doc["tiktok"] = {
        **stats,
        "cookie": st,
        "quando": _agora(),
        "republicou": False,
        "videos_metricas": lista,
        "lidos_studio": len(lista),
        "lista_parcial": True,
        "juizo_24h": juizos,
    }
    _gravar(ESTADO, doc)
    if st != "ok":
        _marcar("tiktok-analisa", "sem sessao, nao invento view nem like")
        return
    licao = _licao_tiktok(lista)
    estudo = oficio.estudo_de("tiktok", _tiktok_itens(cookie), licao)
    _guardar_estudo("tiktok", estudo)
    if not lista:
        _marcar("tiktok-analisa", f"seguidores {stats.get('seguidores')} curtidas {stats.get('curtidas')} videos {stats.get('videos')}. lista do studio nao lida, nao inventei view por video. Estudei {len(estudo.get('modelos') or [])} modelos, sem copiar titulo.")
        return
    novo = lista[0]
    ar = "no ar" if novo.get("publico") else "nao confirmei no ar"
    viz = _vizinhanca(cookie)
    _marcar(
        "tiktok-analisa",
        f"seguidores {stats.get('seguidores')} curtidas {stats.get('curtidas')} videos {stats.get('videos')}. "
        f"li {len(lista)} da lista do studio, nao a conta inteira. ultimo {novo.get('titulo')} {ar}, views {novo.get('views')} likes {novo.get('likes')}. "
        + " | ".join(juizos[:3])
        + f". Estudei {len(estudo.get('modelos') or [])} modelos do que funciona no TikTok, sem copiar titulo. Vizinhanca: {viz}.",
    )


def ciclo_tiktok_cria() -> None:
    import canais_oficio as oficio
    st, cookie, _ = _tiktok(_sessoes().get("tiktok", ""))
    if st != "ok":
        _marcar("tiktok-cria", "sem sessao, nao republico e nao posto", proxima=_agora() + COOKIE_MORTO_S)
        return
    lista = _tiktok_studio(cookie)
    estudo = (_estado().get("estudo") or {}).get("tiktok") or {}
    if not estudo.get("leu"):
        estudo = oficio.estudo_de("tiktok", _tiktok_itens(cookie), _licao_tiktok(lista))
        _guardar_estudo("tiktok", estudo)
    n = len(estudo.get("modelos") or [])
    if not lista:
        _marcar("tiktok-cria", f"nao li a lista do studio, nao inventei post nem agendei. Estudei {n} modelos, sem copiar titulo.", proxima=_agora() + CHECAGEM_S)
        return
    novo = lista[0]
    hora = int(novo.get("post_time") or 0)
    if not novo.get("publico") or not hora:
        _marcar("tiktok-cria", f"ultimo lido {novo.get('titulo')} nao confirmei no ar, views {novo.get('views')}. nao posto outra e nao agendei.", proxima=_agora() + CHECAGEM_S, estudo=n)
        return
    idade = _agora() - hora
    if idade < oficio.DIA:
        _marcar(
            "tiktok-cria",
            f"{novo.get('titulo')} esta no ar, views {novo.get('views')}, ainda nao fez 24h ({idade // 3600}h). nao posto outra e nao agendei de novo. Proximo papel de manha, titulo sem nomear a coisa. Estudei {n} modelos, sem copiar titulo.",
            proxima=_agora() + min(CHECAGEM_S, oficio.DIA - idade),
            estudo=n,
        )
        return
    _marcar(
        "tiktok-cria",
        f"passou 24h de {novo.get('titulo')}, views {novo.get('views')}. este servidor nao envia arquivo ao TikTok; nao inventei post nem agendei. Estudei {n} modelos, sem copiar titulo.",
        proxima=_agora() + CHECAGEM_S,
        estudo=n,
    )


def ciclo_arena_acorda() -> None:
    import canais_oficio as oficio
    hora, dia = oficio.hora_local()
    ordem, motivo = oficio.em_ordem(_estado())
    doc = _estado()
    doc["leitura_agora"] = {
        "em_ordem": ordem,
        "motivo": motivo,
        "quando": _agora(),
        "quem": "servidor",
        "telegram": False,
    }
    _gravar(ESTADO, doc)
    mon = doc.get("monitor") or {}
    if not (8 <= hora < 10):
        _marcar("arena-acorda", "leitura no ciclo. a chamada na conversa existente e as 11:20, uma vez, sem conversa nova")
        return
    if mon.get("dia") == dia and mon.get("tentou"):
        _marcar("arena-acorda", mon.get("resumo") or "ja monitorei hoje")
        return
    ordem, motivo = oficio.em_ordem(doc)
    resumo = "servidor monitorou" if ordem else "servidor monitorou, nao esta em ordem"
    doc = _estado()
    doc["monitor"] = {
        "dia": dia,
        "tentou": True,
        "acordou": False,
        "monitorei": True,
        "quem": "servidor",
        "em_ordem": ordem,
        "motivo": motivo,
        "resumo": resumo,
        "telegram": False,
        "quando": _agora(),
    }
    _gravar(ESTADO, doc)
    _marcar("arena-acorda", resumo)


def ciclo_telegram_informa() -> None:
    import canais_oficio as oficio
    hora, dia = oficio.hora_local()
    doc = _estado()
    mon = doc.get("monitor") or {}
    if not (8 <= hora < 10):
        _marcar("telegram-informa", "espera a janela das 8h, uma vez ao dia")
        return
    if mon.get("dia") != dia or not mon.get("tentou"):
        _marcar("telegram-informa", "ainda sem monitoramento do servidor hoje")
        return
    if mon.get("telegram"):
        _marcar("telegram-informa", "aviso de hoje ja foi enviado")
        return
    texto = oficio.texto_telegram(
        dia,
        bool(mon.get("em_ordem")),
        str(mon.get("motivo") or ""),
        doc,
    )
    ok = oficio.informar(texto)
    doc = _estado()
    doc["monitor"]["telegram"] = ok
    _gravar(ESTADO, doc)
    _marcar("telegram-informa", "avisei no Telegram" if ok else "nao consegui avisar no Telegram")


CICLOS = (
    ("cookies-renova", ciclo_cookies),
    ("cookies-vigia", ciclo_vigia),
    ("bilibili-analisa", ciclo_bilibili_analisa),
    ("bilibili-cria", ciclo_bilibili_cria),
    ("youtube-analisa", ciclo_youtube_analisa),
    ("youtube-cria", ciclo_youtube_cria),
    ("tiktok-analisa", ciclo_tiktok_analisa),
    ("tiktok-cria", ciclo_tiktok_cria),
    ("arena-acorda", ciclo_arena_acorda),
    ("telegram-informa", ciclo_telegram_informa),
)


def ciclo() -> None:
    for nome, fn in CICLOS:
        try:
            fn()
        except Exception as exc:
            msg = str(exc).replace("\n", " ")[:80]
            if any(s in msg.lower() for s in ("cookie", "token", "sess", "bearer")):
                msg = "erro interno"
            _marcar(nome, f"falhou o ciclo, {type(exc).__name__}: {msg}")


async def laco() -> None:
    await asyncio.sleep(20)
    while True:
        await asyncio.to_thread(ciclo)
        doc = _estado()
        vigia = (doc.get("agentes") or {}).get("cookies-vigia") or {}
        espera = int(vigia.get("inspiracao_s") or VIGIA_S)
        espera = min(max(espera, VIGIA_S), COOKIE_MORTO_S)
        # analistas nao esperam o cookie morto o dia inteiro
        espera = min(espera, CHECAGEM_S)
        await asyncio.sleep(espera)
