# Shopee Scraper — Requisitos & Status (foco: proteção de contas)

Última atualização: 2025-08-19

Este documento acompanha o progresso do projeto com prioridade máxima em proteger contas durante o desenvolvimento (minimizar bans e degradação de sessão).

---
ADENDO DE ESCALA (2025-08) — Estado atual, limitadores e como escalar

Estado Atual (síntese)
- CDP estável para PDP e Busca, com filtros padrão e export normalizado (JSON/CSV), dedup por `(shop_id,item_id)`.
- Concurrency via abas com reciclagem por `PAGES_PER_SESSION` e cooldown aleatório curto.
- Disjuntor (captcha/login/inatividade/403–429) + backoff (tenacity) reduzem danos e marcam sessão como degradada.
- Fila local baseada em arquivos funciona bem em 1 host, porém não coordena recursos entre múltiplos processos/hosts.

Limitadores Atuais (por que seu setup atual não escala)
- Único IP/perfil e um único host: throughput limitado e maior risco de detecção.
- Sem rate limiting global e locks: ao adicionar workers, estoura orçamento por IP e perfis podem ser usados em paralelo por engano.
- Porta CDP única (fixa): impede múltiplas instâncias de Chrome no mesmo host sem colisões.
- Persistência somente em arquivos: dificulta dedup cross-workers e consultas/entrega em tempo real.

Prioridade Atual — Proteger Contas e Escalar com Segurança
- Distribuir tarefas entre múltiplos perfis/IPs (sticky), com limites por perfil e por proxy.
- Eliminar colisões de porta/perfil ao rodar vários Chromes no mesmo host.
- Garantir idempotência em reprocessos (upsert por `(shop_id,item_id)`), sem duplicidade.

Backlog Priorizado — Itens novos p/ escala (complementares ao que já consta abaixo)
- Registro de perfis & proxies (`profiles.yaml`) com `profile_name`, `proxy_url`, `locale`, `timezone`, `rps_limit`, `cdp_port_range`.
- Alocador de porta CDP (`CDP_PORT_RANGE`) + lock por `user-data-dir` para impedir corrida de perfis.
- Fila distribuída (Redis + RQ/Celery) e comando `worker` com roteamento por perfil/região.
- Rate limiting global por `profile_name` e `proxy_url` (token bucket Redis) + locks distribuídos.
- Persistência em SQLite/Postgres com upsert por `(shop_id,item_id)` e índices; exporters gravam também no DB.
- Logs centralizados + métricas por perfil/proxy (sucesso, duração, bans/hora) e painel simples.
- Containerização (Chrome estável + deps) com entrypoints `worker`/`queue` e parametrização por perfil.

Como Atingir (guia de implementação)
1) Profiles & Proxies
   - Criar `docs/profiles.example.yaml` e `data/profiles.yaml` (gitignored) com parâmetros por perfil.
   - `src/shopee_scraper/profiles.py`: loader + validação; CLI para listar/validar.
2) Chrome/CDP
   - `CDP_PORT_RANGE=9300-9400` no `.env`; alocar porta livre por worker.
   - Lockfile por `user-data-dir` para impedir uso simultâneo do mesmo perfil.
3) Empacote
   - Dockerfile com Chrome estável e fonts; entrypoints `cli.py worker`, `cli.py queue`.
4) Fila + Workers
   - Adotar Redis e RQ/Celery; adaptar `scheduler.py` mantendo fallback local.
   - `cli.py workers start --profiles br_01 br_02` para spawn local.
5) Rate limiting & Locks
   - `limits.py` com token bucket Redis e `with_profile_lock(profile)`; usar em todos os caminhos CDP.
6) Persistência
   - `db.py` (SQLite primeiro) e `exporter` salvando também no DB (upsert por `(shop_id,item_id)`).

Métricas de Sucesso
- 2+ workers por host, 2+ hosts, sem violar RPS por perfil/IP; sem colisão de porta/perfil.
- Reprocessos não criam duplicatas no DB; exports consistentes.
- `metrics summary/export` refletem execuções distribuídas por perfil/proxy.

