"""Ofício dos canais. Sem cookie impresso. Sem view inventada. Sem republicar."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DIA = 24 * 3600
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
PECAS = Path("data/pecas")
TITULOS_BLOQUEADOS = {
    "雨夜空街的三个细节",
    "凌晨三点的厨房灯",
    "A LÂMPADA DA COZINHA",
    "O CORREDOR RESPONDEU",
    "O CORREDOR",
}
ORIGINAIS = {
    "bilibili": [
        ("四点的电梯停在两楼之间", "原创夜细节。电梯停了，没有人按按钮。"),
        ("雨停以后门还是湿的", "原创。雨停了，门还在滴水。"),
        ("冰箱灯比厨房更亮", "原创。半夜只剩冰箱的灯。"),
        ("走廊尽头的钟慢了一分钟", "原创。钟慢了一分钟，走廊是空的。"),
        ("窗上有一只没走的蛾", "原创。蛾停在玻璃上，灯已经关了。"),
    ],
    "youtube": [
        ("A TORNEIRA QUE NÃO FECHOU", "História original. A torneira continuou pingando."),
        ("O RELÓGIO DO CORREDOR", "História original. O relógio atrasou um minuto."),
        ("A CADEIRA QUE MUDOU DE LUGAR", "História original. A cadeira não estava onde ficou."),
        ("O ELEVADOR PAROU NO DOIS", "História original. O elevador parou sem alguém chamar."),
        ("A JANELA ABRIU SEM VENTO", "História original. A janela abriu com a casa quieta."),
    ],
    "tiktok": [
        ("A TORNEIRA QUE NÃO FECHOU", "História original. Não é o corredor."),
        ("O RELÓGIO DO CORREDOR", "História original. Não é a lâmpada."),
        ("A CADEIRA QUE MUDOU DE LUGAR", "História original. Uma mudança só."),
        ("O ELEVADOR PAROU NO DOIS", "História original. Ninguém apertou o botão."),
        ("A JANELA ABRIU SEM VENTO", "História original. A casa estava quieta."),
    ],
}


def agora() -> int:
    return int(time.time())


def hora_local() -> tuple[int, str]:
    t = time.gmtime(time.time() - 3 * 3600)
    return t.tm_hour, time.strftime("%Y-%m-%d", t)


def juizo(ptime: int, views, agora_s: int | None = None) -> str:
    agora_s = agora() if agora_s is None else agora_s
    if not ptime:
        return "sem hora da peca, nao julguei"
    idade = agora_s - int(ptime)
    if idade < DIA:
        return f"ainda nao fez 24h ({idade // 3600}h), views {views}, nao julguei"
    if views is None:
        return "passou 24h, sem view lida, nao inventei"
    gerou = "sim" if int(views) > 0 else "nao"
    return f"depois de 24h views {views}, gerou view {gerou}"


def _get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(120_000).decode("utf-8", "replace")
    except Exception:
        return ""


def _numero(valor) -> int | None:
    try:
        if valor is None or valor == "":
            return None
        return int(valor)
    except (TypeError, ValueError):
        return None


def forma_duracao(segundos) -> str:
    n = _numero(segundos)
    if n is None:
        return "duracao_nao_lida"
    if n <= 60:
        return "curto_ate_60s"
    if n <= 180:
        return "medio_ate_3min"
    return "longo"


def faixa_views(views) -> str:
    n = _numero(views)
    if n is None:
        return "sem_contagem"
    if n >= 1_000_000:
        return "muito_alta"
    if n >= 100_000:
        return "alta"
    if n >= 10_000:
        return "media"
    return "baixa"


def exemplo_criacao(segundos) -> str:
    forma = forma_duracao(segundos)
    if forma == "curto_ate_60s":
        return "gancho falado nos 2 primeiros segundos, um conflito, reviravolta antes do fim"
    if forma == "medio_ate_3min":
        return "abertura curta, tres momentos, reviravolta no ultimo"
    if forma == "longo":
        return "promessa clara no inicio e desfecho proprio"
    return "gancho cedo e desfecho proprio"


def _epoch_iso(value) -> int:
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _aproveitaveis(itens: list[dict]) -> tuple[list[dict], int]:
    """Este canal publica peca curta. Video longo do chart nao vira molde."""
    curtos = []
    longos = 0
    for item in itens[:12]:
        segundos = _numero(item.get("duracao_s"))
        if segundos is not None and segundos > 180:
            longos += 1
            continue
        curtos.append(item)
    return curtos, longos


def estudo_de(plataforma: str, itens: list[dict], licao: str = "") -> dict:
    base, longos = _aproveitaveis(itens or [])
    modelos = []
    vistos = []
    for item in base[:8]:
        titulo = str(item.get("titulo") or "").strip()
        if titulo:
            vistos.append(titulo[:80])
        segundos = item.get("duracao_s")
        forma = forma_duracao(segundos)
        faixa = faixa_views(item.get("views"))
        if any(modelo["forma"] == forma and modelo["faixa_views"] == faixa for modelo in modelos):
            continue
        modelos.append({
            "forma": forma,
            "faixa_views": faixa,
            "exemplo_de_criacao": exemplo_criacao(segundos),
        })
    if modelos:
        nota = "estudei metadados do proprio app; o exemplo e so a estrutura curta, nao copio titulo nem video"
        if longos:
            nota += f"; ignorei {longos} longo(s), nao vou alongar a peca"
    elif itens:
        nota = "li o app, mas o que tinha view era longo; nao alongo esta peca e nao copio titulo"
    else:
        nota = "nao li o que funciona no app, nao inventei modelo"
    return {
        "plataforma": plataforma,
        "quando": agora(),
        "leu": bool(itens),
        "modelos": modelos[:6],
        "titulos_vistos": vistos[:8],
        "licao": licao or "ainda sem julgamento de 24h do proprio canal",
        "nota": nota,
    }


def estudo_publico(estudo: dict | None) -> dict:
    estudo = estudo or {}
    return {
        "plataforma": estudo.get("plataforma"),
        "quando": estudo.get("quando") or 0,
        "leu": bool(estudo.get("leu")),
        "modelos": estudo.get("modelos") or [],
        "vistos": len(estudo.get("titulos_vistos") or []),
        "licao": estudo.get("licao") or "",
        "nota": estudo.get("nota") or "",
    }


def _bilibili_itens() -> list[dict]:
    bruto = _get("https://api.bilibili.com/x/web-interface/popular?ps=8&pn=1")
    try:
        doc = json.loads(bruto)
    except Exception:
        return []
    itens = []
    for item in ((doc.get("data") or {}).get("list") or [])[:8]:
        stat = item.get("stat") or {}
        itens.append({
            "titulo": str(item.get("title") or "")[:80],
            "views": stat.get("view"),
            "duracao_s": item.get("duration"),
        })
    return itens


def inspirar(plataforma: str, itens: list[dict] | None = None, licao: str = "") -> dict:
    if itens is None and plataforma == "bilibili":
        itens = _bilibili_itens()
    return estudo_de(plataforma, itens or [], licao)


def _groq(system: str, user: str) -> str:
    chave = os.environ.get("ORBE_GROQ_API_KEY", "").strip()
    if not chave:
        return ""
    corpo = json.dumps({
        "model": "openai/gpt-oss-20b",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 280,
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=corpo,
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            doc = json.loads(r.read().decode())
        return str(((doc.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    except Exception:
        return ""


def roteiro(plataforma: str, notas: dict, usados: set[str]) -> dict:
    import canais_papel as papel
    modelos = notas.get("modelos") or []
    exemplos = [str(item.get("exemplo_de_criacao") or "") for item in modelos if item.get("exemplo_de_criacao")]
    semana = papel.hipotese(notas)
    system = (
        "Escreva uma regra noturna original, nao um objeto com nome. "
        "O lugar e a escola vazia a noite. O titulo e uma proibicao ou uma ausencia. "
        "O titulo nao pode nomear lampada, corredor, relogio, cadeira, elevador, torneira, janela, cozinha ou chamada. "
        "Nao copie titulo, frase, nome ou video. "
        "A descricao e somente a frase da regra, sem dizer que foi feita por agente ou narracao sintetica. "
        "Devolva so JSON com titulo, fala e objeto. "
        "Bilibili em chines. TikTok em portugues. "
        "Titulo com no maximo 60 caracteres. Fala com no maximo 80 caracteres."
    )
    user = (
        "Hipotese da semana: " + semana["forma"]
        + ". Papel visual de hoje: " + semana["papel"]
        + ". Exemplo de estrutura, sem copiar: " + " | ".join(exemplos[:3])
        + ". Licao: " + str(notas.get("licao") or "troque o gancho, historia nova")
    )
    texto = _groq(system, user)
    peca = {}
    if texto:
        try:
            ini = texto.find("{")
            fim = texto.rfind("}")
            doc = json.loads(texto[ini:fim + 1]) if ini >= 0 else {}
            peca = {
                "titulo": str(doc.get("titulo") or "").strip()[:60],
                "fala": str(doc.get("fala") or "").strip()[:80],
                "objeto": str(doc.get("objeto") or "marca")[:24],
                "origem": "regra pela ia, assunto escondido, sem copiar titulo",
            }
        except Exception:
            peca = {}
    vistos = set(usados) | set(notas.get("titulos_vistos") or []) | TITULOS_BLOQUEADOS
    if not papel.peca_valida(peca, vistos) or any(peca.get("titulo") and (peca["titulo"] in item or item in peca["titulo"]) for item in vistos if item):
        peca = papel.banco(plataforma, vistos)
    else:
        peca = papel.completar(peca, plataforma)
    peca["papel"] = semana["papel"]
    return peca


def _ffmpeg() -> str:
    achado = shutil.which("ffmpeg")
    if achado:
        return achado
    for pasta in (Path("/usr/bin"), Path("/tmp/ff")):
        if not pasta.exists():
            continue
        for item in pasta.rglob("ffmpeg"):
            if item.is_file() and os.access(item, os.X_OK):
                return str(item)
    return ""


def render_mp4(destino: Path, titulo: str, fala: str, peca: dict | None = None) -> str:
    import canais_papel as papel
    pronta = peca or {"titulo": titulo, "fala": fala, "descricao": fala}
    if not pronta.get("palavra"):
        pronta = papel.completar(pronta, "bilibili")
    return papel.render_loop(destino, pronta)


def _bili_json(url: str, cookie: str, data: bytes | None = None, method: str | None = None, timeout: int = 60) -> tuple[int, dict, object]:
    headers = {"User-Agent": UA, "Cookie": cookie, "Referer": "https://member.bilibili.com/platform/upload/video/frame"}
    if data is not None and method != "PUT":
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            bruto = r.read().decode("utf-8", "replace")
            return r.status, json.loads(bruto or "{}"), r.headers
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            doc = {}
        return e.code, doc, e.headers
    except Exception:
        return 0, {}, None


def bili_publicar(cookie: str, arquivo: Path, titulo: str, descricao: str) -> dict:
    if not cookie or not arquivo.exists():
        return {"ok": False, "motivo": "sem_arquivo_ou_sessao"}
    if titulo in TITULOS_BLOQUEADOS:
        return {"ok": False, "motivo": "titulo_ja_usado"}
    csrf = ""
    for parte in cookie.split(";"):
        parte = parte.strip()
        if parte.startswith("bili_jct="):
            csrf = parte.split("=", 1)[1]
    if not csrf:
        return {"ok": False, "motivo": "sem_csrf"}
    nome = arquivo.name
    tamanho = arquivo.stat().st_size
    query = urllib.parse.urlencode({
        "r": "upos", "profile": "ugcupos/bup", "ssl": "0",
        "version": "2.11.0", "build": "2110000", "name": nome, "size": str(tamanho),
    })
    code, pre, _ = _bili_json(f"https://member.bilibili.com/preupload?{query}", cookie)
    if pre.get("OK") != 1:
        return {"ok": False, "motivo": f"preupload_{code or pre.get('code') or 'falhou'}"}
    auth = pre.get("auth") or ""
    endpoint = pre.get("endpoint") or ""
    if endpoint.startswith("//"):
        endpoint = "https:" + endpoint
    upos = str(pre.get("upos_uri") or "")
    biz_id = pre.get("biz_id")
    if not auth or not endpoint or not upos or not biz_id:
        return {"ok": False, "motivo": "preupload_incompleto"}
    url = endpoint.rstrip("/") + "/" + upos.replace("upos://", "")
    headers_up = {"User-Agent": UA, "X-Upos-Auth": auth}
    req = urllib.request.Request(f"{url}?uploads&output=json", data=b"", method="POST", headers={**headers_up, "Content-Length": "0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            aberto = json.loads(r.read().decode() or "{}")
    except Exception:
        return {"ok": False, "motivo": "upos_nao_abriu"}
    upload_id = aberto.get("upload_id")
    if not upload_id:
        return {"ok": False, "motivo": "sem_upload_id"}
    chunk = int(pre.get("chunk_size") or 4 * 1024 * 1024)
    total = max(1, (tamanho + chunk - 1) // chunk)
    with arquivo.open("rb") as handle:
        for i in range(total):
            pedaco = handle.read(chunk)
            inicio = i * chunk
            params = urllib.parse.urlencode({
                "uploadId": upload_id, "chunks": total, "total": tamanho, "chunk": i,
                "size": len(pedaco), "partNumber": i + 1, "start": inicio, "end": inicio + len(pedaco),
            })
            req = urllib.request.Request(f"{url}?{params}", data=pedaco, method="PUT", headers=headers_up)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    if r.status not in (200, 201):
                        return {"ok": False, "motivo": f"chunk_{r.status}"}
            except Exception:
                return {"ok": False, "motivo": "chunk_falhou"}
    parts = [{"partNumber": i + 1, "eTag": "etag"} for i in range(total)]
    fim = urllib.parse.urlencode({"name": nome, "uploadId": upload_id, "biz_id": biz_id, "output": "json", "profile": "ugcupos/bup"})
    req = urllib.request.Request(
        f"{url}?{fim}",
        data=json.dumps({"parts": parts}).encode(),
        method="POST",
        headers={**headers_up, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            done = json.loads(r.read().decode() or "{}")
    except Exception:
        return {"ok": False, "motivo": "upos_nao_fechou"}
    if done.get("OK") != 1:
        return {"ok": False, "motivo": "upos_recusou_fecho"}
    filename = upos.split("/")[-1].rsplit(".", 1)[0]
    corpo = {
        "copyright": 1,
        "tid": 21,
        "title": titulo[:80],
        "desc": descricao[:300],
        "tag": "原创,夜校,规则",
        "desc_format_id": 9999,
        "dynamic": "",
        "interactive": 0,
        "act_reserve_create": 0,
        "no_disturbance": 0,
        "no_reprint": 1,
        "subtitle": {"open": 0, "lan": ""},
        "dolby": 0,
        "lossless_music": 0,
        "up_selection_reply": False,
        "up_close_reply": False,
        "up_close_danmu": False,
        "web_os": 3,
        "recreate": -1,
        "csrf": csrf,
        "videos": [{"filename": filename, "title": titulo[:80], "desc": "", "cid": biz_id}],
    }
    envio = urllib.parse.urlencode({"ts": int(time.time() * 1000), "csrf": csrf})
    code, resp, _ = _bili_json(
        f"https://member.bilibili.com/x/vu/web/add/v3?{envio}",
        cookie,
        data=json.dumps(corpo).encode(),
        method="POST",
    )
    if resp.get("code") == 0 and (resp.get("data") or {}).get("bvid"):
        arquivo.unlink(missing_ok=True)
        return {"ok": True, "bvid": resp["data"]["bvid"], "motivo": "publicado"}
    return {"ok": False, "motivo": f"add_{resp.get('code') or code}"}


def tentar_acordar(cookie: str, pacote: dict) -> dict:
    if not cookie:
        return {"aceitou": False, "motivo": "sem_sessao_arena"}
    corpo = json.dumps({
        "mode": "agent",
        "text": (
            "Monitore os agentes dos canais. Nao invente view. "
            "Diga o que esta em ordem e o que nao esta. Pacote: "
            + json.dumps(pacote, ensure_ascii=False)[:2500]
        ),
    }).encode()
    for url in (
        "https://arena.ai/api/agent/conversations",
        "https://arena.ai/api/conversations",
    ):
        req = urllib.request.Request(
            url,
            data=corpo,
            method="POST",
            headers={
                "User-Agent": UA,
                "Cookie": cookie,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://arena.ai",
                "Referer": "https://arena.ai/agent",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return {"aceitou": True, "motivo": "arena_aceitou", "monitorei": False}
        except urllib.error.HTTPError as e:
            ultimo = e.code
        except Exception:
            ultimo = 0
    return {"aceitou": False, "motivo": f"arena_http_{ultimo}", "monitorei": False}


def informar(texto: str) -> bool:
    tok = os.environ.get("ORBE_TG_TOKEN", "").strip()
    chat = os.environ.get("ORBE_TG_CHAT", "").strip()
    if not tok or not chat:
        return False
    corpo = json.dumps({"chat_id": chat, "text": texto[:3500]}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{tok}/sendMessage",
        data=corpo,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def pacote(doc: dict) -> dict:
    agentes = {}
    for nome, item in (doc.get("agentes") or {}).items():
        if isinstance(item, dict):
            agentes[nome] = str(item.get("ultimo") or "")[:140]
    return {
        "bilibili": {k: (doc.get("bilibili") or {}).get(k) for k in ("bvid", "estado", "publico", "views", "likes")},
        "youtube": {k: (doc.get("youtube") or {}).get(k) for k in ("ok", "video", "views", "likes", "motivo")},
        "tiktok": {k: (doc.get("tiktok") or {}).get(k) for k in ("conta", "seguidores", "curtidas", "videos", "cookie")},
        "cookies": doc.get("cookies") or {},
        "agentes": agentes,
    }


def em_ordem(doc: dict) -> tuple[bool, str]:
    cookies = doc.get("cookies") or {}
    motivos = []
    from canais_24h import AGENTES
    faltam = set(AGENTES)-set(doc.get("agentes") or {})
    if faltam:
        motivos.append("agentes sem estado: "+", ".join(sorted(faltam)))
    if not youtube_token_configurado() or cookies.get("youtube") != "ok":
        motivos.append("YouTube sem OAuth valido; nao publica")
    leitura = doc.get("youtube") or {}
    videos = leitura.get("videos") or []
    views_ok = leitura.get("views") is not None or any(v.get("views") is not None for v in videos)
    if not leitura.get("ok") or not views_ok or agora()-int(leitura.get("quando") or 0)>3600:
        motivos.append("YouTube sem contagens oficiais recentes")
    recentes = []
    for video in videos:
        tags = video.get("tags") or []
        if not any(str(tag).startswith("orbe-original-") for tag in tags):
            continue
        publicado = _epoch_iso(video.get("publicado_em"))
        if publicado and agora() - publicado < DIA:
            recentes.append(video)
    if len(recentes) >= 2:
        motivos.append("YouTube tem dois originais no mesmo dia; nao posto outro antes de 24h do ultimo")
    if cookies.get("bilibili") != "ok":
        motivos.append("Bilibili sem sessao")
    bili = doc.get("bilibili") or {}
    if bili.get("views") is None or agora()-int(bili.get("quando") or 0)>3600:
        motivos.append("Bilibili sem contagem recente")
    if cookies.get("tiktok") != "ok":
        motivos.append("TikTok sem sessao")
    tt = doc.get("tiktok") or {}
    if any(tt.get(k) is None for k in ("seguidores", "curtidas", "videos")) or agora()-int(tt.get("quando") or 0)>3600:
        motivos.append("TikTok sem contagens recentes")
    metricas = tt.get("videos_metricas") or []
    if not metricas or any(item.get("views") is None for item in metricas):
        motivos.append("TikTok ainda sem contagem por video para avaliar 24h")
    for nome, item in (doc.get("agentes") or {}).items():
        if item.get("saude") == "falha" or str(item.get("ultimo") or "").startswith("falhou o ciclo"):
            motivos.append(nome+": "+str(item.get("motivo") or "ciclo com pendencia"))
        elif agora()-int(item.get("quando") or 0)>7200:
            motivos.append(nome+": sem sinal recente")
    return (not motivos), "; ".join(dict.fromkeys(motivos))


def _linha_youtube(yt: dict) -> str:
    originais = []
    for video in yt.get("videos") or []:
        tags = video.get("tags") or []
        if any(str(tag).startswith("orbe-original-") for tag in tags):
            views = video.get("views")
            originais.append(f"{video.get('titulo') or 'sem titulo'} views {views if views is not None else 'nao lido'}")
    if originais:
        return "YouTube originais: " + "; ".join(originais[:3]) + "."
    views = yt.get("views")
    likes = yt.get("likes")
    return f"YouTube: views {views if views is not None else 'nao lido'} likes {likes if likes is not None else 'nao lido'}."


def _linha_tiktok(tt: dict) -> str:
    base = f"TikTok: videos {tt.get('videos')} seguidores {tt.get('seguidores')}."
    metricas = tt.get("videos_metricas") or []
    if not metricas:
        return base + " View por video nao lida."
    novo = metricas[0]
    ar = "no ar" if novo.get("publico") else "nao confirmei no ar"
    return base + f" Ultimo lido {novo.get('titulo') or 'sem titulo'} {ar}, views {novo.get('views')}."


def texto_telegram(dia: str, ordem: bool, motivo: str, doc: dict) -> str:
    bili = doc.get("bilibili") or {}
    yt = doc.get("youtube") or {}
    tt = doc.get("tiktok") or {}
    linhas = [
        f"Canais {dia}.",
        "O chat da Arena nao foi aberto. A Arena recusa esse chamado, e o Chrome no servidor derrubaria os outros agentes.",
        "Quem monitorou: o servidor, com o numero que os agentes leram.",
        f"Esta tudo em ordem: {'sim' if ordem else 'nao'}.",
        f"Motivo: {motivo or 'os ciclos lidos nao mostraram falha'}.",
        f"Bilibili: {bili.get('bvid') or 'sem peca'} {bili.get('estado') or ''} views {bili.get('views') if bili.get('views') is not None else 'nao lido'}.",
        _linha_youtube(yt),
        _linha_tiktok(tt),
        "Numero so entra se o agente leu. Nao publiquei nada neste aviso.",
    ]
    return "\n".join(linhas)


def youtube_token_configurado() -> bool:
    try:
        import youtube_api
        return youtube_api.configurado()
    except Exception:
        return False
