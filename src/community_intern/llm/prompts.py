from __future__ import annotations

from typing import List


def compose_system_prompt(base_prompt: str, project_introduction: str) -> str:
    parts: List[str] = []
    if base_prompt.strip():
        parts.append(base_prompt.strip())
    if project_introduction.strip():
        parts.append(f"Project introduction:\n{project_introduction.strip()}")
    return "\n\n".join(parts).strip()
