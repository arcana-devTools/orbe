"""YouTube oficial: OAuth renovavel, canal fixo e upload retomavel sem duplicar.
Nao usa cookie/Studio/Chrome; nao edita nem apaga videos existentes.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path

import httpx

CHANNEL = "UCUK8xuQ-os1TjAgRmaRk1QQ"
PROTECTED = {"h6Y-M4AgX6s"}
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3/"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
_LOCK = threading.RLock()
_ACCESS = {"token": "", "expira": 0, "renovado": 0}
_IDENTITY = {"quando": 0, "doc": None}


class YouTubeError(RuntimeError):
    def __init__(self, reason: str, status: int = 0):
        # Nao incluir response.text/URL/headers: podem conter credenciais.
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", reason)[:70]
        self.reason, self.status = safe or "erro", status
        super().__init__(f"YouTube {self.reason} HTTP {status}")


def _vault():
    from secrets_vault import VAULT
    return VAULT


def credenciais() -> dict[str, str]:
    names = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    result = {k: os.environ.get(k, "").strip() for k in names}
    if not all(result.values()):
        try:
            extra = (_vault().get("youtube_oauth") or {}).get("extra") or {}
            for k in names:
                if not result[k]:
                    result[k] = str(extra.get(k) or "").strip()
        except Exception:
            pass
    return result


def configurado() -> bool:
    return all(credenciais().values())


def guardar(refresh: str, scopes: str = SCOPE) -> bool:
    """Cofre cifrado primeiro; env do Render preserva as demais variaveis."""
    credentials = credenciais()
    credentials["YOUTUBE_REFRESH_TOKEN"] = refresh
    if not all(credentials.values()):
        raise YouTubeError("cliente_ausente")
    extra = {**credentials, "scope": scopes, "canal": CHANNEL, "autorizado_em": int(time.time())}
    _vault().put("youtube_oauth", extra=extra)
    for k, v in credentials.items():
        os.environ[k] = v
    from render_admin import aplicar_env
    aplicar_env(credentials)
    return True


def _reason(response: httpx.Response) -> str:
    try:
        doc = response.json()
        err = doc.get("error") or {}
        if isinstance(err, str):
            return err
        details = err.get("errors") or []
        return str((details[0] if details else {}).get("reason") or err.get("status") or "api_recusou")
    except Exception:
        return "api_recusou"


def access_token(force: bool = False) -> str:
    with _LOCK:
        if not force and _ACCESS["token"] and _ACCESS["expira"] > time.time()+90:
            return str(_ACCESS["token"])
        c = credenciais()
        if not all(c.values()):
            raise YouTubeError("oauth_ausente")
        try:
            r = httpx.post(TOKEN_URL, data={"grant_type": "refresh_token", "client_id": c["YOUTUBE_CLIENT_ID"],
                "client_secret": c["YOUTUBE_CLIENT_SECRET"], "refresh_token": c["YOUTUBE_REFRESH_TOKEN"]}, timeout=30)
        except Exception:
            raise YouTubeError("rede_renovacao") from None
        if r.status_code != 200:
            _ACCESS.update(token="", expira=0)
            raise YouTubeError(_reason(r), r.status_code)
        doc = r.json()
        token = str(doc.get("access_token") or "")
        if not token:
            raise YouTubeError("resposta_sem_access")
        _ACCESS.update(token=token, expira=time.time()+int(doc.get("expires_in") or 3600), renovado=int(time.time()))
        return token


def request(method: str, path: str, *, params=None, json=None) -> dict:
    for attempt in range(2):
        token = access_token(force=bool(attempt))
        try:
            r = httpx.request(method, API+path, params=params, json=json,
                headers={"Authorization": "Bearer "+token}, timeout=35)
        except Exception:
            raise YouTubeError("rede_api") from None
        if r.status_code == 401 and not attempt:
            continue
        if r.status_code >= 400:
            raise YouTubeError(_reason(r), r.status_code)
        try:
            return r.json()
        except Exception:
            raise YouTubeError("resposta_invalida") from None
    raise YouTubeError("autorizacao_recusada", 401)


def identidade(force: bool = False) -> dict:
    if not force and _IDENTITY["doc"] and time.time()-_IDENTITY["quando"] < 600:
        return dict(_IDENTITY["doc"])
    doc = request("GET", "channels", params={"part": "id,snippet,contentDetails,statistics", "mine": "true"})
    items = doc.get("items") or []
    match = next((i for i in items if i.get("id") == CHANNEL), None)
    if not match:
        raise YouTubeError("canal_diferente_nao_envio")
    result = {"canal": CHANNEL, "titulo": (match.get("snippet") or {}).get("title"),
        "uploads": ((match.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads"),
        "estatisticas": match.get("statistics") or {}}
    _IDENTITY.update(doc=result, quando=time.time())
    return result


def probe(force: bool = False) -> dict:
    try:
        if force:
            access_token(force=True)
        identity = identidade(force=force)
        return {"ok": True, "estado": "ok", "origem": "oauth_oficial", "canal": identity["canal"],
            "renovado_em": _ACCESS["renovado"], "expira_em": int(_ACCESS["expira"])}
    except YouTubeError as exc:
        return {"ok": False, "estado": exc.reason, "origem": "oauth_oficial", "motivo": exc.reason}
    except Exception:
        return {"ok": False, "estado": "erro_oauth", "motivo": "erro_oauth"}


def _number(stats: dict, key: str):
    value = stats.get(key)
    return int(value) if value is not None else None


def video(item: dict) -> dict:
    s, st, stats = item.get("snippet") or {}, item.get("status") or {}, item.get("statistics") or {}
    return {"video": item.get("id"), "titulo": s.get("title"), "publicado_em": s.get("publishedAt"),
        "privacidade": st.get("privacyStatus"), "upload_status": st.get("uploadStatus"),
        "processamento": (item.get("processingDetails") or {}).get("processingStatus"),
        "publishAt": st.get("publishAt"), "views": _number(stats, "viewCount"), "likes": _number(stats, "likeCount"),
        "comentarios": _number(stats, "commentCount"), "tags": s.get("tags") or []}


def videos(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    doc = request("GET", "videos", params={"part": "snippet,status,statistics,contentDetails,processingDetails", "id": ",".join(ids[:50])})
    return [video(i) for i in doc.get("items") or []]


def recentes() -> list[dict]:
    identity = identidade()
    if not identity.get("uploads"):
        raise YouTubeError("playlist_ausente")
    doc = request("GET", "playlistItems", params={"part": "contentDetails", "playlistId": identity["uploads"], "maxResults": 50})
    ids = [i.get("contentDetails", {}).get("videoId") for i in doc.get("items") or []]
    return videos([i for i in ids if i])


def _chart(categoria: str | None = None) -> list[dict]:
    params = {"part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": "BR", "maxResults": 15}
    if categoria:
        params["videoCategoryId"] = categoria
    doc = request("GET", "videos", params=params)
    records = []
    for i in doc.get("items") or []:
        s, st = i.get("snippet") or {}, i.get("statistics") or {}
        records.append({"id": i.get("id"), "titulo": str(s.get("title") or "")[:120],
            "descricao": str(s.get("description") or "")[:220], "duracao": (i.get("contentDetails") or {}).get("duration"),
            "views": _number(st, "viewCount"), "likes": _number(st, "likeCount")})
    return records


def tendencias() -> dict:
    identidade()
    records = _chart()
    vistos = {item.get("id") for item in records}
    try:
        for item in _chart("24"):
            if item.get("id") not in vistos:
                records.append(item)
                vistos.add(item.get("id"))
    except YouTubeError:
        pass
    if not records:
        raise YouTubeError("sem_tendencia_lida")
    return {"plataforma": "youtube", "quando": int(time.time()), "leu": True, "amostras": records,
        "formatos": ["observar duracao, abertura e promessa dos metadados atuais", "gancho curto e desfecho original, sem copiar titulos"],
        "nota": "metadados e contagens oficiais; nao afirmo que assisti os videos completos"}


def comentarios() -> list[dict]:
    identidade()
    doc = request("GET", "commentThreads", params={"part": "snippet,replies", "allThreadsRelatedToChannelId": CHANNEL,
        "order": "time", "textFormat": "plainText", "maxResults": 30})
    result = []
    for i in doc.get("items") or []:
        s = i.get("snippet") or {}
        top = s.get("topLevelComment") or {}
        ts = top.get("snippet") or {}
        result.append({"id": top.get("id"), "texto": ts.get("textOriginal") or ts.get("textDisplay") or "",
            "publicado_em": ts.get("publishedAt"), "video": s.get("videoId"), "pode_responder": bool(s.get("canReply")),
            "autor": (ts.get("authorChannelId") or {}).get("value"),
            "respondeu_dono": any(((r.get("snippet") or {}).get("authorChannelId") or {}).get("value") == CHANNEL
                for r in (i.get("replies") or {}).get("comments") or [])})
    return result


def responder(parent: str, text: str, observed: dict) -> str:
    if not parent or observed.get("id") != parent or not observed.get("pode_responder") or observed.get("autor") == CHANNEL:
        raise YouTubeError("sem_comentario_real")
    if observed.get("respondeu_dono"):
        raise YouTubeError("ja_respondido")
    if not text.strip() or len(text) > 350 or re.search(r"https?://|www\.", text, re.I):
        raise YouTubeError("resposta_inadequada")
    identidade()
    doc = request("POST", "comments", params={"part": "snippet"}, json={"snippet": {"parentId": parent, "textOriginal": text}})
    if not doc.get("id"):
        raise YouTubeError("resposta_sem_id")
    return str(doc["id"])


def _filehash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publicar(path: Path, metadata: dict, job_id: str) -> dict:
    """Uma sessao por job; nunca inicia de novo se ja enviou bytes.
    A URL de upload fica no cofre cifrado, nao no estado publico.
    """
    identidade(force=True)
    if not re.fullmatch(r"[a-f0-9]{16}", job_id):
        raise YouTubeError("job_invalido")
    if metadata.get("id") or metadata.get("video") in PROTECTED:
        raise YouTubeError("video_existente_protegido")
    if not path.is_file() or path.stat().st_size < 5000:
        raise YouTubeError("sem_original_pronto")
    vault = _vault()
    account = "youtube_upload_"+job_id
    saved = (vault.get(account) or {}).get("extra") or {}
    if saved.get("video"):
        return {"id": saved["video"], "status": saved.get("status") or {}}
    size = path.stat().st_size
    token = access_token()
    url = saved.get("url")
    with httpx.Client(timeout=90, follow_redirects=False) as cx:
        if not url:
            # Se a sessao anterior acabou apos envio incerto, nao repetir.
            if saved.get("iniciou"):
                raise YouTubeError("envio_incerto_nao_repetir")
            try:
                r = cx.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"}, json=metadata,
                    headers={"Authorization": "Bearer "+token, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
            except Exception:
                raise YouTubeError("inicio_upload_rede") from None
            if r.status_code >= 400:
                raise YouTubeError(_reason(r), r.status_code)
            url = r.headers.get("Location") or ""
            if urllib.parse.urlsplit(url).scheme != "https" or urllib.parse.urlsplit(url).hostname not in ("www.googleapis.com", "youtube.googleapis.com"):
                raise YouTubeError("sem_sessao_upload")
            saved = {"url": url, "tamanho": size, "sha256": _filehash(path), "iniciou": True}
            vault.put(account, extra=saved)
        elif size != int(saved.get("tamanho") or 0) or (saved.get("sha256") and saved["sha256"] != _filehash(path)):
            raise YouTubeError("arquivo_mudou_nao_repito")
        def confirm(r):
            doc = r.json()
            if not doc.get("id"):
                raise YouTubeError("upload_sem_id")
            saved.update(video=doc["id"], status=doc.get("status") or {})
            saved.pop("url", None)
            vault.put(account, extra=saved)
            return doc
        def offset(r):
            if r.status_code != 308:
                raise YouTubeError("sessao_upload_nao_retoma", r.status_code)
            end = re.search(r"bytes=0-(\d+)", r.headers.get("Range") or "")
            return int(end.group(1))+1 if end else 0
        # Consultar tambem na primeira vez: confirma a posicao antes de enviar.
        try:
            r = cx.put(url, content=b"", headers={"Authorization": "Bearer "+token, "Content-Range": f"bytes */{size}"})
        except Exception:
            raise YouTubeError("upload_incerto_aguarda_sessao") from None
        if r.status_code in (200, 201):
            return confirm(r)
        pos = offset(r)
        with path.open("rb") as stream:
            while pos < size:
                stream.seek(pos)
                chunk = stream.read(4*1024*1024)
                last = pos+len(chunk)-1
                try:
                    r = cx.put(url, content=chunk, headers={"Authorization": "Bearer "+token, "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {pos}-{last}/{size}"})
                except Exception:
                    raise YouTubeError("upload_incerto_aguarda_sessao") from None
                if r.status_code in (200, 201):
                    return confirm(r)
                new_pos = offset(r)
                if new_pos <= pos:
                    raise YouTubeError("upload_sem_progresso")
                pos = new_pos
    raise YouTubeError("upload_sem_confirmacao")
