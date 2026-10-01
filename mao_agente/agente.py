#!/usr/bin/env python3
"""Mão do Orbe no aparelho do dono. Só abre app/aba, print, clique e tecla.

Não executa shell que venha da rede. Roda em primeiro plano — se fechar, para.
Celular: Termux. PC: Mac/Linux (Windows usa o pc.ps1).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request

ANDROID = os.path.isdir("/data/data/com.termux") or "ANDROID_ROOT" in os.environ
APPS = {
    "whatsapp": "com.whatsapp",
    "instagram": "com.instagram.android",
    "telegram": "org.telegram.messenger",
    "gmail": "com.google.android.gm",
    "chrome": "com.android.chrome",
    "youtube": "com.google.android.youtube",
    "mapas": "com.google.android.apps.maps",
    "camera": "com.android.camera2",
    "shopee": "com.shopee.br",
    "mercadolivre": "com.mercadolibre",
    "kiwify": "https://dashboard.kiwify.com.br",
}


def _http(url: str, token: str, corpo: dict | None = None, timeout: int = 40) -> dict:
    data = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if corpo is not None else "GET",
                                 headers={"x-orbe-mao": token, "Content-Type": "application/json",
                                          "User-Agent": "orbe-mao"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _run(cmd: list[str], timeout: int = 20, limite: int = 160) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, type(exc).__name__
    if p.returncode != 0:
        return False, (p.stderr or p.stdout or "falhou")[:limite]
    return True, (p.stdout or "ok")[:limite]


_URLS_APP = {
    "shopee": ("https://shopee.com.br/", "https://affiliate.shopee.com.br/"),
    "mercadolivre": ("https://www.mercadolivre.com.br/",
                     "https://www.mercadolivre.com.br/l/afiliados-portal-do-afiliado"),
}
_TELA = {
    "com.shopee.br": (
        "com.shopee.br/com.shopee.app.ui.home.HomeActivity_",
        "com.shopee.br/com.shopee.app.ui.home.HomeActivity",
    ),
    "com.mercadolibre": (
        "com.mercadolibre/com.mercadolibre.activities.SplashActivity",
        "com.mercadolibre/com.mercadolibre.activities.MainActivity",
    ),
    "com.whatsapp": (
        "com.whatsapp/.HomeActivity",
        "com.whatsapp/.Main",
    ),
}


def _abriu(ok: bool, msg: str, pkg: str = "") -> bool:
    baixo = (msg or "").lower()
    if (not ok) or "error:" in baixo or "exception" in baixo or "unable to resolve" in baixo or "does not exist" in baixo:
        return False
    if "status: ok" not in baixo:
        return False
    return (not pkg) or pkg.lower() in baixo


_ESQUEMA = {
    "com.google.android.gm": ("https://mail.google.com/", "mailto:orbe@dev.local"),
    "com.whatsapp": ("https://wa.me/",),
    "com.mercadolibre": ("https://www.mercadolivre.com.br/",),
    "com.shopee.br": ("https://shopee.com.br/",),
    "com.google.android.youtube": ("https://www.youtube.com/",),
    "com.instagram.android": ("https://www.instagram.com/",),
    "org.telegram.messenger": ("https://t.me/",),
    "com.google.android.apps.maps": ("geo:0,0?q=Palhoca",),
    "com.android.chrome": ("https://www.google.com/",),
}


def _saida(cmd: list[str], timeout: int = 20, limite: int = 500) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, type(exc).__name__
    texto = " ".join(((proc.stdout or "") + " " + (proc.stderr or "")).split())
    if proc.returncode != 0:
        return False, (texto or "falhou")[:limite]
    return True, (texto or "ok")[:limite]


def _token_pkg(linha: str, pkg: str) -> str:
    for pedaco in linha.replace(":", " ").split():
        if pedaco.startswith(pkg + "/"):
            return pedaco
    return ""


def _componente(pkg: str) -> str:
    """Pergunta ao Android a tela inicial. Vale para qualquer pacote."""
    cmds = []
    if shutil.which("cmd"):
        cmds.append("cmd")
    prefixo = "/data/data/com.termux/files/usr/bin/cmd"
    if prefixo not in cmds:
        cmds.append(prefixo)
    for binario in cmds:
        ok, msg = _saida([binario, "package", "resolve-activity", "--brief",
                          "-a", "android.intent.action.MAIN",
                          "-c", "android.intent.category.LAUNCHER", pkg], 15, 800)
        if not ok:
            continue
        for linha in msg.splitlines():
            achou = _token_pkg(linha.strip(), pkg)
            if achou:
                return achou
    for binario in ("dumpsys", "/system/bin/dumpsys"):
        try:
            proc = subprocess.run([binario, "package", pkg], capture_output=True, text=True, timeout=20)
        except Exception:
            continue
        linhas = ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines()
        for i, linha in enumerate(linhas):
            if pkg not in linha or "/" not in linha:
                continue
            janela = "\n".join(linhas[i:i + 18])
            if "category.LAUNCHER" not in janela:
                continue
            achou = _token_pkg(linha, pkg)
            if achou:
                return achou
    return ""


def _abrir_android(acao: str, alvo: str) -> tuple[bool, str]:
    if acao == "abrir_url" or (acao == "abrir_app" and alvo.startswith("http")):
        url = alvo if acao == "abrir_url" else alvo
        _run(["input", "keyevent", "224"], 5)
        ok, msg = _saida(["am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", url,
                          "-p", "com.android.chrome", "--activity-clear-top", "--activity-single-top"], 25, 400)
        if _abriu(ok, msg):
            return True, "abri no Chrome"
        return False, (msg or "não abri o Chrome")[:160]
    pkg = APPS.get(alvo, "")
    if pkg.startswith("http"):
        return _abrir_android("abrir_url", pkg)
    if not pkg and "." in alvo and " " not in alvo and alvo.replace(".", "").replace("_", "").isalnum():
        pkg = alvo
    if not pkg:
        return False, "não conheço esse app"
    _run(["input", "keyevent", "224"], 5)
    falhas = []
    comp = _componente(pkg)
    candidatos = ((comp,) if comp else ()) + _TELA.get(pkg, ())
    vistos = set()
    for nome in candidatos:
        if not nome or nome in vistos:
            continue
        vistos.add(nome)
        ok, msg = _saida(["am", "start", "-W", "--user", "0", "-n", nome], 25, 500)
        if _abriu(ok, msg, pkg):
            return True, f"abri {alvo}"
        if msg and msg not in ("OSError", "FileNotFoundError"):
            falhas.append(" ".join(msg.split())[:70])
    for url in _ESQUEMA.get(pkg, ()):
        ok, msg = _saida(["am", "start", "-W", "--user", "0", "-a", "android.intent.action.VIEW",
                          "-d", url, "-p", pkg], 25, 500)
        if _abriu(ok, msg, pkg):
            return True, f"abri {alvo}"
        if msg and msg not in ("OSError", "FileNotFoundError"):
            falhas.append(" ".join(msg.split())[:70])
    return False, ("; ".join(falhas) or "o Android não deixou abrir o app")[:160]


def _abrir_pc(acao: str, alvo: str) -> tuple[bool, str]:
    sistema = platform.system()
    if acao == "abrir_url":
        if sistema == "Darwin":
            return _run(["open", alvo])
        if sistema == "Windows":
            return _run(["cmd", "/c", "start", "", alvo])
        return _run(["xdg-open", alvo])
    if sistema == "Darwin":
        return _run(["open", "-a", alvo])
    if sistema == "Windows":
        return _run(["cmd", "/c", "start", "", alvo])
    return _run(["xdg-open", alvo])


def _print() -> tuple[bool, str, str]:
    destino = os.path.join(os.environ.get("TMPDIR") or "/tmp", "orbe-mao.png")
    if ANDROID:
        if shutil.which("termux-screenshot"):
            ok, msg = _run(["termux-screenshot", "-f", destino], 15)
        else:
            ok, msg = _run(["screencap", "-p", destino], 15)
            if not ok:
                return False, "abri, mas o print precisa do Termux:API (pkg install termux-api)", ""
    else:
        sistema = platform.system()
        if sistema == "Darwin":
            ok, msg = _run(["screencapture", "-x", destino])
        else:
            ok, msg = False, "sem ferramenta de print"
            for cmd in (["gnome-screenshot", "-f", destino], ["import", "-window", "root", destino],
                        ["scrot", destino]):
                if shutil.which(cmd[0]):
                    ok, msg = _run(cmd)
                    if ok:
                        break
        if not ok:
            return False, msg or "não consegui o print", ""
    try:
        bruto = open(destino, "rb").read()
    except Exception as exc:
        return False, str(exc)[:120], ""
    if len(bruto) > 1_800_000:
        return True, "print grande demais pra mandar", ""
    return True, "print", base64.b64encode(bruto).decode()


def _clicar(x: int, y: int) -> tuple[bool, str]:
    if ANDROID:
        return _run(["input", "tap", str(x), str(y)])
    sistema = platform.system()
    if sistema == "Darwin":
        return _run(["osascript", "-e", f'tell application "System Events" to click at {{{x}, {y}}}'])
    if shutil.which("xdotool"):
        return _run(["xdotool", "mousemove", str(x), str(y), "click", "1"])
    return False, "clique neste sistema precisa do xdotool"


def _digitar(texto: str) -> tuple[bool, str]:
    if any(c in texto for c in "\n\r;`|$\"\\'"):
        return False, "texto recusado"
    if ANDROID:
        return _run(["input", "text", texto.replace(" ", "%s")])
    if shutil.which("xdotool"):
        return _run(["xdotool", "type", "--", texto])
    if platform.system() == "Darwin":
        return _run(["osascript", "-e", f'tell application "System Events" to keystroke "{texto}"'])
    return False, "digitar neste sistema não está disponível"


def _tecla(nome: str) -> tuple[bool, str]:
    if ANDROID:
        cod = {"enter": "66", "tab": "61", "esc": "111", "backspace": "67", "space": "62",
               "up": "19", "down": "20", "left": "21", "right": "22"}.get(nome)
        if not cod:
            return False, "tecla inválida"
        return _run(["input", "keyevent", cod])
    if shutil.which("xdotool"):
        return _run(["xdotool", "key", nome])
    return False, "tecla neste sistema não está disponível"


def executar(cmd: dict) -> tuple[bool, str, str]:
    acao, alvo = cmd.get("acao"), cmd.get("alvo") or ""
    extra = cmd.get("extra") or {}
    if acao == "abrir_url":
        if not str(alvo).startswith("https://"):
            return False, "url recusada", ""
        fn = _abrir_android if ANDROID else _abrir_pc
        ok, msg = fn("abrir_url", alvo)
        return ok, "abri a aba" if ok else msg, ""
    if acao == "abrir_app":
        if not ANDROID and alvo in ("gmail", "youtube", "github", "kiwify"):
            url = {"gmail": "https://mail.google.com", "youtube": "https://www.youtube.com",
                   "github": "https://github.com", "kiwify": "https://dashboard.kiwify.com.br"}[alvo]
            ok, msg = _abrir_pc("abrir_url", url)
            return ok, "abri a aba" if ok else msg, ""
        fn = _abrir_android if ANDROID else _abrir_pc
        ok, msg = fn("abrir_app", alvo)
        return ok, msg if not ok else f"abri {alvo}", ""
    if acao == "print":
        return _print()
    if acao == "clicar":
        ok, msg = _clicar(int(extra.get("x", 0)), int(extra.get("y", 0)))
        return ok, "cliquei" if ok else msg, ""
    if acao == "digitar":
        ok, msg = _digitar(alvo)
        return ok, "digitei" if ok else msg, ""
    if acao == "tecla":
        ok, msg = _tecla(alvo)
        return ok, "tecla" if ok else msg, ""
    return False, "ação desconhecida", ""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apelido", required=True, choices=("celular", "pc"))
    p.add_argument("--token", default=os.environ.get("ORBE_MAO_TOKEN", ""))
    p.add_argument("--base", default=os.environ.get("ORBE_BASE", "https://orbe-xfzn.onrender.com"))
    args = p.parse_args()
    if not args.token:
        sys.exit("falta o token")
    base = args.base.rstrip("/")
    print(f"mão {args.apelido} ligada em {base}", flush=True)
    if ANDROID:
        subprocess.run(["termux-wake-lock"], capture_output=True)
    while True:
        try:
            fila = _http(f"{base}/api/mao/fila?aparelho={args.apelido}", args.token, timeout=40)
        except Exception as exc:
            print("sem ligação:", type(exc).__name__, flush=True)
            time.sleep(5)
            continue
        cmd = fila.get("comando")
        if not cmd:
            continue
        ok, resumo, imagem = executar(cmd)
        corpo = {"id": cmd.get("id"), "ok": ok, "resumo": resumo, "aparelho": args.apelido}
        if imagem:
            corpo["imagem"] = imagem
        try:
            _http(f"{base}/api/mao/resultado", args.token, corpo, timeout=40)
        except Exception as exc:
            print("não devolvi:", type(exc).__name__, flush=True)
        print(("ok" if ok else "falhou"), resumo, flush=True)


if __name__ == "__main__":
    main()
