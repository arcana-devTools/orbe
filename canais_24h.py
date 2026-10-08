"""Oito agentes dos canais. Rodam no servidor, 24h, sem PC.

bilibili-cria / bilibili-analisa
youtube-cria / youtube-analisa
tiktok-cria / tiktok-analisa
cookies-renova / cookies-vigia

Não imprime cookie. Não pede cookie. Não inventa view.
Não republica peça recusada. Não edita o Short 13. Não publica sem sessão.
"""
from __future__ import annotations

import asyncio
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
)


def _agora() -> int:
    return int(time.time())


def _http(url: str, cookie: str = "", data: bytes | None = None, method: str | None = None, timeout: int = 25) -> tuple[int, str, str]:
    headers = {"User-Agent": UA, "Accept": "application/json,text/html"}
    if cookie:
        headers["Cookie"] = cookie
    if data is not None:
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
    saida = {
        "vivo": doc.get("vivo") or 0,
        "sem_pc": True,
        "agentes": doc.get("agentes") or {},
        "canais": {k: v for k, v in doc.items() if k in ("bilibili", "youtube", "tiktok", "cookies")},
    }
    return saida


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
    return {
        "ok": True,
        "bvid": arc.get("bvid") or "",
        "aid": arc.get("aid") or 0,
        "titulo": arc.get("title") or "",
        "estado": estado,
        "publico": arc.get("state") == 0,
        "views": stat.get("view") or 0,
        "likes": stat.get("like") or 0,
        "replies": stat.get("reply") or 0,
        "mid": (arc.get("author") or {}).get("mid") or 0,
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


def _youtube_publico() -> dict:
    code, final, html = _http(f"https://www.youtube.com/watch?v={YT_VIDEO}")
    if "accounts.google.com" in final or code != 200 or not html:
        return {"ok": False, "motivo": f"http_{code or 'rede'}"}
    views = re.search(r'"viewCount":"(\d+)"', html)
    likes = re.search(r'"likeCount":"(\d+)"', html)
    titulo = re.search(r"<title>([^<]+)</title>", html)
    return {
        "ok": True,
        "video": YT_VIDEO,
        "titulo": (titulo.group(1).replace(" - YouTube", "") if titulo else "")[:120],
        "views": int(views.group(1)) if views else None,
        "likes": int(likes.group(1)) if likes else None,
        "comentarios_respondidos": False,
        "motivo_comentario": "sessao do studio morta, nao respondo no escuro",
    }


def _youtube_cookie(cookie: str) -> str:
    if not cookie:
        return "ausente"
    code, final, corpo = _http("https://studio.youtube.com/", cookie)
    if "accounts.google.com" in final or "ServiceLogin" in corpo:
        return "morto"
    if code == 200 and "studio.youtube.com" in final:
        return "ok"
    return f"http_{code or 'rede'}"


def _tiktok_cookie(cookie: str) -> str:
    if not cookie:
        return "ausente"
    code, _, corpo = _http("https://www.tiktok.com/tiktokstudio/api/web/user/info", cookie)
    if code == 200 and '"user"' in corpo and "<html" not in corpo[:40].lower():
        return "ok"
    return "morto" if code in (200, 401, 403) else f"http_{code or 'rede'}"


def _arena(cookie: str) -> tuple[str, str]:
    if not cookie:
        return "ausente", cookie
    headers_cookie = cookie
    req = urllib.request.Request(
        "https://arena.ai/api/me",
        headers={"User-Agent": UA, "Cookie": headers_cookie, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            corpo = r.read(4000).decode("utf-8", "replace")
            novos = []
            bruto = r.headers.get_all("Set-Cookie") if hasattr(r.headers, "get_all") else []
            for linha in bruto or []:
                if linha.startswith("arena-auth-prod-v1."):
                    novos.append(linha.split(";", 1)[0])
            if novos:
                headers_cookie = "; ".join(novos)
            ok = r.status == 200 and bool(re.search(r'"email"\s*:\s*"[^"]+@', corpo))
            return ("ok" if ok else "sem_email"), headers_cookie
    except urllib.error.HTTPError as e:
        return f"http_{e.code}", cookie
    except Exception:
        return "rede", cookie


def ciclo_cookies() -> None:
    pares = _sessoes()
    nav = _bilibili_nav(pares.get("bilibili", ""))
    yt = _youtube_cookie(pares.get("youtube", ""))
    tt = _tiktok_cookie(pares.get("tiktok", ""))
    arena_estado, arena_novo = _arena(pares.get("arena_yt", ""))
    if arena_novo and arena_novo != pares.get("arena_yt"):
        pares["arena_yt"] = arena_novo
    _guardar_sessoes(pares, {"ultimo_probe": _agora()})
    mortos = [nome for nome, st in (("youtube", yt), ("tiktok", tt), ("arena_yt", arena_estado)) if st != "ok"]
    _marcar(
        "cookies-renova",
        "renovou o que o servidor ainda aceita" if not mortos else "sem renovacao de servidor para " + ",".join(mortos),
        bilibili="ok" if nav.get("ok") else nav.get("motivo"),
        youtube=yt,
        tiktok=tt,
        arena_yt=arena_estado,
    )
    doc = _estado()
    doc["cookies"] = {
        "bilibili": "ok" if nav.get("ok") else nav.get("motivo"),
        "youtube": yt,
        "tiktok": tt,
        "arena_yt": arena_estado,
        "quando": _agora(),
    }
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
        "comentarios": len(comentarios),
        "respostas_novas": novos,
        "quando": _agora(),
    }
    _gravar(ESTADO, doc)
    _marcar(
        "bilibili-analisa",
        f"views {arq.get('views')} likes {arq.get('likes')} comentarios {len(comentarios)} respostas {novos}",
    )


def ciclo_bilibili_cria() -> None:
    cookie = _sessoes().get("bilibili", "")
    nav = _bilibili_nav(cookie)
    if not nav.get("ok"):
        _marcar("bilibili-cria", "sem sessao, nao posto", proxima=_agora() + CHECAGEM_S)
        return
    arq = _bilibili_arquivo(cookie)
    if arq.get("ok") and not arq.get("publico") and not arq.get("vazio"):
        _marcar("bilibili-cria", "uma peca ainda nao publica, nao posto outra", estado=arq.get("estado"), proxima=_agora() + CHECAGEM_S)
        return
    _marcar("bilibili-cria", "sem peca nova pronta, nao invento post", proxima=_agora() + INSPIRA_POS_POST_S)


def ciclo_youtube_analisa() -> None:
    pub = _youtube_publico()
    doc = _estado()
    doc["youtube"] = {**pub, "quando": _agora(), "editou_short_13": False}
    _gravar(ESTADO, doc)
    if not pub.get("ok"):
        _marcar("youtube-analisa", "sem leitura publica")
        return
    _marcar("youtube-analisa", f"views {pub.get('views')} likes {pub.get('likes')} sem resposta de comentario")


def ciclo_youtube_cria() -> None:
    st = _youtube_cookie(_sessoes().get("youtube", ""))
    if st != "ok":
        _marcar("youtube-cria", "cookie morto, nao publico e nao edito o Short 13", proxima=_agora() + COOKIE_MORTO_S)
        return
    _marcar("youtube-cria", "sem pacote de video titulo descricao e hora, nao publico", proxima=_agora() + INSPIRA_POS_POST_S)


def ciclo_tiktok_analisa() -> None:
    st = _tiktok_cookie(_sessoes().get("tiktok", ""))
    doc = _estado()
    doc["tiktok"] = {"cookie": st, "quando": _agora(), "republicou": False, "views": None if st != "ok" else 0}
    _gravar(ESTADO, doc)
    if st != "ok":
        _marcar("tiktok-analisa", "sem sessao, nao invento view nem like")
        return
    _marcar("tiktok-analisa", "sessao entrou, leitura fina no proximo ciclo")


def ciclo_tiktok_cria() -> None:
    st = _tiktok_cookie(_sessoes().get("tiktok", ""))
    if st != "ok":
        _marcar("tiktok-cria", "sem sessao, nao republico e nao posto", proxima=_agora() + COOKIE_MORTO_S)
        return
    _marcar("tiktok-cria", "nao republico o que ja foi agendado", proxima=_agora() + INSPIRA_POS_POST_S)


CICLOS = (
    ("cookies-renova", ciclo_cookies),
    ("cookies-vigia", ciclo_vigia),
    ("bilibili-analisa", ciclo_bilibili_analisa),
    ("bilibili-cria", ciclo_bilibili_cria),
    ("youtube-analisa", ciclo_youtube_analisa),
    ("youtube-cria", ciclo_youtube_cria),
    ("tiktok-analisa", ciclo_tiktok_analisa),
    ("tiktok-cria", ciclo_tiktok_cria),
)


def ciclo() -> None:
    for nome, fn in CICLOS:
        try:
            fn()
        except Exception:
            _marcar(nome, "falhou o ciclo, tenta de novo")


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
