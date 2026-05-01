from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from harumi.config import (
    CONFIG_SCHEMA,
    _get_value,
    _invalidate_config_cache,
    _load_config_file,
    get_config_file_path,
    value_source,
)

_HEADER = """\
# Harumi configuration
# Use `harumi config set KEY VALUE` to change settings.
# Environment variables (HARUMI_*) take precedence over this file.
"""


def _toml_line(key: str, value: object) -> str:
    if isinstance(value, bool):
        return f"{key} = {'true' if value else 'false'}"
    if isinstance(value, int):
        return f"{key} = {value}"
    return f'{key} = "{value}"'


def _write_config_file(data: dict) -> None:
    path = get_config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_HEADER]
    for key, (_, _, _, desc) in CONFIG_SCHEMA.items():
        lines.append(f"# {desc}")
        lines.append(_toml_line(key, data.get(key, CONFIG_SCHEMA[key][2])))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    _invalidate_config_cache()


def _ensure_config_file() -> Path:
    path = get_config_file_path()
    if not path.exists():
        defaults = {key: schema[2] for key, schema in CONFIG_SCHEMA.items()}
        _write_config_file(defaults)
    return path


def config_get_command(key: str | None) -> int:
    _ensure_config_file()
    console = Console()

    if key is not None:
        key = key.strip()
        if key not in CONFIG_SCHEMA:
            console.print(f"[red]Unknown key:[/red] {key}")
            console.print(f"Valid keys: {', '.join(CONFIG_SCHEMA)}")
            return 2
        env_var, _, _, desc = CONFIG_SCHEMA[key]
        val = _get_value(key)
        src = value_source(key)
        console.print(f"[dim]{key}[/dim] = [bold]{val}[/bold]  [dim]({src})[/dim]")
        console.print(f"[dim]env var: {env_var}  —  {desc}[/dim]")
        return 0

    console.print(Rule("Config", style="bold"))
    t = Table(show_header=True, box=None, padding=(0, 2, 0, 0), header_style="dim")
    t.add_column("Key")
    t.add_column("Value")
    t.add_column("Source", style="dim")
    t.add_column("Env var", style="dim")

    for k, (env_var, _, _, _) in CONFIG_SCHEMA.items():
        val = _get_value(k)
        src = value_source(k)
        src_text = Text(src, style="green" if src == "config" else ("yellow" if src == "env" else "dim"))
        t.add_row(k, str(val), src_text, env_var)

    console.print(t)
    console.print(f"\n[dim]Config file: {get_config_file_path()}[/dim]")
    return 0


def config_set_command(key: str, value: str) -> int:
    key = key.strip()
    console = Console()

    if key not in CONFIG_SCHEMA:
        console.print(f"[red]Unknown key:[/red] {key}")
        console.print(f"Valid keys: {', '.join(CONFIG_SCHEMA)}")
        return 2

    _, typ, _, desc = CONFIG_SCHEMA[key]

    try:
        if typ is bool:
            parsed: object = value.strip().lower() not in {"0", "false", "no", "off"}
        elif typ is int:
            parsed = int(value.strip())
        else:
            parsed = value.strip()
    except ValueError:
        console.print(f"[red]Invalid value for {key}:[/red] expected {typ.__name__}")
        return 2

    _ensure_config_file()
    current = dict(_load_config_file())
    _invalidate_config_cache()
    current[key] = parsed
    _write_config_file(current)
    _invalidate_config_cache()

    console.print(f"[green]Set[/green] [bold]{key}[/bold] = {parsed}")
    return 0
