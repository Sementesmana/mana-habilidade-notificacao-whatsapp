# mana-habilidade-notificacao-whatsapp

> **Habilidade Maná Builder — Camada 2C.** Cadastro de contatos + agendamento cron + envio de notificações WhatsApp (texto, áudio TTS, PDF, imagem) via hub `agente-whatsapp`. Consolida o padrão fan-out DM que estava replicado em ~4 agentes.

## Instalação

```bash
pip install "git+https://github.com/Sementesmana/mana-habilidade-notificacao-whatsapp.git@v0.2.0"
```

Dependências: `requests`, `psycopg2-binary`, `APScheduler`. Depende também do hub HTTP `agente-whatsapp` (ADR 2026-06-13) e do `banco-mana` (Postgres compartilhado).

## Config

Env vars esperadas no agente consumidor:

```bash
AGENTE_WHATSAPP_URL=https://agente-whatsapp-production.up.railway.app
AGENTE_WHATSAPP_API_KEY=<X-API-Key do hub>
DATABASE_URL=<postgres do banco-mana>
```

## Uso mínimo

```python
from mana_habilidade_notificacao_whatsapp import (
    ContatoDDL, ContatoRepo, WhatsAppSender, NotificationScheduler,
)

# 1) Setup (uma vez no startup do agente)
ddl = ContatoDDL(db_url=DATABASE_URL, schema="comercializacao")
ddl.init_schema()  # cria schema + 3 tabelas se não existirem (idempotente)

repo = ContatoRepo(db_url=DATABASE_URL, schema="comercializacao")

sender = WhatsAppSender(
    hub_url=AGENTE_WHATSAPP_URL,
    hub_key=AGENTE_WHATSAPP_API_KEY,
    agente_nome="comercio-revendas",
    classe_default="transacional",
)

# 2) CRUD de contatos
contato = repo.criar(
    nome="João da Silva",
    whatsapp="+5562999999999",
    email="joao@revendedor.com",
    tags=["revendedores", "sudeste"],
)
todos = repo.listar_ativos(tags=["revendedores"])

# 3) Envio individual
sender.send_text("62999999999", "Sua meta desta semana...")
sender.send_pdf("62999999999", pdf_bytes, filename="meta.pdf", caption="Meta 2026-07")
sender.send_image("62999999999", png_bytes, caption="Ranking semanal")
sender.send_audio("62999999999", "Bom dia! Confira sua meta.", voz="onyx")

# 4) Broadcast (usa /send-whatsapp-lista nativo do hub — 1 chamada só)
sender.broadcast_text(
    contatos=todos,
    template="Olá {nome}, sua meta é {meta_bags} bags",
    variaveis_por_contato={
        contato.id: {"meta_bags": "50"},
    },
)

# 5) Cron (agendamento recorrente)
scheduler = NotificationScheduler(sender=sender, repo=repo)

def enviar_meta_semanal():
    contatos = repo.listar_ativos(tags=["revendedores"])
    sender.broadcast_text(contatos, "Segunda! Meta desta semana...")

scheduler.agendar_cron("meta-semanal", "0 8 * * MON", callback=enviar_meta_semanal)
scheduler.start()  # inicia APScheduler
```


## Coleta de respostas (v0.2.0 — padrão TMS)

**Padrão consolidado do `agente-tms` (validado E2E 2026-05-25):** envia msg pedindo valor → recebe resposta via `agente-router` → parseia → grava no banco.

```python
from mana_habilidade_notificacao_whatsapp import RespostaColetor, TIPO_VALOR_NUMERICO

coletor = RespostaColetor(
    db_url=DATABASE_URL,
    schema="comercializacao",
    match_ultimos_digitos=8,   # padrão TMS: tolera 55/DDD/9º dígito
)
coletor.init_schema()   # cria tabela coletas_resposta

# 1) Envia solicitação
sender.send_text(contato.whatsapp, "Distribuidor, qual o valor da saca de arroz?")

# 2) Registra que espera resposta
coleta = coletor.criar(
    telefone_esperado=contato.whatsapp,
    tipo_esperado=TIPO_VALOR_NUMERICO,   # ou TIPO_TEXTO, TIPO_BOOLEAN, TIPO_CHOICE
    contato_id=contato.id,
    metadata={"produto": "arroz", "unidade": "saca"},
    prazo_horas=48,
)

# 3) Endpoint do consumidor recebe webhook do agente-router
@app.route("/webhook-retorno", methods=["POST"])
def webhook_retorno():
    data = request.json
    r = coletor.processar_resposta(
        telefone_origem=data["telefone"],
        texto_bruto=data["texto"],
    )
    if r["match"] and r["valor_parseado"] is not None:
        # Consumidor decide o que fazer com o valor (ex.: gravar cotação)
        salvar_cotacao(r["coleta"].contato_id, r["valor_parseado"])
    return "ok"

# Listar
pendentes = coletor.listar_pendentes()
respondidas = coletor.listar_respondidas(horas_recentes=24)
expiradas = coletor.listar_expiradas()
```

**Tipos esperados de resposta:**

