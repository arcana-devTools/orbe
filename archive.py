"""Arquiva cada tarefa concluída na pasta escolhida pelo usuário (.md + .json)."""
from __future__ import annotations

import time
from pathlib import Path

from models import Task


def archive_task(task: Task, results_dir: str) -> str:
    """Escreve <ts>-<id>.md e .json na pasta; devolve o caminho do .md."""
    d = Path(results_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = d / f"{ts}-{task.id}"

    lines = [
        f"# Tarefa arquivada — {ts}",
        "",
        f"**Objetivo:** {task.goal}",
        f"**Estado:** {task.state.value}",
        "",
        "## Resultados por conta",
        "",
    ]
    for r in task.results:
        lines += [
            f"### {r.platform} — {'OK' if r.ok else 'FALHOU'}",
            f"- prompt: {r.prompt}",
            f"- resposta: {r.answer if r.ok else r.error}",
            "",
        ]
    lines += ["## Síntese (nossa IA)", "", task.synthesis or "(sem síntese)", ""]
    base.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    base.with_suffix(".json").write_text(task.model_dump_json(indent=2), encoding="utf-8")
    return str(base.with_suffix(".md"))
