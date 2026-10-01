"""Mão na tela do dono — celular e PC dele, não o desktop do servidor.

O aparelho liga pra fora (poll). A colônia manda ordem curta: abrir app, abrir
aba, print, clique, tecla. Nada de shell. Nada de captcha. Tudo no diário.

O token é derivado da senha do painel + o apelido (celular|pc). Quem não tem
a senha não manda ordem. O valor não volta em resposta de API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

FILA = Path("data/mao.json")
PRINTS = Path("data/mao_prints")
APARELHOS = ("celular", "pc")
ACOES = ("abrir_url", "abrir_app", "print", "clicar", "digitar", "tecla")
TECLAS = ("enter", "tab", "esc", "backspace", "space", "up", "down", "left", "right")
ONLINE_S = 40
EXPIRA_S = 15 * 60
RETRY_S = 90

_APPS_CEL = {
    "whatsapp": "whatsapp", "wpp": "whatsapp", "zap": "whatsapp",
    "instagram": "instagram", "insta": "instagram",
    "telegram": "telegram", "gmail": "gmail", "chrome": "chrome",
    "youtube": "youtube", "mapas": "mapas", "maps": "mapas",
    "camera": "camera", "câmera": "camera", "shopee": "shopee",
    "mercado livre": "mercadolivre", "mercadolivre": "mercadolivre",
    "kiwify": "kiwify",
}
_URLS = {
    "gmail": "https://mail.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "whatsapp web": "https://web.whatsapp.com",
    "kiwify": "https://dashboard.kiwify.com.br",
}
_VERBO = re.compile(
    r"\b(abre|abrir|abra|open|mostra|mostrar|print|foto|clica|clicar|digita|digitar|tela)\b",
    re.I)


def token_de(apelido: str) -> str:
    senha = os.environ.get("ORBE_PANEL_PASSWORD", "").strip()
    if not senha or apelido not in APARELHOS:
        return ""
    return hashlib.sha256(f"orbe-mao:{senha}:{apelido}".encode()).hexdigest()[:32]


def token_ok(apelido: str, dado: str) -> bool:
    esperado = token_de(apelido)
    if not esperado or not dado:
        return False
    return hmac.compare_digest(str(dado).strip(), esperado)


def _carregar() -> dict[str, Any]:
    try:
        return json.loads(FILA.read_text(encoding="utf-8"))
    except Exception:
        return {"ordens": [], "visto": {}}


_ultimo_flush: dict[str, float] = {}


def _salvar(d: dict[str, Any], importante: bool = False) -> None:
    FILA.parent.mkdir(parents=True, exist_ok=True)
    FILA.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    if not importante:
        return
    try:
        __import__("state_backup").sujo()
    except Exception:
        pass


def _limpar(ordens: list[dict]) -> list[dict]:
    agora = time.time()
    saida = []
    for o in ordens:
        if agora - float(o.get("criado") or 0) > EXPIRA_S and o.get("estado") != "feito":
            continue
        saida.append(o)
    return saida[-40:]


def bater(apelido: str) -> None:
    agora = time.time()
    if agora - _ultimo_flush.get(apelido, 0) < 10:
        return
    d = _carregar()
    visto = d.setdefault("visto", {})
    visto[apelido] = agora
    d["ordens"] = _limpar(d.get("ordens") or [])
    _salvar(d)
    _ultimo_flush[apelido] = agora


def online(apelido: str, d: dict | None = None) -> bool:
    d = d or _carregar()
    ts = float((d.get("visto") or {}).get(apelido) or 0)
    return time.time() - ts < ONLINE_S


def estado() -> dict[str, Any]:
    d = _carregar()
    aparelhos = {}
    for a in APARELHOS:
        ts = float((d.get("visto") or {}).get(a) or 0)
        aparelhos[a] = {"online": time.time() - ts < ONLINE_S, "visto_s": int(time.time() - ts) if ts else None}
    fila = [o for o in d.get("ordens") or [] if o.get("estado") in ("fila", "executando")]
    return {"aparelhos": aparelhos, "fila": len(fila)}


def _alvo_limpo(acao: str, alvo: str) -> str:
    alvo = (alvo or "").strip()
    if acao == "abrir_url":
        if not re.match(r"https://[^\s]+$", alvo, re.I):
            raise ValueError("url tem que ser https")
        if len(alvo) > 400:
            raise ValueError("url longa demais")
        return alvo
    if acao == "abrir_app":
        if re.search(r"[;&|`$<>\\]", alvo):
            raise ValueError("app inválido")
        bruto = alvo.lower().strip()
        if re.match(r"^[a-z][a-z0-9_.]{2,80}$", bruto) and "." in bruto:
            return bruto
        nome = re.sub(r"[^a-z0-9 ]", "", bruto).strip()
        if not nome or len(nome) > 40:
            raise ValueError("app inválido")
        return nome
    if acao == "digitar":
        if not alvo or len(alvo) > 500:
            raise ValueError("texto inválido")
        return alvo
    if acao == "tecla":
        t = alvo.lower().strip()
        if t not in TECLAS:
            raise ValueError("tecla não permitida")
        return t
    if acao == "print":
        return ""
    if acao == "clicar":
        return alvo  # "x,y" validado em pedir
    raise ValueError("ação inválida")


def pedir(aparelho: str, acao: str, alvo: str = "", extra: dict | None = None,
          origem: str = "api") -> dict[str, Any]:
    if aparelho not in APARELHOS:
        raise ValueError("aparelho tem que ser celular ou pc")
    if acao not in ACOES:
        raise ValueError("ação não permitida")
    if acao == "clicar":
        ex = extra or {}
        texto = str(ex.get("texto") or alvo or "").strip()
        if texto:
            if len(texto) > 80 or any(c in texto for c in "\n\r"):
                raise ValueError("texto do botão inválido")
            extra = {"texto": texto}
            alvo = texto
        else:
            x, y = int(ex.get("x", -1)), int(ex.get("y", -1))
            if not (0 <= x <= 4000 and 0 <= y <= 4000):
                raise ValueError("clique fora da tela")
            extra = {"x": x, "y": y}
            alvo = ""
    else:
        alvo = _alvo_limpo(acao, alvo)
        extra = {}
    d = _carregar()
    ordem = {"id": uuid.uuid4().hex[:12], "aparelho": aparelho, "acao": acao, "alvo": alvo,
             "extra": extra or {}, "origem": origem, "criado": time.time(), "estado": "fila"}
    d.setdefault("ordens", []).append(ordem)
    d["ordens"] = _limpar(d["ordens"])
    _salvar(d, importante=True)
    try:
        from conciencia import anotar
        anotar(f"mão: pedi {acao} {alvo or extra} no {aparelho}", acao="mao")
    except Exception:
        pass
    return {"ok": True, "id": ordem["id"], "aparelho": aparelho, "acao": acao,
            "online": online(aparelho, d)}


def pegar(aparelho: str) -> dict | None:
    """A próxima ordem deste aparelho. Marca como executando pra não duplicar."""
    d = _carregar()
    agora = time.time()
    escolhida = None
    for o in d.get("ordens") or []:
        if o.get("aparelho") != aparelho:
            continue
        if o.get("estado") == "fila":
            escolhida = o
            break
        if o.get("estado") == "executando" and agora - float(o.get("pegou") or 0) > RETRY_S:
            escolhida = o
            break
    if not escolhida:
        bater(aparelho)
        return None
    visto = d.setdefault("visto", {})
    visto[aparelho] = agora
    escolhida["estado"] = "executando"
    escolhida["pegou"] = agora
    _salvar(d, importante=True)
    _ultimo_flush[aparelho] = agora
    return {"id": escolhida["id"], "acao": escolhida["acao"], "alvo": escolhida.get("alvo") or "",
            "extra": escolhida.get("extra") or {}}


def resultado(aparelho: str, oid: str, ok: bool, resumo: str, imagem: str = "") -> dict[str, Any]:
    d = _carregar()
    achou = None
    for o in d.get("ordens") or []:
        if o.get("id") == oid and o.get("aparelho") == aparelho:
            achou = o
            break
    if not achou:
        return {"ok": False, "motivo": "ordem não encontrada"}
    achou["estado"] = "feito"
    achou["ok"] = bool(ok)
    achou["resumo"] = (resumo or "")[:300]
    achou["feito_em"] = time.time()
    _salvar(d, importante=True)
    if imagem and len(imagem) < 3_000_000:
        try:
            import base64
            PRINTS.mkdir(parents=True, exist_ok=True)
            bruto = base64.b64decode(imagem)
            ext = "png" if bruto[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
            (PRINTS / f"{oid}.{ext}").write_bytes(bruto)
            achou["print"] = f"{oid}.{ext}"
            _salvar(d, importante=False)
            # olhada, não arquivo. some em 10 min e não entra no backup.
            for velho in PRINTS.glob("*"):
                try:
                    if time.time() - velho.stat().st_mtime > 600:
                        velho.unlink()
                except Exception:
                    pass
        except Exception:
            pass
    try:
        from conciencia import anotar
        anotar(f"mão {aparelho}: {achou.get('acao')} → {achou['resumo'][:120]}", acao="mao")
    except Exception:
        pass
    if achou.get("origem") == "telegram":
        _avisar_telegram(achou)
    return {"ok": True}


def consultar(oid: str) -> dict[str, Any]:
    for o in _carregar().get("ordens") or []:
        if o.get("id") == oid:
            return {"id": o.get("id"), "aparelho": o.get("aparelho"), "acao": o.get("acao"),
                    "estado": o.get("estado"), "ok": o.get("ok"), "resumo": o.get("resumo") or "",
                    "print": o.get("print") or ""}
    return {}


def _avisar_telegram(ordem: dict) -> None:
    try:
        import telegram_sim
        tok, chat = telegram_sim._cfg()
        if not (tok and chat):
            return
        import httpx
        txt = ("✅ " if ordem.get("ok") else "⚠️ ") + f"{ordem.get('aparelho')}: {ordem.get('resumo') or ordem.get('acao')}"
        arq = PRINTS / str(ordem.get("print") or "")
        with httpx.Client(timeout=30) as cx:
            if arq.exists():
                cx.post(f"https://api.telegram.org/bot{tok}/sendPhoto",
                        data={"chat_id": chat, "caption": txt[:200]},
                        files={"photo": arq.read_bytes()})
            else:
                cx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                        data={"chat_id": chat, "text": txt[:400]})
    except Exception:
        pass


def entender(texto: str) -> dict[str, Any] | None:
    """Frase do dono → ordem. None se não for pedido de tela."""
    bruto = (texto or "").strip()
    t = bruto.lower()
    if not t or not _VERBO.search(t):
        return None
    if re.search(r"^[a-z0-9_]{3,24}_(login|senha|email)\s*:", t):
        return None
    aparelho = ""
    if re.search(r"\b(celular|telefone|cll|cel)\b", t):
        aparelho = "celular"
    elif re.search(r"\b(pc|computador|notebook|windows|mac)\b", t):
        aparelho = "pc"
    aba = bool(re.search(r"\b(aba|guia|browser|navegador|chrome)\b", t))

    m = re.search(r"\bclic\w*\s+(\d{1,4})\s*[ ,x]\s*(\d{1,4})", t)
    if m:
        return {"aparelho": aparelho or "pc", "acao": "clicar",
                "extra": {"x": int(m.group(1)), "y": int(m.group(2))}}
    if re.search(r"\b(print|foto da tela|mostra a tela|mostrar a tela)\b", t):
        return {"aparelho": aparelho or "pc", "acao": "print", "alvo": ""}

    m = re.search(r"\bdigit\w*\s+(.+)$", bruto, re.I)
    if m and aparelho:
        return {"aparelho": aparelho, "acao": "digitar", "alvo": m.group(1).strip()[:500]}

    alvo_app = ""
    for nome in sorted(_APPS_CEL, key=len, reverse=True):
        if nome in t:
            alvo_app = _APPS_CEL[nome]
            break
    if not alvo_app:
        for nome in _URLS:
            if nome in t:
                alvo_app = nome
                break
    if not alvo_app:
        m = re.search(r"https://[^\s]+", bruto, re.I)
        if m:
            return {"aparelho": aparelho or "pc", "acao": "abrir_url", "alvo": m.group(0)}
        return None

    if alvo_app in _URLS and (aparelho == "pc" or aba or alvo_app in ("gmail", "github", "whatsapp web")):
        if aparelho == "celular" and alvo_app in _APPS_CEL and not aba:
            return {"aparelho": "celular", "acao": "abrir_app", "alvo": _APPS_CEL.get(alvo_app, alvo_app)}
        return {"aparelho": aparelho or "pc", "acao": "abrir_url", "alvo": _URLS[alvo_app]}
    if not aparelho:
        aparelho = "pc" if aba else "celular"
    if aparelho == "pc" and alvo_app == "whatsapp":
        return {"aparelho": "pc", "acao": "abrir_url", "alvo": "https://web.whatsapp.com"}
    return {"aparelho": aparelho, "acao": "abrir_app", "alvo": alvo_app}


def pedir_texto(texto: str, origem: str = "telegram") -> dict[str, Any] | None:
    ped = entender(texto)
    if not ped:
        return None
    return pedir(ped["aparelho"], ped["acao"], ped.get("alvo") or "", ped.get("extra"), origem=origem)
