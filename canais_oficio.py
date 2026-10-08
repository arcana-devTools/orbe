"""Ofício dos canais. Sem cookie impresso. Sem view inventada. Sem republicar."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
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


def inspirar(plataforma: str) -> dict:
    titulos: list[str] = []
    if plataforma == "bilibili":
        bruto = _get("https://api.bilibili.com/x/web-interface/popular?ps=8&pn=1")
        try:
            doc = json.loads(bruto)
            for item in ((doc.get("data") or {}).get("list") or [])[:8]:
                nome = str(item.get("title") or "").strip()
                if nome:
                    titulos.append(nome[:80])
        except Exception:
            titulos = []
    elif plataforma == "youtube":
        bruto = _get("https://www.youtube.com/feed/trending")
        if "viewCount" in bruto or "<title>" in bruto:
            import re
            titulos = [t[:80] for t in re.findall(r'"title":\{"simpleText":"([^"]{4,80})"', bruto)[:8]]
    else:
        bruto = _get("https://www.tiktok.com/api/recommend/item_list/?aid=1988&count=5")
        if bruto.startswith("{"):
            try:
                doc = json.loads(bruto)
                for item in (doc.get("itemList") or [])[:5]:
                    nome = str(item.get("desc") or "").strip()
                    if nome:
                        titulos.append(nome[:80])
            except Exception:
                titulos = []
    return {
        "plataforma": plataforma,
        "quando": agora(),
        "leu": bool(titulos),
        "formatos": titulos[:5],
        "nota": "li titulos publicos, nao copio" if titulos else "nao li tendencia, nao inventei formato",
    }


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
    formatos = notas.get("formatos") or []
    system = (
        "Escreva uma peca original curta de historia noturna. "
        "Nao copie titulo, frase ou video de outra pessoa. "
        "Devolva so JSON com titulo, descricao e fala. "
        "Bilibili em chines. YouTube e TikTok em portugues. "
        "Titulo com no maximo 60 caracteres. Fala com no maximo 180 caracteres."
    )
    user = "Formato visto, so como ideia, nao copiar: " + " | ".join(formatos[:4])
    texto = _groq(system, user)
    titulo, descricao, fala = "", "", ""
    if texto:
        try:
            ini = texto.find("{")
            fim = texto.rfind("}")
            doc = json.loads(texto[ini:fim + 1]) if ini >= 0 else {}
            titulo = str(doc.get("titulo") or "").strip()[:60]
            descricao = str(doc.get("descricao") or "").strip()[:300]
            fala = str(doc.get("fala") or "").strip()[:180]
        except Exception:
            titulo = ""
    copiou = any(titulo and titulo in item for item in formatos) or titulo in TITULOS_BLOQUEADOS or titulo in usados
    if not titulo or not descricao or copiou:
        banco = ORIGINAIS[plataforma]
        escolha = banco[int(time.strftime("%j")) % len(banco)]
        if escolha[0] in usados:
            escolha = next((item for item in banco if item[0] not in usados), banco[0])
        titulo, descricao = escolha
        fala = descricao
        origem = "original fixo, nao copiei tendencia"
    else:
        origem = "original pela ia, sem copiar titulo lido"
    return {"titulo": titulo, "descricao": descricao, "fala": fala, "origem": origem}


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


def render_mp4(destino: Path, titulo: str, fala: str) -> str:
    ff = _ffmpeg()
    if not ff:
        return "sem ffmpeg, nao gerei video e nao posto"
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return "sem pillow, nao gerei video e nao posto"
    destino.parent.mkdir(parents=True, exist_ok=True)
    fonte = None
    for caminho in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if Path(caminho).exists():
            fonte = ImageFont.truetype(caminho, 42)
            break
    if fonte is None:
        fonte = ImageFont.load_default()
    linhas = [titulo[:42], fala[:42], fala[42:84]]
    frames = []
    for i in range(6):
        im = Image.new("RGB", (1280, 720), (10, 14, 28))
        draw = ImageDraw.Draw(im)
        cor = (242, 196, 84) if i % 2 == 0 else (150, 110, 40)
        draw.ellipse((560, 120, 720, 280), fill=cor)
        y = 340
        for linha in linhas:
            if linha.strip():
                draw.text((80, y), linha, fill=(235, 235, 235), font=fonte)
                y += 64
        frame = destino.parent / f"{destino.stem}-{i}.png"
        im.save(frame)
        frames.append(frame)
    cmd = [
        ff, "-y", "-framerate", "1", "-start_number", "0",
        "-i", str(destino.parent / f"{destino.stem}-%d.png"),
        "-f", "lavfi", "-i", "sine=frequency=196:duration=6:sample_rate=44100",
        "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(destino),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except Exception:
        cmd = [ff, "-y", "-framerate", "1", "-start_number", "0", "-i", str(destino.parent / f"{destino.stem}-%d.png"), "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destino)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except Exception:
            return "ffmpeg falhou, nao postei"
    for frame in frames:
        frame.unlink(missing_ok=True)
    if not destino.exists() or destino.stat().st_size < 1000:
        return "video curto demais, nao postei"
    return ""


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
        "tag": "原创,夜晚,细节",
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
    if not youtube_token_configurado():
        motivos.append("YouTube sem token vitalicio, nao publica e nao edita o Short 13")
    if cookies.get("bilibili") != "ok":
        motivos.append("Bilibili sem sessao")
    if cookies.get("tiktok") != "ok":
        motivos.append("TikTok sem sessao")
    return (not motivos), "; ".join(motivos)


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
        f"Bilibili: {bili.get('bvid') or 'sem peca'} {bili.get('estado') or ''} views {bili.get('views')}.",
        f"YouTube: views {yt.get('views')} likes {yt.get('likes')}.",
        f"TikTok: videos {tt.get('videos')} seguidores {tt.get('seguidores')}.",
        "Numero so entra se o agente leu. Nao publiquei nada neste aviso.",
    ]
    return "\n".join(linhas)


def youtube_token_configurado() -> bool:
    return all(os.environ.get(nome, "").strip() for nome in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"))
