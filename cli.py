import typer
from pathlib import Path
from rich.console import Console

from src.shopee_scraper.session import login_and_save_session
from src.shopee_scraper.search import search_products
from src.shopee_scraper.cdp.collector import collect_pdp_once
from src.shopee_scraper.cdp.exporter import export_pdp_from_jsonl

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


@app.command("cdp-pdp")
def cdp_pdp(
    url: str = typer.Argument(..., help="URL completa de uma PDP de produto da Shopee"),
    launch: bool = typer.Option(False, "--launch", help="Lança o Chrome com porta de debug (usa USER_DATA_DIR)"),
    timeout: float = typer.Option(20.0, "--timeout", help="Tempo de captura após a navegação (s)"),
):
    """Captura respostas de API de PDP via CDP e salva em JSONL (data/)."""
    try:
        out = collect_pdp_once(url=url, launch=launch, timeout_s=timeout)
        console.print(f"[green]OK[/]: respostas capturadas em {out}")
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")


@app.command("cdp-export")
def cdp_export(
    input_path: str = typer.Argument(None, help="Arquivo JSONL gerado pelo cdp-pdp (data/cdp_pdp_*.jsonl). Se omitido, usa o mais recente."),
):
    """Exporta JSON/CSV normalizado a partir de um JSONL de captura CDP de PDP."""
    try:
        if input_path is None:
            # find latest
            import glob, os

            files = sorted(glob.glob("data/cdp_pdp_*.jsonl"), key=os.path.getmtime, reverse=True)
            if not files:
                raise FileNotFoundError("Nenhum arquivo data/cdp_pdp_*.jsonl encontrado.")
            input_path = files[0]
        jpath = Path(input_path)
        if not jpath.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {jpath}")
        json_out, csv_out, rows = export_pdp_from_jsonl(jpath)
        console.print(f"[green]OK[/]: exportados {len(rows)} registros → {json_out}, {csv_out}")
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")


if __name__ == "__main__":
    app()
