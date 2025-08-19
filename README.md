# Shopee Scraper (MVP)

Projeto de estudo para scraping de dados públicos da Shopee. Além do MVP com Playwright, adotamos a estratégia CDP (Chrome DevTools Protocol) para capturar, de um Chrome real, as respostas de APIs usadas pela página (ex.: PDP), reduzindo detecção por anti-bot.

## Requisitos
- Python 3.10+
- macOS/Linux/Windows

## Instalação
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install --upgrade pip
pip install -r requirements.txt
# Instalar navegador (Chromium) do Playwright dentro do workspace
PLAYWRIGHT_BROWSERS_PATH=.pw-browsers \
  .venv/bin/python -m playwright install chromium
```

## Configuração
Crie um `.env` baseado em `.env.example`:
```env
SHOPEE_DOMAIN=shopee.com.br
HEADLESS=false
STORAGE_STATE=storage_state.json
USER_DATA_DIR=.user-data
DATA_DIR=data
# Dê um nome de perfil para isolar contas (opcional)
PROFILE_NAME=conta_br_01
LOCALE=pt-BR
TIMEZONE=America/Sao_Paulo
REQUESTS_PER_MINUTE=60
MIN_DELAY=1.0
MAX_DELAY=2.5
PROXY_URL=
USE_PERSISTENT_CONTEXT_FOR_SEARCH=true
DISABLE_3PC_PHASEOUT=true
CDP_PORT=9222
CDP_FILTER_PATTERNS=
```

## Estratégia (CDP)
- Por que CDP: Shopee usa ML + SDK de segurança com fingerprint dinâmico e headers criptográficos. Em vez de injetar automação detectável, observamos passivamente o tráfego via CDP.
- Fluxo: descobrir URLs de produto (PDP) → abrir PDP no Chrome com porta de debug → capturar `/api/v4/pdp/get_pc` via CDP → exportar.
- Sessão real: usar `USER_DATA_DIR` e, se possível, proxy residencial alinhado à região.
  - Em CDP, se `PROXY_URL` estiver definido, o Chrome é lançado com `--proxy-server=...`.
  - Dica: muitos provedores chamam o endpoint de "HTTPS proxy"; no Chrome a flag usa `http://host:port` (mapeamos automaticamente `https://` → `http://`).
  - Observação: credenciais embutidas (`user:pass@host:port`) são removidas da flag; o Chrome solicitará usuário/senha via prompt (ou use allowlist de IP no provedor).
  - Coerência: o CDP alinha `Accept-Language` e `timezone` com as configs do `.env`.
  - Use `PROFILE_NAME` para isolar diretórios por conta: `.user-data/profiles/<PROFILE_NAME>`.

## Uso (CLI)
Comandos principais:
```bash
python cli.py --help
python cli.py login
python cli.py cdp-login  # login em Chrome real (perfil CDP)
python cli.py search --keyword "fones bluetooth"
# Captura via CDP (PDP):
# A) Lança Chrome com porta de debug por padrão (USER_DATA_DIR)
python cli.py cdp-pdp "https://shopee.com.br/algum-produto" --timeout 25
# B) Para anexar a um Chrome já aberto com --remote-debugging-port=9222, use --no-launch
python cli.py cdp-pdp "https://shopee.com.br/algum-produto" --no-launch --timeout 25
# Exportar dados normalizados a partir da captura CDP
python cli.py cdp-export  # usa o JSONL mais recente
python cli.py cdp-export data/cdp_pdp_1755508732.jsonl

# Captura via CDP (Busca/Listagem):
python cli.py cdp-search --keyword "brinquedo para cachorro" --timeout 25  # captura + exporta (lança Chrome por padrão)
python cli.py cdp-search --keyword "brinquedo para cachorro" --no-launch --no-export  # só captura, anexando a Chrome já aberto

# Enriquecer export de busca com dados reais de PDP (lote):
python cli.py cdp-enrich-search  --launch  # usa o export mais recente e roda PDP em lote
# Dica (proxies com prompt de login):
# 1) Abra uma sessão única autenticada no proxy: python cli.py cdp-login
# 2) Rode os lotes anexando à mesma instância: python cli.py cdp-enrich-search --no-launch
python cli.py cdp-enrich-search data/cdp_search_17555_export.json --launch --per-timeout 12 --pause 0.6
```
Notas:
- `search` serve para descoberta básica; a coleta robusta de dados usa CDP nas PDPs.
- Para consistência com o CDP, você pode usar `cdp-login` + `cdp-search` e pular o Playwright.
- Saída CDP: `data/cdp_pdp_<timestamp>.jsonl` (uma linha por resposta capturada com url/status/headers/body).
  - Para busca: `data/cdp_search_<timestamp>.jsonl` + exports `_export.json`/`_export.csv`.
  - Health-check: se nenhuma resposta CDP for capturada no tempo limite, o perfil é marcado como degradado em `data/session_status/<perfil>.json` e o comando falha.
  - Rate limiting: navegações via CDP são limitadas por `REQUESTS_PER_MINUTE`.
  - Reciclagem: se `PAGES_PER_SESSION` > 0 e `--launch` estiver ativo, lotes longos são divididos em sessões menores (Chrome relançado entre chunks) e os JSONLs são concatenados.

## Estrutura
```
.
├── cli.py
├── requirements.txt
├── .env.example
├── src/
│   └── shopee_scraper/
│       ├── __init__.py
│       ├── config.py
│       ├── session.py
│       ├── search.py
│       ├── utils.py
│       └── cdp/
│           ├── __init__.py
│           └── collector.py
├── data/
│   └── .gitkeep
└── docs/
    ├── ARCHITECTURE_PLAN.txt
    └── ANTIBOT_CAPTCHA_NOTE.txt
```

## Aviso
- Coletar somente dados públicos; respeitar robots.txt e ToS.
- Evitar PII; usar limites conservadores; manter 1 IP por sessão.

## Próximos Passos
- Exportador PDP: parsear JSONL do CDP para JSON/CSV normalizado.
- Captura CDP de busca/listagens: extrair PDPs das APIs de listagem.
- Batch PDP: processar lista de URLs com pacing humano e reciclagem de instâncias.
- Resiliência: retries/backoff, limites por perfil, detecção/pausa em bloqueios.
- Proxies/Perfis: 1 IP por perfil (resid./mobile), alinhado à região, sem troca no meio da sessão.

## Testes
- Rodar testes:
```bash
pytest -q
```
- Escopo inicial dos testes: utilitários de IO (JSON/CSV) e exportadores CDP (normalização de PDP e Busca). Testes evitam abrir navegador.
