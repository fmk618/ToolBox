from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .core.errors import ToolboxError
from .core.pipeline import convert
from .core.engines_graph import ENGINES, build_graph

app = typer.Typer(
    help="Toolbox — universal file format converter (PDF / Word / Markdown / ...)",
    no_args_is_help=True,
)
console = Console()


@app.command("convert")
def convert_cmd(
    input: Path = typer.Argument(..., exists=True, readable=True, help="Input file"),
    output: Path = typer.Option(..., "-o", "--output", help="Output file path"),
    to: str | None = typer.Option(
        None, "--to", help="Target format override (e.g. md, pdf, docx)"
    ),
):
    """Convert INPUT to OUTPUT, formats inferred from extensions."""
    try:
        used = convert(input, output, dst_fmt=to)
    except ToolboxError as e:
        console.print(f"[red]✗ {type(e).__name__}:[/red] {e}")
        raise typer.Exit(1)

    if not used:
        console.print(f"[yellow]·[/yellow] {input} → {output}  [dim](no conversion needed)[/dim]")
    else:
        chain = " → ".join(used)
        console.print(f"[green]✓[/green] {input} → {output}  [dim]via {chain}[/dim]")


@app.command("engines")
def engines_cmd():
    """List engines and their availability."""
    table = Table(title="Engines")
    table.add_column("Name", style="bold")
    table.add_column("Available")
    table.add_column("Edges")

    for e in ENGINES:
        avail = "[green]✓[/green]" if e.available else "[red]✗[/red]"
        edges = e.edges()
        preview = ", ".join(f"{a}→{b}" for a, b in edges[:5])
        if len(edges) > 5:
            preview += f" (+{len(edges) - 5} more)"
        table.add_row(e.name, avail, preview)

    console.print(table)


@app.command("routes")
def routes_cmd():
    """Show every direct conversion edge currently reachable."""
    graph = build_graph()
    if not graph:
        console.print("[red]No engines available.[/red]")
        return

    table = Table(title="Direct conversion edges (available engines only)")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Engine")
    for src in sorted(graph.keys()):
        for dst, engine in graph[src]:
            table.add_row(src, dst, engine.name)
    console.print(table)


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
):
    """Run the HTTP API server."""
    import uvicorn

    uvicorn.run("toolbox.api:api", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
