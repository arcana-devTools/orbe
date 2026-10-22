"""Grava a proxima peca antes da janela. Nao publica."""
from __future__ import annotations

import json
from pathlib import Path

PASTA = Path("data/pecas")


def caminho(nome: str) -> tuple[Path, Path]:
    return PASTA / f"{nome}-pronta.mp4", PASTA / f"{nome}-pronta.json"


def ja_pronta(nome: str) -> dict | None:
    video, meta = caminho(nome)
    if not video.is_file() or video.stat().st_size < 1000 or not meta.is_file():
        return None
    try:
        doc = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict) or not doc.get("titulo"):
        return None
    return doc


def limpar(nome: str) -> None:
    for path in caminho(nome):
        path.unlink(missing_ok=True)


def _titulos(obj) -> set[str]:
    saida: set[str] = set()
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if chave in ("titulo", "title") and isinstance(valor, str) and valor.strip():
                saida.add(valor.strip())
            else:
                saida |= _titulos(valor)
    elif isinstance(obj, list):
        for item in obj:
            saida |= _titulos(item)
    return saida


def usados() -> set[str]:
    saida: set[str] = set()
    for path in (Path("data/canais_24h.json"), Path("data/youtube_rotina.json")):
        if not path.is_file():
            continue
        try:
            saida |= _titulos(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    try:
        from canais_oficio import TITULOS_BLOQUEADOS
        saida |= set(TITULOS_BLOQUEADOS)
    except Exception:
        pass
    return saida


def preparar(nome: str, ja_usados: set[str] | None = None) -> str:
    pronta = ja_pronta(nome)
    if pronta:
        return f"peca pronta {pronta.get('titulo')}, sem publicar"
    import canais_oficio as oficio
    import canais_papel as papel
    plataforma = nome if nome in papel.BANCO else "tiktok"
    peca = papel.banco(plataforma, ja_usados if ja_usados is not None else usados())
    peca = papel.completar(peca, plataforma)
    if not papel.peca_valida(peca, ja_usados if ja_usados is not None else usados()):
        return "sem titulo livre no banco, nao gerei video e nao postei"
    video, meta = caminho(nome)
    video.parent.mkdir(parents=True, exist_ok=True)
    erro = oficio.render_mp4(video, peca["titulo"], peca["fala"], peca)
    if erro:
        limpar(nome)
        return erro
    if not video.is_file() or video.stat().st_size < 1000:
        limpar(nome)
        return "video nao ficou no disco, nao postei"
    meta.write_text(json.dumps(peca, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"peca pronta {peca.get('titulo')}, sem publicar"


def main() -> None:
    import asyncio
    import os
    os.environ["ORBE_STATE_RESTORE"] = "force"
    import state_backup
    rest = asyncio.run(state_backup.restaurar(forcar=True))
    print("restaurou", bool(rest.get("ok")), flush=True)
    if not rest.get("ok"):
        raise SystemExit(1)
    livres = usados()
    for nome in ("youtube", "bilibili", "tiktok"):
        print(preparar(nome, livres), flush=True)
        doc = ja_pronta(nome)
        if doc and doc.get("titulo"):
            livres.add(str(doc["titulo"]))
    salvo = asyncio.run(state_backup.salvar(forcar=True))
    print("salvou", bool(salvo.get("ok")), flush=True)
    if not salvo.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
