"""Papel encontrado, nao corredor. Uma hipotese por semana. Sem credito de fabrica."""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

PAPEIS = ("alto-falante", "lista", "mapa")
HIPOTESE = "regra noturna da escola vazia, assunto escondido, frase grande no quadro, historia nova"
LUGAR = "escola vazia à noite"
AVISO_ANTIGO = "Não é o desenho de 2018."
SPOILERS = (
    "lampada", "lâmpada", "corredor", "relogio", "relógio", "cadeira", "elevador",
    "torneira", "janela", "cozinha", "chamada",
)
FRASES_COPIADAS = (
    "nao e o corredor",
    "não é o corredor",
    "nao e a lampada",
    "não é a lâmpada",
    "historia original",
    "história original",
    "narracao sintetica",
    "narração sintética",
    "criada pelo agente",
    "manda pra quem",
    "manda para quem",
    "o final e pior",
    "o final é pior",
)
BANCO = {
    "tiktok": [
        ("Não conta as luzes do fundo", "marca"),
        ("Falta um nome na lista", "marca"),
        ("Não responde se chamarem você", "marca"),
        ("Essa carteira está sem dono", "marca"),
        ("Proibido ler a última linha", "marca"),
    ],
    "youtube": [
        ("Não conta as luzes do fundo", "marca"),
        ("Falta um nome na lista", "marca"),
        ("Não responde se chamarem você", "marca"),
        ("Essa carteira está sem dono", "marca"),
        ("Proibido ler a última linha", "marca"),
    ],
    "bilibili": [
        ("名单上少了一个名字", "标记"),
        ("不要回应空教室的点名", "标记"),
        ("这张桌子没有主人", "标记"),
        ("禁止看最后一行", "标记"),
        ("别数后面的灯", "标记"),
    ],
}


def agora() -> int:
    return int(time.time())


def hora_local(quando: int | None = None) -> int:
    return time.gmtime((quando or agora()) - 3 * 3600).tm_hour


def manha(quando: int | None = None) -> bool:
    return 9 <= hora_local(quando) < 11


def papel_do_dia(quando: int | None = None) -> str:
    dia = time.gmtime((quando or agora()) - 3 * 3600).tm_yday
    return PAPEIS[dia % 3]


def hipotese(doc: dict | None = None, quando: int | None = None) -> dict:
    quando = agora() if quando is None else quando
    atual = (doc or {}).get("hipotese") or {}
    if atual.get("ate") and quando < int(atual.get("ate") or 0):
        atual["papel"] = papel_do_dia(quando)
        return atual
    return {
        "forma": HIPOTESE,
        "lugar": LUGAR,
        "desde": quando,
        "ate": quando + 7 * 86400,
        "papel": papel_do_dia(quando),
        "nota": "uma hipotese por sete dias; o papel muda, a forma nao",
    }


def _normal(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "").strip().lower())


def entrega_a_coisa(titulo: str, objeto: str = "") -> bool:
    base = _normal(titulo)
    if not base:
        return True
    if objeto and _normal(objeto) and _normal(objeto) in base and _normal(objeto) not in ("marca", "标记"):
        return True
    return any(palavra in base for palavra in SPOILERS)


def e_regra(titulo: str) -> bool:
    texto = str(titulo or "")
    marcas = ("não", "nao", "nunca", "proibido", "sem ", "ninguém", "ninguem", "falta", "禁止", "不要", "别", "没有", "少了")
    baixo = texto.lower()
    return any(marca in baixo or marca in texto for marca in marcas)


def copiou_frase(texto: str) -> bool:
    base = _normal(texto)
    return any(frase in base for frase in FRASES_COPIADAS)


def descricao_limpa(frase: str) -> str:
    linha = str(frase or "").strip().split("\n")[0].strip()
    if not linha or copiou_frase(linha) or "http" in linha.lower():
        return ""
    return linha[:180]


def palavra_capa(titulo: str) -> str:
    for parte in re.split(r"\s+", str(titulo or "").strip()):
        limpa = re.sub(r"[^0-9A-Za-zÀ-ÿ\u4e00-\u9fff]", "", parte)
        if len(limpa) >= 2:
            return limpa[:8].upper()
    return "REGRA"