| Tipo | Parser | Exemplo input → output |
|---|---|---|
| `TIPO_VALOR_NUMERICO` | `parse_valor_numerico` | `"R$ 45,50 por saca"` → `45.50` |
| `TIPO_TEXTO` | strip | `"  qualquer  "` → `"qualquer"` |
| `TIPO_BOOLEAN` | sim/não/1/0/ok/... | `"sim"` → `True` |
| `TIPO_CHOICE` | contém opção (case-insensitive) | `"quero PIX"` + `["PIX","Boleto"]` → `"PIX"` |

**Match por últimos-N-dígitos** (default 8): tolera diferenças de 55/DDD/9º dígito extra. Ex.: `"5562999999999"`, `"62999999999"`, `"+55 (62) 9 9999-9999"` — todos casam com coleta cujo telefone_esperado tem os mesmos últimos 8 dígitos.

## Módulos

| API | Responsabilidade |
|---|---|
| `ContatoDDL` | `init_schema()` — cria schema + 3 tabelas idempotente |
| `ContatoRepo` | CRUD de `contatos_notificacao` (criar, buscar_por_id, buscar_por_whatsapp, listar_ativos, atualizar, ativar/desativar, deletar, criar_lote) |
| `WhatsAppSender` | `send_text`, `send_audio` (TTS), `send_pdf`, `send_document`, `send_image`, `broadcast_text` (lote nativo), `broadcast_pdf`, `broadcast_image` |
| `NotificationScheduler` | Wrapper APScheduler (`agendar_cron`, `agendar_intervalo`, `pausar`, `retomar`, `remover`, `listar_jobs`) |
| `RespostaColetor` (v0.2.0) | Cria contexto de coleta, faz match por últimos-N-dígitos, parseia resposta (numérico/texto/booleano/choice) |
| `Contato` / `Coleta` | Dataclasses (id, campos do domínio) |

## O que a habilidade automatiza

- **Normalização de telefone** — aceita `62999999999`, `+55 62 99999-9999`, `120363XYZ-group`, `abc@g.us`. Sempre envia normalizado.
- **Idempotency key determinístico** — SHA256(prefixo + telefone + hash conteúdo). Mesmo envio 2x = 1x.
- **Base64 encoding** de PDF/imagem com validação de limite 12 MB.
- **Sanitização de filename** contra path traversal.
- **Classes de envio** validadas (`conversacional`/`transacional`/`massa` — ADR 2026-06-13).
- **Payload obrigatório do hub** — `classe`, `idempotency_key`, `agente` inseridos automaticamente.
- **Fallback do broadcast** — se `/send-whatsapp-lista` do hub falhar com 400, cai pra envios individuais.
- **Truncamento de caption** — limita a 1024 chars (regra WhatsApp).
- **Cron timezone-aware** — default `America/Sao_Paulo`.

## Padrões que a habilidade IMPÕE

- **WhatsApp SÓ pelo hub** — nunca Z-API direto (ADR 2026-06-13).
- **Dedup por requisição**, não por conteúdo — idempotency_key gerado por evento único.
- **`classe` obrigatória** — dita rate limit e retry no hub.
- **`agente` obrigatório** — pra rastrear origem no `whatsapp.outbox` do hub.

## Exceções

Todas herdam de `NotificationError`:

| Exception | Quando |
|---|---|
| `ConfigError` | Env var faltando, URL/chave inválida, APScheduler não instalado |
| `RepoError` | Erro no CRUD Postgres |
| `DDLError` | Erro no `init_schema` |
| `SenderError` | Erro genérico no envio |
| `HubUnauthorized` | 401/403 (X-API-Key errada) |
| `HubValidation` | 400 do hub (payload inválido: telefone, extension, classe) |
| `HubUnavailable` | 5xx ou timeout do hub |
| `PayloadTooLarge` | Doc/imagem > 12 MB em base64 |
| `ScheduleError` | Erro no APScheduler (cron_expression inválida, etc) |

## LGPD

Trafega **PII** (nome + whatsapp + email). Se for enviar dado do contato pra LLM depois, **pseudonimize antes** com `mana-habilidade-pseudonimizar-pii`.

## Estado

**v0.2.0 — alpha** (extração inicial 2026-07-06).

Consumidor real planejado como 1º migração: `agente-comercio-revendas` (Dayan, piloto). Vira **beta** quando ele migrar em produção sem regressão. Vira **producao** quando 2+ consumidores reais rodarem.

## Testes

```bash
pytest tests/ --cov=mana_habilidade_notificacao_whatsapp
```

- **88 testes passando**
- **85% cobertura** (mínimo Maná: 70%)
- Mocks para psycopg2 e requests — CI não precisa de Postgres real

## Origem prática

- **Fan-out DM por vendedor** — `agente-gestor-comercial` (mapa_vendedores + throttle + agendamento editável)
- **Envio de imagem inline** — `agente-gestor-estoque` (Pillow gera PNG do painel → `/send-image`)
- **TTS via hub** — `agente-agronomo` (modo=audio + voz onyx)
- **Cron semanal** — `agente-premiacao` (segunda 08h BRT)

Ver `SKILL.md` para referência completa da API + gotchas.
