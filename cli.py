import os
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
    collect_search_paged,
    collect_search_all,
)
from src.shopee_scraper.cdp.exporter import (
    export_pdp_from_jsonl,
    export_search_from_jsonl,
)
from src.shopee_scraper.config import settings
from src.shopee_scraper.envcheck import validate_environment, suggest_region_for_domain
from src.shopee_scraper.scheduler import add_task as queue_add_task, load_tasks as queue_load_tasks, run_once as queue_run_once

app = typer.Typer(help="Shopee Scraper CLI (MVP scaffolding)")
profiles_app = typer.Typer(help="Gerenciar perfis de navegador (CDP)")
app.add_typer(profiles_app, name="profiles")
metrics_app = typer.Typer(help="Relatórios a partir de data/logs/events.jsonl")
app.add_typer(metrics_app, name="metrics")
queue_app = typer.Typer(help="Fila local de tarefas (scheduler simples)")
app.add_typer(queue_app, name="queue")
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
    soft_circuit: bool = typer.Option(False, "--soft-circuit/--hard-circuit", help="Não aborta em bloqueio; apenas loga e segue (soft)"),
    circuit_inactivity: float = typer.Option(None, "--circuit-inactivity", help="Janela de inatividade (s) para sinalizar bloqueio"),
):
    """Captura respostas de API de PDP via CDP e salva em JSONL (data/)."""
    try:
        # Optional overrides for circuit behaviour
        if soft_circuit:
            from src.shopee_scraper.config import settings as _s
            _s.cdp_circuit_enabled = False
        if circuit_inactivity is not None:
            from src.shopee_scraper.config import settings as _s
            _s.cdp_inactivity_s = float(circuit_inactivity)
        out = collect_pdp_once(url=url, launch=launch, timeout_s=timeout)
        console.print(f"[green]OK[/]: respostas capturadas em {out}")
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")


# ------------------------------ Queue CLI ------------------------------

@queue_app.command("add-search")
def queue_add_search(
    keyword: str = typer.Option(..., "--keyword", "-k"),
    pages: int = typer.Option(1, "--pages", "-p"),
    start_page: int = typer.Option(0, "--start-page"),
    all_pages: bool = typer.Option(False, "--all-pages/--no-all-pages"),
    timeout: float = typer.Option(20.0, "--timeout"),
    launch: bool = typer.Option(True, "--launch/--no-launch"),
    auto_export: bool = typer.Option(True, "--export/--no-export"),
):
    kind = "cdp_search_all" if all_pages else "cdp_search"
    params = dict(keyword=keyword, pages=pages, start_page=start_page, timeout_s=timeout, launch=launch, auto_export=auto_export)
    t = queue_add_task(kind, params)
    console.print(f"[green]OK[/]: task {t.kind} adicionada id={t.id}")


@queue_app.command("add-enrich")
def queue_add_enrich(
    input_path: str = typer.Option(None, "--input"),
    launch: bool = typer.Option(True, "--launch/--no-launch"),
    timeout: float = typer.Option(8.0, "--per-timeout"),
    pause: float = typer.Option(0.5, "--pause"),
    concurrency: int = typer.Option(0, "--concurrency"),
    stagger: float = typer.Option(1.0, "--stagger"),
):
    params = dict(input_path=input_path, launch=launch, timeout_s=timeout, pause_s=pause, concurrency=concurrency, stagger_s=stagger)
    t = queue_add_task("cdp_enrich", params)
    console.print(f"[green]OK[/]: task {t.kind} adicionada id={t.id}")


@queue_app.command("list")
def queue_list():
    tasks = queue_load_tasks()
    if not tasks:
        console.print("Nenhuma tarefa na fila.")
        return
    from rich.table import Table
    tbl = Table(title="Queue Tasks")
    for col in ("id","kind","status","attempts","max","created","updated"):
        tbl.add_column(col)
    for t in tasks:
        tbl.add_row(t.id, t.kind, t.status, str(t.attempts), str(t.max_attempts), time_fmt(t.created_ts), time_fmt(t.updated_ts))
    console.print(tbl)


def time_fmt(ts: int) -> str:
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