## Prioridade Atual — Proteger Contas
- Perfil por conta: um `user-data-dir` exclusivo por conta/sessão. Nunca reutilize perfis entre contas.
- 1 IP por perfil: proxy residencial/móvel estável e geolocalizado. Evite trocar IP no meio da sessão (sticky session).
- Navegador real + CDP: observar tráfego (Network.*) sem injeção JS. Manter 3P cookies, consent, Accept-Language/timezone coerentes.
- Comportamento humano: home → busca/categoria → PDP; dwell/scroll natural e timings aleatórios.
- Limites conservadores: ~1–2 req/s; orçamentos por minuto e pausas. Pare ao sinal de bloqueio.
- Health-check & disjuntor: detectar login wall/CAPTCHA/layout vazio; marcar sessão “degradada” e interromper.
- Reciclagem: reiniciar Chrome/perfil após N páginas para reduzir padrões acumulados.

## Visão Rápida (Feito vs. Falta)

### Concluído
- Login manual headful com sessão persistida (`storage_state.json`).
- Busca Playwright (scroll básico), extração de cards e export JSON/CSV.
- CDP PDP: captura via `Network.getResponseBody` e export normalizado (JSON/CSV).
- CDP Busca: captura de APIs de listagem e export normalizado (JSON/CSV).
- Enriquecimento: pipeline Busca → PDP (serial e concorrente por abas).
- Config `.env`, locale/timezone, flag para 3P cookies; diretórios e gitignore.
- CDP + Proxy por perfil (básico): `--proxy-server` respeita `PROXY_URL`.
- Perfis isolados (básico): suporte a `PROFILE_NAME` → `.user-data/profiles/<PROFILE_NAME>`.
- Health-check mínimo (CDP): se 0 respostas capturadas, marca perfil como degradado em `data/session_status/<perfil>.json` e aborta.
- Rate limiting básico (CDP): limite por minuto em navegações.
- Reciclagem por N páginas (CDP): divisão de lotes em sessões quando `--launch`.
- Coerência de headers/timezone (CDP): `Accept-Language` e `timezone` alinhados.
- Health-check ampliado + disjuntor (CDP): detecção de CAPTCHA/login/inatividade/403-429 e abort early.
- Backoff com `tenacity` nos pontos críticos do CDP (navigate/enable/getResponseBody).
- Cooldown entre chunks ao reciclar sessões CDP.
- Logs estruturados (JSON) + contadores mínimos em `data/logs/events.jsonl`.
- Paginação CDP de busca (via parâmetro `page` + `--all-pages`).
- CLI de perfis (básico): `profiles list/create/use` com atualização do `.env`.
- Validação de ambiente (domínio/locale/timezone/proxy/perfil) via `env-validate`.
- Tuning de circuito/concorrência (CDP): `CDP_INACTIVITY_S`, `CDP_CIRCUIT_ENABLED` (soft-circuit), `CDP_MAX_CONCURRENCY`; espera ajustada por `stagger`.

### Parcial
- Alinhamento de locale/UA/timezone (Playwright ok; CDP parcial – revisar UA e headers).
- Deduplicação: agora global por `(shop_id,item_id)` nas exports (PDP e Busca).
- Modelagem de dados: Schemas Pydantic aplicados a PDP/Busca.
- Scroll de busca (CDP): carregar mais itens sem trocar `page` (UX com scroll infinito) — opcional/pendente.
- Concorrência: abas concorrentes implementadas; sem scheduler/queue; métricas estruturadas básicas via CLI.

### Backlog Priorizado (necessidade → menor; em cada nível: menor esforço → maior)

Nível 1 — Essenciais (Alta necessidade)
- (sem itens pendentes nesta seção)

 Nível 2 — Importantes (Média necessidade)
- Scroll em CDP Busca (opcional): simular scroll/troca de página interna para UX que carrega mais itens sem alterar `page`.
- (concluído) Schemas Pydantic + dedup global `(shop_id,item_id)`.
- Mapeamento domínio↔região/IP (impacto: médio, esforço: baixo): validação de coerência de geo/idioma/timezone antes de rodadas.
- Proxy sticky avançado (impacto: médio, esforço: médio‑alto): suporte a extensão de autenticação/allowlist e session tag no username.

Nível 3 — Oportunidade (Baixa necessidade)
- Persistência em banco (impacto: médio, esforço: médio‑alto): SQLite/Postgres com upsert.
- CAPTCHA/OTP providers (impacto: médio, esforço: alto): 2Captcha/Anti‑Captcha e SMS API como fallback.
- Scheduler/queue (impacto: alto p/ escala, esforço: alto): Celery/RQ + limites por perfil/IP.
- Trilho mobile/anti‑detect (impacto: alto p/ resiliência, esforço: muito alto): app nativo/emulador e Kameleo.

