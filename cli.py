import typer
from rich.console import Console

from src.shopee_scraper.session import login_and_save_session
from src.shopee_scraper.search import search_products

app = typer.Typer(help="Shopee Scraper CLI (MVP scaffolding)")
console = Console()


@app.command()
def login():
    """Abre navegador headful para login manual e salva a sessão."""
    login_and_save_session()


@app.command()
def search(
    keyword: str = typer.Option(..., "--keyword", "-k", help="Palavra-chave para busca"),
    limit: int = typer.Option(50, "--limit", "-l", help="Quantidade máxima de itens"),
):
    """Executa scraping de busca autenticado e salva JSON/CSV em data/."""
    rows = search_products(keyword=keyword, limit=limit)
    console.print(f"[green]OK[/]: coletados {len(rows)} itens para '{keyword}'.")


if __name__ == "__main__":
    app()
