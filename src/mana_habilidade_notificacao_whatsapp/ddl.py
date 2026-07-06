"""DDL — criação idempotente do schema/tabelas."""
import logging
from typing import Optional

from .exceptions import DDLError

log = logging.getLogger("mana-habilidade-notificacao-whatsapp.ddl")


DDL_CONTATOS = """
CREATE TABLE IF NOT EXISTS {schema}.contatos_notificacao (
    id           BIGSERIAL PRIMARY KEY,
    nome         TEXT NOT NULL,
    whatsapp     TEXT NOT NULL,
    email        TEXT,
    ativo        BOOLEAN NOT NULL DEFAULT TRUE,
    tags         TEXT[] NOT NULL DEFAULT '{{}}',
    metadata     JSONB NOT NULL DEFAULT '{{}}',
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(whatsapp)
);
"""

DDL_ENVIOS = """
CREATE TABLE IF NOT EXISTS {schema}.envios_notificacao (
    id                BIGSERIAL PRIMARY KEY,
    idempotency_key   TEXT NOT NULL,
    contato_id        BIGINT REFERENCES {schema}.contatos_notificacao(id) ON DELETE SET NULL,
    telefone          TEXT NOT NULL,
    tipo              TEXT NOT NULL,
    conteudo_hash     TEXT,
    hub_response      JSONB,
    sucesso           BOOLEAN NOT NULL DEFAULT FALSE,
    erro              TEXT,
    tentativa         INT NOT NULL DEFAULT 1,
    enviado_em        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_envios_contato ON {schema}.envios_notificacao(contato_id);
CREATE INDEX IF NOT EXISTS idx_envios_data ON {schema}.envios_notificacao(enviado_em DESC);
"""

DDL_JOBS = """
CREATE TABLE IF NOT EXISTS {schema}.jobs_notificacao (
    id            TEXT PRIMARY KEY,
    nome          TEXT NOT NULL,
    cron          TEXT NOT NULL,
    ativo         BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_run    TIMESTAMPTZ,
    proximo_run   TIMESTAMPTZ,
    metadata      JSONB NOT NULL DEFAULT '{{}}',
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class ContatoDDL:
    """Cria/verifica o schema e as 3 tabelas da habilidade.

    Idempotente — pode chamar init_schema() no startup do agente sempre.
    """

    def __init__(self, db_url: str, schema: str = "notificacoes"):
        if not db_url:
            raise DDLError("db_url vazio")
        if not schema or not schema.replace("_", "").isalnum():
            raise DDLError(f"schema inválido: '{schema}' (só alfanum + _)")
        self.db_url = db_url
        self.schema = schema

    def init_schema(self, conn=None) -> None:
        """Cria schema + 3 tabelas se não existirem.

        Se conn for passado, usa a conexão do consumidor. Senão abre uma nova.
        """
        should_close = False
        if conn is None:
            import psycopg2
            conn = psycopg2.connect(self.db_url)
            should_close = True
        try:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                cur.execute(DDL_CONTATOS.format(schema=self.schema))
                cur.execute(DDL_ENVIOS.format(schema=self.schema))
                cur.execute(DDL_JOBS.format(schema=self.schema))
            conn.commit()
            log.info("schema '%s' + tabelas contatos/envios/jobs inicializados", self.schema)
        except Exception as e:
            conn.rollback()
            raise DDLError(f"falha init_schema: {e}") from e
        finally:
            if should_close:
                conn.close()

    def drop_all(self, conn=None) -> None:
        """Drop das tabelas (útil em testes). NÃO chamar em produção."""
        should_close = False
        if conn is None:
            import psycopg2
            conn = psycopg2.connect(self.db_url)
            should_close = True
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{self.schema}".envios_notificacao CASCADE')
                cur.execute(f'DROP TABLE IF EXISTS "{self.schema}".jobs_notificacao CASCADE')
                cur.execute(f'DROP TABLE IF EXISTS "{self.schema}".contatos_notificacao CASCADE')
            conn.commit()
            log.warning("drop_all executado no schema '%s'", self.schema)
        finally:
            if should_close:
                conn.close()