## Mapa por Fase (Plano de Arquitetura)
- Fase 1 (MVP): concluída.
- Fase 2 (Produto/Modelo): parcial — Schemas Pydantic e dedup prontos; paginação por `page` implementada; falta scroll e cobertura de categorias.
- Fase 3 (Resiliência): avançando — rate limiting, health-check + disjuntor, backoff e logs JSON mínimos; faltam métricas estruturadas.
- Fase 4 (Perfis/Proxies): parcial — perfis isolados por `PROFILE_NAME` e `--proxy-server` básico; falta gestão de perfis via CLI e sticky avançado.
- Fase 5 (CAPTCHA/OTP): pendente — somente manual.
- Fase 6/7 (Escala/Orquestração CDP): parcial — concorrência por abas e reciclagem básica; falta scheduler/queue e métricas.
- Fases 8–12 (Mobile, Anti‑detect, Banco, Observabilidade, Compliance): em aberto (parcial em compliance básico via .env/gitignore e limites conservadores).

## Itens de Ação Detalhados (priorizados)

### Alta Prioridade (proteção de contas)
— CDP + Proxy por perfil
  - Objetivo: isolar fingerprint e reputação por perfil/conta com IP coerente.
  - Implementação (baixa complexidade):
    - Em `src/shopee_scraper/cdp/collector.py`, incluir flag `--proxy-server=<proto>://host:port` em `_build_launch_cmd` quando `settings.proxy_url` estiver definido.
    - Suporte a credenciais no próprio URL (`http://user:pass@host:port`) ou via extensão se necessário (posterior).
    - Acrescentar variáveis por perfil (ex.: `PROFILE_NAME`, `PROFILE_PROXY_URL`) e resolver `user-data-dir` para `.user-data/profiles/<PROFILE_NAME>`.
  - Sinais de sucesso: Chrome sai com IP correto (verificar em `https://ipecho.net/plain`), sessão permanece estável entre execuções.
  - Riscos: proxies instáveis ou datacenter; preferir residencial/móvel.

— Perfis isolados
  - Objetivo: cada conta tem seu perfil Chrome (cookies, cache, consent) e seu IP.
  - Implementação (baixa complexidade):
    - Permitir `PROFILE_NAME` no `.env`; montar `settings.user_data_dir = .user-data/profiles/<PROFILE_NAME>` se presente.
    - Adicionar comandos no CLI: `profiles create/list/use` (opcional numa segunda etapa). Primeiro passo: só respeitar `PROFILE_NAME`.
  - Sinais de sucesso: diretórios separados por perfil; nenhuma mistura de sessão entre contas.

— Health-check & circuit breaker
  - Objetivo: parar rápido ao detectar bloqueios para proteger reputação da conta/IP.
  - Implementação (média-baixa):
    - Reaproveitar heurísticas de `_is_captcha_gate` (Playwright) e adicionar verificação de redirecionamentos de login/erro.
    - Expor `on_block(event, context)` que marca sessão degradada (ex.: arquivo `data/session_degraded/<perfil>.flag`) e aborta lote.
    - Integrar ao trilho CDP: se não capturar respostas esperadas por N segundos ou se a navegação cair em `/verify/captcha`, acionar disjuntor e encerrar.
  - Sinais de sucesso: lotes param automaticamente; logs mostram causa e próximo passo.

— Rate limiting & backoff
  - Objetivo: reduzir a taxa de eventos e reagir a sinais de throttling.
  - Implementação (baixa):
    - Criar util `rate_limiter(tokens_per_minute)` simples por processo/perfil.
    - Aplicar `tenacity` com backoff exponencial para 429/5xx nos pontos de captura (ex.: re-tentar abrir PDP/esperar respostas).
  - Sinais de sucesso: menor incidência de bloqueios; latência previsível.

— Reciclagem por N páginas
  - Objetivo: reduzir “padrões acumulados” por longas sessões.
  - Implementação (baixa):
    - Contador de páginas no CLI/CDP; após `PAGES_PER_SESSION`, fechar e relançar Chrome com o mesmo perfil/IP (cooldown curto).
  - Sinais de sucesso: estabilidade após longos lotes; queda de bloqueios tardios.