def peca_valida(peca: dict, usados: set[str] | None = None) -> bool:
    titulo = str(peca.get("titulo") or "").strip()
    frase = descricao_limpa(peca.get("fala") or peca.get("descricao") or titulo)
    if not titulo or not frase or len(titulo) > 60:
        return False
    if not e_regra(titulo) or entrega_a_coisa(titulo, str(peca.get("objeto") or "")):
        return False
    if copiou_frase(titulo) or copiou_frase(frase):
        return False
    if titulo in (usados or set()):
        return False
    return True


def banco(plataforma: str, usados: set[str] | None = None, quando: int | None = None) -> dict:
    usados = usados or set()
    lista = BANCO.get(plataforma) or BANCO["tiktok"]
    dia = time.gmtime((quando or agora()) - 3 * 3600).tm_yday
    for i in range(len(lista)):
        titulo, objeto = lista[(dia + i) % len(lista)]
        if titulo in usados:
            continue
        frase = titulo if titulo.endswith((".", "。")) else titulo + ("。" if plataforma == "bilibili" else ".")
        return {
            "titulo": titulo,
            "descricao": frase,
            "fala": frase,
            "objeto": objeto,
            "palavra": palavra_capa(titulo),
            "papel": papel_do_dia(quando),
            "origem": "regra fixa da semana, sem nomear objeto e sem copiar titulo",
        }
    titulo, objeto = lista[0]
    frase = titulo
    return {
        "titulo": titulo,
        "descricao": frase,
        "fala": frase,
        "objeto": objeto,
        "palavra": palavra_capa(titulo),
        "papel": papel_do_dia(quando),
        "origem": "regra fixa da semana, sem nomear objeto e sem copiar titulo",
    }


def completar(peca: dict, plataforma: str, quando: int | None = None) -> dict:
    titulo = str(peca.get("titulo") or "").strip()[:60]
    frase = descricao_limpa(peca.get("fala") or peca.get("descricao") or titulo)
    if not frase:
        frase = descricao_limpa(titulo)
    return {
        "titulo": titulo,
        "descricao": frase,
        "fala": frase,
        "objeto": str(peca.get("objeto") or "marca")[:24],
        "palavra": palavra_capa(titulo),
        "papel": peca.get("papel") or papel_do_dia(quando),
        "origem": peca.get("origem") or "regra da semana",
        "tiktok_id": peca.get("tiktok_id") or "",
        "aviso_antigo": bool(peca.get("aviso_antigo")),
    }


def regra_de_legenda(texto: str) -> str:
    linha = str(texto or "").split("\n")[0]
    linha = re.split(r"manda\s+pra|manda\s+para|[😨🏫]", linha, maxsplit=1, flags=re.I)[0]
    return linha.strip(" .|")[:60]


def _fonte(tamanho: int, chines: bool = False):
    from PIL import ImageFont
    candidatos = []
    if chines:
        candidatos.extend((
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "data/fonts/SourceHanSansCN-Regular.otf",
        ))
    candidatos.extend((
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ))
    for caminho in candidatos:
        if Path(caminho).exists():
            return ImageFont.truetype(caminho, tamanho)
    if chines:
        destino = Path("data/fonts/SourceHanSansCN-Regular.otf")
        destino.parent.mkdir(parents=True, exist_ok=True)
        url = "https://github.com/adobe-fonts/source-han-sans/raw/release/SubsetOTF/CN/SourceHanSansCN-Regular.otf"
        try:
            urllib.request.urlretrieve(url, destino)
        except Exception:
            return None
        if destino.exists() and destino.stat().st_size > 10000:
            return ImageFont.truetype(destino, tamanho)
    return ImageFont.load_default()