@queue_app.command("run")
def queue_run(
    max_tasks: int = typer.Option(0, "--max-tasks", help="Limita quantas tarefas executar nesta rodada (0 = todas)"),
):
    tried = queue_run_once(max_tasks=max_tasks)
    console.print(f"[green]OK[/]: processadas {tried} tarefas (pending → running → done/requeue)")


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


# ------------------------------ Profiles CLI ------------------------------

def _profiles_base_dir() -> Path:
    # If settings.user_data_dir already points to .../profiles/<name>, go up to 'profiles'
    p = Path(settings.user_data_dir)
    try:
        parts = list(p.parts)
        if "profiles" in parts:
            idx = parts.index("profiles")
            return Path(*parts[: idx + 1])
    except Exception:
        pass
    return p / "profiles"


@profiles_app.command("list")
def profiles_list():
    """Lista perfis disponíveis e o perfil ativo (via PROFILE_NAME)."""
    base = _profiles_base_dir()
    base.mkdir(parents=True, exist_ok=True)
    items = sorted([d.name for d in base.iterdir() if d.is_dir()])
    active = settings.profile_name or "(não definido)"
    console.print(f"Base de perfis: {base}")
    console.print(f"Perfil ativo (PROFILE_NAME): {active}")
    if not items:
        console.print("Nenhum perfil encontrado. Crie um com: python cli.py profiles create <nome>")
        return
    for name in items:
        marker = "*" if settings.profile_name and name == settings.profile_name else "-"
        console.print(f" {marker} {name}")


@profiles_app.command("create")
def profiles_create(name: str = typer.Argument(..., help="Nome do perfil a criar")):
    """Cria o diretório do perfil (.user-data/profiles/<nome>)."""
    base = _profiles_base_dir()
    target = base / name
    target.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]OK[/]: perfil criado em {target}")
    console.print("Dica: ative com 'python cli.py profiles use " + name + "'")


def _update_env_var(key: str, value: str, env_path: Path) -> None:
    lines = []
    found = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#"):
                lines.append(line)
                continue
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@profiles_app.command("use")
def profiles_use(name: str = typer.Argument(..., help="Nome do perfil a usar")):
    """Define PROFILE_NAME no .env para usar o perfil informado (cria se não existir)."""
    base = _profiles_base_dir()
    target = base / name
    target.mkdir(parents=True, exist_ok=True)
    env_path = Path(".env")
    _update_env_var("PROFILE_NAME", name, env_path)
    console.print(f"[green]OK[/]: PROFILE_NAME={name} definido em {env_path}")
    console.print(f"Diretório do perfil: {target}")
    console.print("Faça login com: python cli.py cdp-login")


@app.command("env-validate")
def env_validate():
    """Valida domínio/proxy/perfil/locale/timezone e sugere correções."""
    issues = validate_environment()
    if not issues:
        console.print("[green]OK[/]: Ambiente válido.")
        return
    console.print("[yellow]Avisos/Erros de ambiente detectados:")
    for lvl, msg in issues:
        if lvl == "error":
            console.print(f"[red]ERRO[/]: {msg}")
        else:
            console.print(f"[yellow]WARN[/]: {msg}")
    # Sugerir região p/ domínio
    suggestion = suggest_region_for_domain(settings.shopee_domain)
    if suggestion:
        console.print(
            f"Sugestão: para {settings.shopee_domain}, use LOCALE={suggestion['locale']} e TIMEZONE={suggestion['timezone']}"
        )


# ------------------------------ Metrics CLI ------------------------------

@metrics_app.command("summary")
def metrics_summary(
    path: str = typer.Option("data/logs/events.jsonl", "--path", help="Arquivo JSONL de eventos (loguru serialize)"),
    hours: int = typer.Option(0, "--hours", help="Janela em horas (0 = tudo)"),
    profile: str = typer.Option(None, "--profile", help="Filtrar por PROFILE_NAME"),
    proxy: str = typer.Option(None, "--proxy", help="Filtrar por PROXY_URL"),
):
    """Mostra taxa de sucesso, latência e bloqueios por perfil/proxy."""
    from src.shopee_scraper.metrics import run_report

    try:
        run_report(Path(path), hours=hours, profile=profile, proxy=proxy)
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")


