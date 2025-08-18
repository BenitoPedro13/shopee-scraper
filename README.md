# Shopee Scraper (MVP)

Projeto de estudo para scraping de dados públicos da Shopee com Python + Playwright, evoluindo de um MVP simples até uma solução mais robusta (proxies, múltiplos perfis, CAPTCHA/OTP, anti-detect).

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
LOCALE=pt-BR
TIMEZONE=America/Sao_Paulo
REQUESTS_PER_MINUTE=60
MIN_DELAY=1.0
MAX_DELAY=2.5
PROXY_URL=
USE_PERSISTENT_CONTEXT_FOR_SEARCH=true
DISABLE_3PC_PHASEOUT=true
```

## Uso (MVP)
Por enquanto apenas a estrutura/CLI básica:
```bash
python cli.py --help
python cli.py login
python cli.py search --keyword "fones bluetooth"
# Captura via CDP (PDP):
# A) Lançar Chrome com porta de debug e perfil do USER_DATA_DIR
python cli.py cdp-pdp "https://shopee.com.br/algum-produto" --launch --timeout 25
# B) Anexar a um Chrome já aberto com --remote-debugging-port=9222
# (defina CDP_PORT se usar outra porta)
python cli.py cdp-pdp "https://shopee.com.br/algum-produto" --timeout 25
```
Obs.: As rotinas de login e scraping serão implementadas nas próximas etapas.

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
│       └── utils.py
├── data/
│   └── .gitkeep
└── docs/
    └── ARCHITECTURE_PLAN.txt
```

## Aviso
- Coletar somente dados públicos; respeitar robots.txt e ToS.
- Evitar PII; usar limites conservadores; manter 1 IP por sessão.

## Próximos Passos
- Implementar fluxo de login (headful) e persistência de sessão.
- Implementar scraping de busca e export (JSON/CSV).
- Adicionar resiliência (retries/backoff, throttling, detecção de bloqueios).
- Evoluir para proxies, múltiplas sessões e anti-detect.
