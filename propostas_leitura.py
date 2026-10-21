"""Leitura das propostas. Nao envia, nao cancela e nao escreve proposta nova."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
SESSAO_99 = Path("data/99_sessao.txt")
SESSAO_WORKANA = Path("data/workana_sessao.txt")
ESTADO_WORKANA = Path("data/workana_estado.json")


def _ler(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _limpo(trecho: str) -> str:
    texto = html.unescape(re.sub(r"<[^>]+>", " ", trecho or ""))
    return re.sub(r"\s+", " ", texto).strip()


def ler_99(pagina: str) -> list[dict]:
    """Uma proposta por card. Status sai do bloco, nao do menu."""
    if "Nenhuma proposta foi encontrada" in pagina:
        return []
    itens = []
    for bloco in re.findall(r'(<li class="[^"]*result-item[\s\S]*?)(?=<li class="[^"]*result-item|$)', pagina):
        titulo = re.search(r'href="/project/[^"]+"[^>]*>\s*([^<]+)', bloco)
        if not titulo:
            continue
        nome = _limpo(titulo.group(1))
        if not nome or nome.lower().startswith("buscar"):
            continue
        enviada = re.search(r"Enviada:\s*([0-9/]+)", bloco)
        oferta = re.search(r"Oferta:\s*(R\$\s*[0-9.,]+)", bloco)
        status = "aberta"
        baixo = bloco.lower()
        if "aceita" in baixo and "aguardando" not in baixo:
            status = "aceita"
        elif "rejeitada" in baixo:
            status = "rejeitada"
        elif "aguardando resposta" in baixo or "enviada:" in baixo:
            status = "aguardando resposta"
        itens.append({
            "titulo": nome[:90],
            "status": status,
            "enviada": enviada.group(1) if enviada else "",
            "oferta": _limpo(oferta.group(1)) if oferta else "",
        })
    if itens:
        return itens
    # a lista atual nao usa result-item; o titulo fica no link do projeto
    for href, bruto in re.findall(r'href="(/project/[^"]+)"[^>]*>\s*([^<]+)', pagina):
        nome = _limpo(bruto)
        if not nome or "buscar" in nome.lower():
            continue
        ini = pagina.find(href)
        bloco = pagina[max(0, ini - 400): ini + 900]
        enviada = re.search(r"Enviada:\s*([0-9/]+)", bloco)
        oferta = re.search(r"Oferta:\s*(R\$\s*[0-9.,]+)", bloco)
        status = "aguardando resposta" if enviada else "aberta"
        if re.search(r">\s*Aceita\b", bloco):
            status = "aceita"
        itens.append({
            "titulo": nome[:90],
            "status": status,
            "enviada": enviada.group(1) if enviada else "",
            "oferta": _limpo(oferta.group(1)) if oferta else "",
        })
    return itens


def ler_workana(corpo: str) -> dict:
    try:
        doc = json.loads(corpo or "{}")
    except Exception:
        return {"ok": False}
    notas = doc.get("notifications") or {}
    fios = doc.get("threads") or {}
    return {
        "ok": True,
        "notificacoes": int(notas.get("count") or 0),
        "conversas": int(fios.get("count") or 0),
    }


def _jar(cookie: str) -> httpx.Cookies:
    jar = httpx.Cookies()
    for par in cookie.split(";"):
        if "=" in par:
            nome, valor = par.split("=", 1)
            jar.set(nome.strip(), valor.strip())
    return jar


def consultar() -> str:
    partes = []
    cookie99 = _ler(SESSAO_99)
    if not cookie99:
        partes.append("99freelas sem sessao")
    else:
        try:
            r = httpx.get(
                "https://www.99freelas.com.br/my-proposals?limit=50",
                cookies=_jar(cookie99),
                headers={"User-Agent": UA, "Accept-Language": "pt-BR"},
                timeout=30,
                follow_redirects=True,
            )
            if "/logout" not in r.text:
                partes.append("99freelas sessao caiu")
            else:
                itens = ler_99(r.text)
                aceitas = [v for v in itens if v["status"] == "aceita"]
                if not itens:
                    partes.append("99freelas 0 propostas, 0 aceitas")
                else:
                    resumo = "; ".join(
                        f"{v['titulo']} {v['status']}"
                        + (f" desde {v['enviada']}" if v["enviada"] else "")
                        for v in itens[:5]
                    )
                    partes.append(f"99freelas {len(itens)} propostas, {len(aceitas)} aceitas. {resumo}")
        except Exception as exc:
            partes.append(f"99freelas leitura falhou {type(exc).__name__}")

    cookie_w = _ler(SESSAO_WORKANA)
    revisao = ""
    try:
        est = json.loads(ESTADO_WORKANA.read_text(encoding="utf-8"))
        if est.get("em_revisao"):
            revisao = ", perfil em revisao"
    except Exception:
        pass
    if not cookie_w:
        partes.append("workana sem sessao" + revisao)
    else:
        try:
            r = httpx.get(
                "https://www.workana.com/notifications",
                headers={
                    "Cookie": cookie_w,
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=25,
            )
            doc = ler_workana(r.text)
            if not doc.get("ok"):
                partes.append("workana leitura falhou" + revisao)
            else:
                partes.append(
                    f"workana {doc['conversas']} conversas, {doc['notificacoes']} notificacoes"
                    + revisao
                )
        except Exception as exc:
            partes.append(f"workana leitura falhou {type(exc).__name__}" + revisao)
    return "[propostas] " + ". ".join(partes) + "."