def _cor_papel(papel: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if papel == "lista":
        return (236, 228, 208), (18, 28, 48)
    if papel == "mapa":
        return (14, 28, 24), (244, 214, 120)
    return (10, 18, 32), (242, 196, 84)


def _desenhar(papel: str, palavra: str, frase: str, luz: float, revelar: bool, aviso: bool):
    from PIL import Image, ImageDraw
    fundo, tinta = _cor_papel(papel)
    im = Image.new("RGB", (720, 1280), fundo)
    draw = ImageDraw.Draw(im, "RGBA")
    chines = any("\u4e00" <= char <= "\u9fff" for char in frase + palavra)
    fonte_palavra = _fonte(120, chines)
    fonte_frase = _fonte(42, chines)
    fonte_aviso = _fonte(28, False)
    if fonte_palavra is None or fonte_frase is None:
        raise RuntimeError("sem_fonte")
    if papel == "alto-falante":
        draw.rounded_rectangle((230, 430, 490, 760), radius=28, fill=(24, 36, 52))
        for y in range(470, 730, 36):
            for x in range(270, 460, 36):
                draw.ellipse((x, y, x + 18, y + 18), fill=(70, 86, 104))
    elif papel == "lista":
        for y in range(520, 980, 70):
            draw.line((90, y, 630, y), fill=(40, 48, 60), width=4)
        draw.line((90, 660, 630, 590), fill=(150, 42, 42), width=8)
    else:
        salas = ((80, 500, 300, 700), (340, 500, 620, 700), (80, 760, 300, 980), (420, 760, 640, 980))
        for sala in salas:
            draw.rectangle(sala, outline=tinta, width=6)
        draw.rectangle((300, 760, 420, 980), outline=fundo, width=8)
    if aviso:
        draw.text((48, 48), AVISO_ANTIGO, fill=(236, 232, 220), font=fonte_aviso)
    draw.text((48, 150), palavra[:8], fill=tinta, font=fonte_palavra)
    y = 860
    for linha in _quebrar(frase, 16):
        draw.text((48, y), linha, fill=tinta, font=fonte_frase)
        y += 58
    if luz > 0:
        alpha = int(90 * luz)
        camada = Image.new("RGBA", im.size, (255, 214, 120, alpha))
        im = Image.alpha_composite(im.convert("RGBA"), camada).convert("RGB")
        draw = ImageDraw.Draw(im)
    if revelar:
        draw.ellipse((330, 600, 390, 660), fill=(176, 48, 48))
    return im


def _quebrar(texto: str, limite: int) -> list[str]:
    palavras = str(texto or "").split()
    if len(palavras) <= 1:
        bruto = str(texto or "")
        return [bruto[i:i + limite] for i in range(0, len(bruto), limite)][:4] or [""]
    linhas, atual = [], ""
    for palavra in palavras:
        if len(atual) + len(palavra) + 1 > limite and atual:
            linhas.append(atual)
            atual = palavra
        else:
            atual = (atual + " " + palavra).strip()
    if atual:
        linhas.append(atual)
    return linhas[:4]


def frame(peca: dict, indice: int, total: int = 12):
    papel = peca.get("papel") or papel_do_dia()
    luz = math.sin(math.pi * indice / (total - 1))
    revelar = indice == total // 2
    return _desenhar(
        papel,
        str(peca.get("palavra") or palavra_capa(peca.get("titulo") or "")),
        str(peca.get("fala") or peca.get("descricao") or peca.get("titulo") or ""),
        luz,
        revelar,
        bool(peca.get("aviso_antigo")),
    )


def capa(peca: dict):
    from PIL import Image, ImageDraw
    papel = peca.get("papel") or papel_do_dia()
    fundo, tinta = _cor_papel(papel)
    # A capa usa a cor invertida do video, uma palavra so.
    im = Image.new("RGB", (720, 1280), tinta)
    draw = ImageDraw.Draw(im)
    chines = any("\u4e00" <= char <= "\u9fff" for char in str(peca.get("palavra") or ""))
    fonte = _fonte(140, chines)
    if fonte is None:
        raise RuntimeError("sem_fonte")
    draw.text((40, 520), str(peca.get("palavra") or "REGRA")[:8], fill=fundo, font=fonte)
    return im


def render_loop(destino: Path, peca: dict) -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        return "sem ffmpeg, nao gerei video e nao posto"
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        primeiro = frame(peca, 0)
        ultimo = frame(peca, 11)
        if list(primeiro.getdata()) != list(ultimo.getdata()):
            return "loop quebrado, nao postei"
        frames = []
        for i in range(12):
            imagem = frame(peca, i)
            caminho = destino.parent / f"{destino.stem}-{i:02d}.png"
            imagem.save(caminho)
            frames.append(caminho)
        capa(peca).save(destino.parent / "capa.png")
    except Exception:
        return "sem fonte ou sem pillow, nao postei"
    cmd = [
        ff, "-y", "-framerate", "1", "-i", str(destino.parent / f"{destino.stem}-%02d.png"),
        "-f", "lavfi", "-i", "sine=frequency=740:duration=0.12,afade=t=out:st=0.06:d=0.06,apad=whole_dur=12",
        "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(destino),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=90)
    except Exception:
        return "ffmpeg falhou, nao postei"
    for caminho in frames:
        caminho.unlink(missing_ok=True)
    if not destino.exists() or destino.stat().st_size < 1000:
        return "video curto demais, nao postei"
    return ""