@metrics_app.command("export")
def metrics_export(
    path: str = typer.Option("data/logs/events.jsonl", "--path", help="Arquivo JSONL de eventos (loguru serialize)"),
    hours: int = typer.Option(0, "--hours", help="Janela em horas (0 = tudo)"),
    profile: str = typer.Option(None, "--profile", help="Filtrar por PROFILE_NAME"),
    proxy: str = typer.Option(None, "--proxy", help="Filtrar por PROXY_URL"),
    out_csv: str = typer.Option("data/metrics/summary.csv", "--out-csv", help="Caminho do CSV de saída"),
    out_json: str = typer.Option("data/metrics/summary.json", "--out-json", help="Caminho do JSON de saída"),
):
    """Exporta agregações para CSV/JSON (para gráficos/notebooks)."""
    from src.shopee_scraper.metrics import export_metrics

    try:
        csv_path, json_path = export_metrics(
            Path(path), hours=hours, profile=profile, proxy=proxy, out_csv=Path(out_csv), out_json=Path(out_json)
        )
        console.print(f"[green]OK[/]: métricas exportadas → {csv_path}, {json_path}")
    except Exception as e:
        console.print(f"[red]Erro[/]: {e}")


@app.command("cdp-search")
def cdp_search(
    keyword: str = typer.Option(..., "--keyword", "-k", help="Palavra-chave da busca"),
    launch: bool = typer.Option(True, "--launch/--no-launch", help="Lança o Chrome com porta de debug"),
    timeout: float = typer.Option(20.0, "--timeout", help="Tempo de captura por página após navegação (s)"),
    pages: int = typer.Option(1, "--pages", "-p", help="Quantidade de páginas a capturar (via parâmetro page)"),
    start_page: int = typer.Option(0, "--start-page", help="Página inicial (0 = primeira)"),
    all_pages: bool = typer.Option(False, "--all-pages/--no-all-pages", help="Paginar até o fim (para quando não houver novas respostas)"),
    max_pages: int = typer.Option(100, "--max-pages", help="Limite superior de páginas no modo --all-pages"),
    soft_circuit: bool = typer.Option(False, "--soft-circuit/--hard-circuit", help="Não aborta em bloqueio; apenas loga e segue (soft)"),
    circuit_inactivity: float = typer.Option(None, "--circuit-inactivity", help="Janela de inatividade (s) para sinalizar bloqueio"),
    auto_export: bool = typer.Option(True, "--export/--no-export", help="Exporta JSON/CSV após capturar"),
):
    """Captura APIs de busca via CDP e (opcional) exporta resultados normalizados."""
    try:
        # Optional overrides for circuit behaviour
        if soft_circuit:
            from src.shopee_scraper.config import settings as _s
            _s.cdp_circuit_enabled = False
        if circuit_inactivity is not None:
            from src.shopee_scraper.config import settings as _s
            _s.cdp_inactivity_s = float(circuit_inactivity)

        if all_pages:
            jsonl = collect_search_all(
                keyword=keyword,
                launch=launch,
                timeout_s=timeout,
                start_page=start_page,
                max_pages=max_pages,
                pause_s=0.5,
            )
        elif pages and pages > 1:
            jsonl = collect_search_paged(
                keyword=keyword,
                pages=pages,
                start_page=start_page,
                launch=launch,
                timeout_s=timeout,
                pause_s=0.5,
            )
        else:
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
    soft_circuit: bool = typer.Option(False, "--soft-circuit/--hard-circuit", help="Não aborta em bloqueio; apenas loga e segue (soft)"),
    circuit_inactivity: float = typer.Option(None, "--circuit-inactivity", help="Janela de inatividade (s) para sinalizar bloqueio"),
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

        # Optional overrides for circuit behaviour
        if soft_circuit:
            from src.shopee_scraper.config import settings as _s
            _s.cdp_circuit_enabled = False
        if circuit_inactivity is not None:
            from src.shopee_scraper.config import settings as _s
            _s.cdp_inactivity_s = float(circuit_inactivity)

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
