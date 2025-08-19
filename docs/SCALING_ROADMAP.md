# Shopee Scraper — Roadmap de Escala (2025)

Este documento detalha o porquê e o como das mudanças necessárias para sair de 1 máquina/1 proxy/1 perfil para múltiplos perfis/proxies e múltiplos workers, preservando higiene de contas, reduzindo detecção e mantendo dados consistentes.

## Objetivos
- Distribuir captura CDP entre vários perfis e IPs alinhados à região.
- Garantir limites de taxa por perfil e por proxy (globais e coordenados).
- Evitar colisões de porta/perfil no mesmo host.
- Tornar reprocessos idempotentes (upsert por `(shop_id,item_id)`).
- Melhorar observabilidade (sucesso, latência, bans/hora) para operação segura.

## Estado Atual (resumo)
- Chrome real via CDP, perfis isolados (`PROFILE_NAME` → `.user-data/profiles/<name>`), `--proxy-server` a partir de `PROXY_URL`.
- Disjuntor + backoff + rate limiting por minuto (local) e reciclagem por `PAGES_PER_SESSION`.
- Concurrency via abas (limite por `CDP_MAX_CONCURRENCY`) e `stagger`.
- Exports normalizados (JSON/CSV) com dedup global por `(shop_id,item_id)`.
- Fila local (arquivos), métricas básicas via CLI a partir de `data/logs/events.jsonl`.

## Por que mudar (riscos/limites)
- Um único IP/fingerprint concentra tráfego → bloqueios aumentam e throughput cai.
- Fila local não coordena trabalhadores nem limites por IP/perfil.
- Porta CDP única → várias instâncias de Chrome colidem no mesmo host.
- Arquivos não escalam bem para dedup/consulta/entrega em paralelo.

## Mudanças Propostas (o que, por quê, como)

1) Registro de Perfis & Proxies
- Por quê: manter 1 perfil ↔ 1 IP com parâmetros específicos (região, idioma, limites).
- Como: `data/profiles.yaml` (gitignored) + loader `src/shopee_scraper/profiles.py`.
- Conteúdo: `profile_name`, `proxy_url (sticky)`, `locale`, `timezone`, `rps_limit`, `cdp_port_range`, `notes`.
- CLI: `python cli.py profiles validate --all` para validar coerência domínio↔região/locale/timezone.

2) Fila Distribuída + Workers
- Por quê: distribuir tarefas com reintentos e roteamento por perfil/região.
- Como: Redis + RQ (ou Celery). Adaptar `scheduler.py` mantendo modo local como fallback.
- CLI: `python cli.py worker --profile br_01` (um worker por perfil) e `python cli.py workers start --profiles br_01 br_02`.
- Roteamento: tarefas de `shopee.com.br` → perfis BR; futuras regiões usam perfis dedicados.

3) Rate Limiting Global & Locks
- Por quê: evitar floods e uso concorrente do mesmo perfil.
- Como: token bucket Redis por `profile_name` e `proxy_url` + lock distribuído (chave por perfil) antes de abrir Chrome ou navegar.
- Integração: substituir `RateLimiter` local nos caminhos CDP por wrapper distribuído.

4) Gestão de Chrome/CDP no Host
- Por quê: suportar N instâncias de Chrome por host sem colisão.
- Como: `CDP_PORT_RANGE=9300-9400` no `.env`; alocador de porta livre; lock por `user-data-dir` (arquivo `.lock`).
- Reciclagem: manter `PAGES_PER_SESSION` com jitter (2–5s) para reduzir padrões detectáveis.

5) Persistência e Idempotência
- Por quê: dedup cross-workers e entrega consistente.
- Como: `src/shopee_scraper/db.py` (SQLite → Postgres), upsert por `(shop_id,item_id)`, índices.
- Exporters: continuam gerando JSON/CSV e passam a gravar no DB (tabelas `pdp`, `search_items`, `runs`).

6) Observabilidade
- Por quê: operar com segurança e reagir cedo a degradações.
- Como: logs centralizados (stdout → coletor), `metrics summary/export` lê DB/logs e agrega por perfil/proxy.
- Painel simples (notebook/CSV) e alertas mínimos (ex.: bans/hora acima do limite).

7) Empacotamento & Deploy
- Por quê: padronizar execução e habilitar escala horizontal.
- Como: Dockerfile com Chrome estável e fontes; entrypoints `cli.py worker` e `cli.py queue`.
- Orquestração: múltiplos containers, cada um com `PROFILE_NAME` e `PROXY_URL` distintos (via `profiles.yaml` ou envs).

## Fases e Entregas (com critérios de aceitação)

Fase 0 — Preparação (baixo risco)
- Entregas: `profiles.yaml`, loader e validação; `CDP_PORT_RANGE` + alocador; lockfile por perfil.
- Critérios: 2 Chromes no mesmo host com perfis/portas diferentes, sem colisões; validação de perfis ok.

Fase 1 — Containerização
- Entregas: Dockerfile, imagem com Chrome e deps Python; entrypoints.
- Critérios: rodar `cdp-search` e `cdp-enrich-search` em container com um perfil funcionando via proxy sticky.

Fase 2 — Fila Distribuída e Workers
- Entregas: Redis + RQ (ou Celery), `cli.py worker`, adaptação de `scheduler.py`.
- Critérios: 2 workers/host e 2 hosts processando tarefas sem violar RPS por perfil/IP; sem compartilhamento acidental de perfil.

Fase 3 — Rate Limiting Global e Locks
- Entregas: token bucket Redis por `profile_name` e `proxy_url`; `with_profile_lock(..)` aplicado nos caminhos CDP.
- Critérios: ao dobrar número de workers, taxa efetiva por perfil/IP permanece dentro do orçamento configurado.

Fase 4 — Banco e Idempotência
- Entregas: `db.py` (SQLite primeiro), tabelas e índices; exporters gravam no DB com upsert.
- Critérios: reexecuções não criam duplicatas; consultas por `(shop_id,item_id)` retornam registro único e mais recente.

Fase 5 — Observabilidade
- Entregas: métricas agregadas por perfil/proxy, export CSV/JSON; notebook de painel; thresholds de alerta documentados.
- Critérios: ver taxa de sucesso, duração média e bans/hora por perfil/proxy em janelas de 1h/24h.

## Riscos e Mitigações
- Proxies instáveis: preferir residencial/móvel sticky; monitorar bans/hora; reciclar perfis/IPs sob degradação.
- Detecção por padrões: manter reciclagem com jitter, evitar bursts (stagger), alinhar locale/timezone/UA.
- Complexidade operacional: começar pequeno (3–5 perfis), padronizar via container, automatizar validações.

## Próximos Passos Imediatos
- Especificar `profiles.yaml` + loader.
- Implementar `CDP_PORT_RANGE` e lock por `user-data-dir`.
- Esboçar Dockerfile base.