### Média Prioridade
- Métricas estruturadas: agregações/relatório via CLI (`metrics summary`) e export (`metrics export`); notebook simples em `docs/metrics_example.ipynb`. Painel visual dedicado ainda pendente.
- Paginação CDP (Busca)
  - Simular scroll/troca de página e agregar múltiplas respostas antes do export.
- Coerência de fingerprint (CDP)
  - Alinhar UA/Accept-Language/timezone e consent; verificar 3P cookies ativas.

### Baixa Prioridade
- Banco (SQLite/Postgres) + upsert.
- CAPTCHA/OTP providers (fallback manual como padrão).
- Scheduler/queue (básico entregue; futuro: Celery/RQ e distribuição multi-instância).
- Trilho mobile e anti‑detect.

## Operação Segura (recomendações)
- Uma conta por perfil de navegador e por IP; jamais compartilhe IP entre contas simultâneas.
- Evite headless; mantenha dwell/scrolls naturais; não dispare lotes longos sem reciclar instâncias.
- Monitore sinais de bloqueio; ao primeiro sinal, interrompa e recicle perfil/IP.
- Não altere IP no meio da sessão; não limpe cookies entre páginas da mesma sessão.

## Histórico (resumo do que já foi feito)
- [x] Login headful e `storage_state.json` (Playwright)
- [x] Busca e export CSV/JSON (Playwright)
- [x] CDP PDP: captura e export
- [x] CDP Busca: captura e export
- [x] Enriquecimento Busca→PDP, com concorrência por abas
- [x] Configs via `.env`; 3P cookies flag; Accept-Language/timezone (Playwright)
- [x] Proxy por perfil no CDP (básico)
- [x] Perfis isolados multi-conta (básico via `PROFILE_NAME`)
- [x] Health-check mínimo (marca sessão degradada se 0 respostas)
- [x] Rate limiting básico (por minuto)
- [x] Reciclagem por N páginas (CDP, quando `--launch`)
- [x] Logs JSON + métricas
- [x] Schemas Pydantic + dedup global
- [x] Paginação CDP (Busca) via parâmetro `page`
- [x] CLI de perfis (list/create/use) + validação de ambiente
- [x] Métricas estruturadas básicas via CLI (summary por perfil/proxy)
- [x] Fila local e scheduler simples via CLI (`queue add-*`, `queue run`, `queue list`)
- [ ] Scroll (Busca) via CDP
- [ ] Banco (SQLite/Postgres) com upsert
- [ ] CAPTCHA/OTP providers
- [ ] Scheduler/queue (escala)
- [ ] Trilho mobile e anti‑detect

Infra de qualidade
- [x] Testes unitários básicos (utils de IO e exportadores CDP)

---

Sugestão de próxima sprint (proteção de contas):
1) Scroll em CDP de busca (infinite scroll) para agregar itens carregados sem mudança de `page`.
2) Mapeamento domínio↔região/IP e validação de coerência (geo/idioma/timezone) antes de lotes.
3) Métricas estruturadas (agregações/painel simples) sobre os logs JSON.

## Como começar a implementar (atalhos)
- Código relevante:
  - CDP: `src/shopee_scraper/cdp/collector.py` (lançamento do Chrome, filtros, navegação, captura de bodies).
  - Config: `src/shopee_scraper/config.py` (settings via `.env`).
  - CLI: `cli.py` (comandos `cdp-*` e fluxo batch/concurrent).
  - Utilitários: `src/shopee_scraper/utils.py` (delays, IO).
- Passos práticos (proxy + perfil):
  1) Adicionar `--proxy-server` em `_build_launch_cmd` se `settings.proxy_url` estiver definido.
  2) Ler `PROFILE_NAME` do `.env` e ajustar `settings.user_data_dir` para `.user-data/profiles/<PROFILE_NAME>` se presente.
  3) Testar manualmente com `python cli.py cdp-login` (ver IP) e depois `cdp-search` em baixo volume.
- Passos práticos (health-check):
  1) Encapsular heurísticas de bloqueio (captcha/login wall) e expor `is_degraded()`.
  2) Em fluxos `cdp-*`, se `is_degraded()` → encerrar lote, escrever flag e logar causa.
- Passos práticos (rate limiting/backoff):
  1) Implementar um `RateLimiter` simples (token bucket ou sleep por janela).
  2) Decorar pontos de navegação/captura com `tenacity` para 429/5xx.
