"""Acha falha recente e abre PR de melhoria.

Nao publica video. Nao envia proposta. Nao faz merge. Nao grava cookie nem token.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

REPO = os.environ.get("ORBE_GITHUB_REPO", "arcana-devTools/orbe")
REPOS = ("arcana-devTools/orbe", "arcana-devTools/orbe-uic")
CAMINHO_OK = re.compile(r"^[A-Za-z0-9_./-]+$")


def _pat() -> str:
    pat = os.environ.get("ORBE_GITHUB_PAT", "").strip()
    if pat:
        return pat
    try:
        from secrets_vault import VAULT

        d = VAULT.get("github") or {}
        return str((d.get("extra") or {}).get("pat", "")).strip()
    except Exception:
        return ""


def _hdr(pat: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orbe-melhorias",
    }


def seguro(texto: str) -> bool:
    """Recusa valor de segredo. O nome da regra, sozinho, pode ficar no codigo."""
    bruto = texto or ""
    if re.search(r"github_pat_[A-Za-z0-9_]{12,}", bruto):
        return False
    if re.search(r"ghp_[A-Za-z0-9]{12,}", bruto):
        return False
    if re.search(r"(?i)(cookie|token|password|senha)\s*=\s*\S{12,}", bruto):
        return False
    if re.search(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}", bruto):
        return False
    return True


def caminho_seguro(path: str) -> bool:
    if not path or path.startswith("/") or ".." in path.split("/"):
        return False
    return bool(CAMINHO_OK.match(path))


def falhas(pat: str | None = None, limite: int = 5) -> list[dict[str, str]]:
    """Ultimas falhas dos Actions. Sem log e sem segredo."""
    pat = pat or _pat()
    if not pat:
        return []
    h = _hdr(pat)
    saida = []
    for repo in REPOS:
        r = httpx.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            headers=h,
            params={"status": "failure", "per_page": limite},
            timeout=30,
        )
        if r.status_code != 200:
            saida.append({"repo": repo, "nome": "leitura", "quando": "", "motivo": f"http {r.status_code}"})
            continue
        for run in (r.json().get("workflow_runs") or [])[:limite]:
            saida.append({
                "repo": repo,
                "nome": str(run.get("name") or ""),
                "quando": str(run.get("created_at") or ""),
                "motivo": str(run.get("conclusion") or ""),
            })
    return saida


def plano(falhas_vistas: list[dict[str, str]] | None = None) -> list[str]:
    """O que ainda cabe melhorar, sem disparar job e sem gastar conta."""
    itens = [
        "TikTok: o servidor nao envia arquivo. A leitura fica; o envio nao.",
        "Bilibili: preupload_406 nao repete no mesmo dia. A falha precisa de motivo legivel.",
        "UICLAP: publicar depende do Orbe. Com o servico suspenso, o job falha.",
        "Workana: perfil em revisao. Nao enviar proposta enquanto a revisao durar.",
    ]
    for falha in falhas_vistas or []:
        nome = falha.get("nome") or "action"
        if nome == "leitura":
            continue
        linha = f"{falha.get('repo')} {nome} falhou em {falha.get('quando', '')[:16]}."
        if linha not in itens:
            itens.append(linha)
    return itens


def abrir_pr(
    titulo: str,
    corpo: str,
    arquivos: dict[str, str],
    branch: str,
    repo: str = REPO,
    pat: str | None = None,
) -> dict[str, Any]:
    """Abre um PR. Recusa segredo no titulo, no texto e nos arquivos."""
    pat = pat or _pat()
    if not pat:
        return {"ok": False, "motivo": "sem PAT"}
    if not seguro(titulo) or not seguro(corpo) or not seguro(branch):
        return {"ok": False, "motivo": "texto com segredo"}
    if not arquivos:
        return {"ok": False, "motivo": "sem arquivo"}
    for path, conteudo in arquivos.items():
        if not caminho_seguro(path) or not seguro(conteudo):
            return {"ok": False, "motivo": f"arquivo recusado: {path}"}
    h = _hdr(pat)
    base = f"https://api.github.com/repos/{repo}"
    ref = httpx.get(f"{base}/git/ref/heads/main", headers=h, timeout=30)
    if ref.status_code != 200:
        return {"ok": False, "motivo": f"main http {ref.status_code}"}
    sha = ref.json()["object"]["sha"]
    tree = []
    for path, conteudo in arquivos.items():
        blob = httpx.post(f"{base}/git/blobs", headers=h, json={"content": conteudo, "encoding": "utf-8"}, timeout=30)
        if blob.status_code not in (200, 201):
            return {"ok": False, "motivo": f"blob http {blob.status_code}"}
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob.json()["sha"]})
    arvore = httpx.post(f"{base}/git/trees", headers=h, json={"base_tree": sha, "tree": tree}, timeout=30)
    if arvore.status_code not in (200, 201):
        return {"ok": False, "motivo": f"tree http {arvore.status_code}"}
    commit = httpx.post(
        f"{base}/git/commits",
        headers=h,
        json={"message": titulo, "tree": arvore.json()["sha"], "parents": [sha]},
        timeout=30,
    )
    if commit.status_code not in (200, 201):
        return {"ok": False, "motivo": f"commit http {commit.status_code}"}
    novo = commit.json()["sha"]
    ref_novo = httpx.post(f"{base}/git/refs", headers=h, json={"ref": f"refs/heads/{branch}", "sha": novo}, timeout=30)
    if ref_novo.status_code not in (200, 201):
        return {"ok": False, "motivo": f"branch http {ref_novo.status_code}"}
    pr = httpx.post(
        f"{base}/pulls",
        headers=h,
        json={"title": titulo[:70], "head": branch, "base": "main", "body": corpo[:4000]},
        timeout=30,
    )
    if pr.status_code not in (200, 201):
        return {"ok": False, "motivo": f"pr http {pr.status_code}"}
    return {"ok": True, "url": pr.json().get("html_url"), "numero": pr.json().get("number")}


def relatorio() -> str:
    vistas = falhas()
    linhas = ["[melhorias] sem publicar, sem proposta, sem merge."]
    linhas.extend(f"- {item}" for item in plano(vistas))
    return "\n".join(linhas)


def main() -> None:
    print(relatorio())


if __name__ == "__main__":
    main()
