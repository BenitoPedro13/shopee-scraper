import typer
from pathlib import Path
from rich.console import Console

from src.shopee_scraper.session import login_and_save_session
from src.shopee_scraper.search import search_products
from src.shopee_scraper.cdp.collector import (
    collect_pdp_once,
    collect_search_once,
    launch_chrome_for_login,
    collect_pdp_batch,
    collect_pdp_batch_concurrent,
)
from src.shopee_scraper.cdp.exporter import (
    export_pdp_from_jsonl,
    export_search_from_jsonl,
)

app = typer.Typer(help="Shopee Scraper CLI (MVP scaffolding)")
console = Console()


@app.command()
def login():
    """Abre navegador headful para login manual e salva a sessão (Playwright)."""
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
    launch: bool = typer.Option(True, "--launch/--no-launch", help="Lança o Chrome com porta de debug (usa USER_DATA_DIR)"),
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


@app.command("cdp-login")
def cdp_login(
    timeout_open_s: float = typer.Option(None, "--timeout", help="(Opcional) Fecha o Chrome após N segundos"),
):
    """Lança um Chrome real com perfil do USER_DATA_DIR para login manual (CDP)."""
    try:
        launch_chrome_for_login(timeout_open_s=timeout_open_s)
        console.print("[green]OK[/]: Chrome encerrado. Sessão ficou gravada no perfil.")
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")


@app.command("cdp-search")
def cdp_search(
    keyword: str = typer.Option(..., "--keyword", "-k", help="Palavra-chave da busca"),
    launch: bool = typer.Option(True, "--launch/--no-launch", help="Lança o Chrome com porta de debug"),
    timeout: float = typer.Option(20.0, "--timeout", help="Tempo de captura após navegação (s)"),
    auto_export: bool = typer.Option(True, "--export/--no-export", help="Exporta JSON/CSV após capturar"),
):
    """Captura APIs de busca via CDP e (opcional) exporta resultados normalizados."""
    try:
        jsonl = collect_search_once(keyword=keyword, launch=launch, timeout_s=timeout)
        console.print(f"[green]OK[/]: respostas capturadas em {jsonl}")
        if auto_export:
            json_out, csv_out, rows = export_search_from_jsonl(jsonl)
            console.print(
                f"[green]OK[/]: exportados {len(rows)} resultados de busca → {json_out}, {csv_out}"
            )
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")


@app.command("cdp-enrich-search")
def cdp_enrich_search(
    input_path: str = typer.Argument(None, help="Arquivo de export de busca (JSON ou CSV). Se omitido, pega o mais recente."),
    launch: bool = typer.Option(True, "--launch/--no-launch", help="Lança o Chrome com porta de debug (recomendado)"),
    timeout: float = typer.Option(8.0, "--per-timeout", help="Tempo de captura por PDP (s)"),
    pause: float = typer.Option(0.2, "--pause", help="Pausa entre PDPs no modo serial (s)"),
    fraction: float = typer.Option(0.25, "--fraction", min=0.0, max=1.0, help="Fraçao do total para rodar em paralelo (0..1). Ex.: 0.25 = 1/4"),
    concurrency: int = typer.Option(0, "--concurrency", help="Força um número fixo de abas (sobrepõe --fraction se > 0)"),
    stagger: float = typer.Option(1.0, "--stagger", help="Atraso entre abas no disparo de cada lote (s)"),
):
    """Enriquece uma exportação de busca com dados reais de PDP via CDP (batch)."""
    try:
        import glob
        import os
        import csv
        import json
        from pathlib import Path

        # Resolve input file
        if input_path is None:
            candidates = sorted(
                glob.glob("data/cdp_search_*_export.json") + glob.glob("data/cdp_search_*_export.csv"),
                key=os.path.getmtime,
                reverse=True,
            )
            if not candidates:
                raise FileNotFoundError("Nenhum export de busca encontrado (data/cdp_search_*_export.*)")
            input_path = candidates[0]
        in_path = Path(input_path)
        if not in_path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {in_path}")

        # Load search rows
        def load_rows(p: Path):
            if p.suffix.lower() == ".json":
                return json.loads(p.read_text(encoding="utf-8"))
            rows = []
            with p.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    rows.append(r)
            return rows

        search_rows = load_rows(in_path)
        urls = [r.get("url") for r in search_rows if r.get("url")]
        if not urls:
            raise ValueError("Nenhuma URL de produto encontrada no export de busca.")

        # Choose concurrency
        import math
        eff_conc = concurrency if concurrency and concurrency > 0 else max(1, math.ceil(len(urls) * max(0.0, min(1.0, fraction))))

        # Simple progress meter
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]CDP PDP Enrich"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("capture", total=len(urls))

            def _on_progress(event: str, info: dict):
                if event == "start":
                    progress.advance(task, 1)

            # Batch capture PDPs (concurrent if eff_conc > 1)
            if eff_conc > 1:
                batch_jsonl = collect_pdp_batch_concurrent(
                    urls=urls,
                    launch=launch,
                    timeout_s=timeout,
                    stagger_s=stagger,
                    concurrency=eff_conc,
                    on_progress=_on_progress,
                )
            else:
                batch_jsonl = collect_pdp_batch(
                    urls=urls,
                    launch=launch,
                    timeout_s=timeout,
                    pause_s=pause,
                    on_progress=_on_progress,
                )
        # Export normalized PDP rows
        json_out, csv_out, pdp_rows = export_pdp_from_jsonl(batch_jsonl)

        # Index PDP rows by (shop_id, item_id)
        by_key = {}
        for r in pdp_rows:
            sid = r.get("shop_id")
            iid = r.get("item_id")
            if sid is None or iid is None:
                continue
            key = (str(sid), str(iid))
            if key not in by_key:
                by_key[key] = r

        # Enrich search rows with PDP fields (prefixed pdp_)
        enriched = []
        for r in search_rows:
            sid = r.get("shop_id")
            iid = r.get("item_id")
            pdp = by_key.get((str(sid), str(iid)), {}) if sid and iid else {}
            merged = dict(r)
            for k, v in pdp.items():
                merged[f"pdp_{k}"] = v
            enriched.append(merged)

        # Write outputs next to input
        stem = in_path.stem  # cdp_search_<ts>_export
        out_json = in_path.parent / f"{stem}_enriched.json"
        out_csv = in_path.parent / f"{stem}_enriched.csv"

        # Reuse utils writers for stable output
        from src.shopee_scraper.utils import write_json, write_csv

        write_json(enriched, out_json)
        write_csv(enriched, out_csv)

        console.print(f"[green]OK[/]: enriquecidos {len(enriched)} itens. Arquivos → {out_json}, {out_csv}")

        # Per-URL logging summary
        matched = sum(1 for r in enriched if r.get("pdp_item_id") and r.get("pdp_shop_id"))
        total = len(enriched)
        console.print(f"Resumo: {matched}/{total} com PDP válido.")
        # List a concise per-URL line
        for idx, r in enumerate(enriched, start=1):
            title = r.get("title") or r.get("name") or "(sem título)"
            short = (title[:50] + "…") if len(title) > 50 else title
            ok = "OK" if r.get("pdp_item_id") else "-"
            price = r.get("pdp_price_min") or r.get("pdp_price_max") or r.get("price")
            rating = r.get("pdp_rating_star")
            url = r.get("url")
            console.print(f"{idx:>3} [{ok}] preço={price} rating={rating} → {short}")
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")

if __name__ == "__main__":
    app()
