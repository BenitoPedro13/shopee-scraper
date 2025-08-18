import typer
from rich.console import Console

app = typer.Typer(help="Shopee Scraper CLI (MVP scaffolding)")
console = Console()


@app.command()
def login():
    """Fluxo de login (será implementado na próxima etapa)."""
    console.print("[yellow]TODO:[/] Implementar login headful e salvar sessão.", highlight=False)


@app.command()
def search(keyword: str = typer.Option(..., "--keyword", "-k", help="Palavra-chave para busca")):
    """Scraping da busca (será implementado na próxima etapa)."""
    console.print(f"[yellow]TODO:[/] Buscar por '{keyword}' e extrair resultados.")


if __name__ == "__main__":
    app()

