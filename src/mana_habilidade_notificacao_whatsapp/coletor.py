"""RespostaColetor — coleta respostas do WhatsApp com match por últimos-8-dígitos.

Padrão consolidado do agente-tms (validado E2E 2026-05-25):
- Envia solicitação via WhatsAppSender
- Cria contexto de coleta (o que esperar de resposta)
- Agente-router relay pra endpoint /webhook-* do consumidor
- coletor.processar_resposta() faz match e parse
- Consumidor decide o que fazer com valor_parseado

Match: últimos-8-dígitos do telefone — tolera 55/DDD/9º dígito extra.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .exceptions import RepoError
from .helpers import so_digitos

log = logging.getLogger("mana-habilidade-notificacao-whatsapp.coletor")


# Tipos esperados de resposta
TIPO_VALOR_NUMERICO = "valor_numerico"
TIPO_TEXTO = "texto"
TIPO_BOOLEAN = "boolean"
TIPO_CHOICE = "choice"
TIPOS_VALIDOS = (TIPO_VALOR_NUMERICO, TIPO_TEXTO, TIPO_BOOLEAN, TIPO_CHOICE)


DDL_COLETAS = """
CREATE TABLE IF NOT EXISTS {schema}.coletas_resposta (
    id                BIGSERIAL PRIMARY KEY,
    envio_id          BIGINT REFERENCES {schema}.envios_notificacao(id) ON DELETE SET NULL,
    contato_id        BIGINT REFERENCES {schema}.contatos_notificacao(id) ON DELETE SET NULL,
    tipo_esperado     TEXT NOT NULL,
    metadata          JSONB NOT NULL DEFAULT '{{}}',
    prazo_ate         TIMESTAMPTZ,
    respondido_em     TIMESTAMPTZ,
    texto_bruto       TEXT,
    valor_parseado    JSONB,
    telefone_esperado TEXT NOT NULL,
    ultimos_digitos   TEXT NOT NULL,
    match_confianca   REAL,
    criado_em         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coletas_pendentes
    ON {schema}.coletas_resposta(ultimos_digitos)
    WHERE respondido_em IS NULL;
CREATE INDEX IF NOT EXISTS idx_coletas_contato
    ON {schema}.coletas_resposta(contato_id);
CREATE INDEX IF NOT EXISTS idx_coletas_envio
    ON {schema}.coletas_resposta(envio_id);
"""


# Regex numérico BR: R$ 1.234,56 | 1234,56 | 1234.56 | 45,50 | 45
_RE_VALOR_NUM = re.compile(
    r"[Rr]?\$?\s*([\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|[\d]+(?:[.,]\d{1,2})?)"
)


@dataclass
class Coleta:
    """Uma coleta de resposta esperada."""
    id: Optional[int] = None
    envio_id: Optional[int] = None
    contato_id: Optional[int] = None
    tipo_esperado: str = TIPO_VALOR_NUMERICO
    metadata: dict = field(default_factory=dict)
    prazo_ate: Optional[str] = None
    respondido_em: Optional[str] = None
    texto_bruto: Optional[str] = None
    valor_parseado: Any = None
    telefone_esperado: str = ""
    ultimos_digitos: str = ""
    match_confianca: Optional[float] = None
    criado_em: Optional[str] = None

    @classmethod
    def from_row(cls, row: tuple) -> "Coleta":
        return cls(
            id=row[0],
            envio_id=row[1],
            contato_id=row[2],
            tipo_esperado=row[3],
            metadata=row[4] or {},
            prazo_ate=row[5].isoformat() if row[5] else None,
            respondido_em=row[6].isoformat() if row[6] else None,
            texto_bruto=row[7],
            valor_parseado=row[8],
            telefone_esperado=row[9],
            ultimos_digitos=row[10],
            match_confianca=row[11],
            criado_em=row[12].isoformat() if row[12] else None,
        )


def ultimos_n_digitos(telefone: str, n: int = 8) -> str:
    """Extrai últimos N dígitos, ignorando prefixos 55/DDD/9º dígito.

    Ex: '5562999999999' → '99999999' (n=8)
        '+55 (62) 9 9999-9999' → '99999999'
        '62999999999' → '99999999'
    """
    d = so_digitos(telefone)
    if len(d) < n:
        return d
    return d[-n:]


def parse_valor_numerico(texto: str) -> Optional[float]:
    """Extrai o PRIMEIRO valor numérico do texto (formato BR ou US).

    Ex: 'R$ 45,50 por saca' → 45.50
        'valor é 1.234,56' → 1234.56
        '250' → 250.0
        'não sei' → None
    """
    if not texto:
        return None
    m = _RE_VALOR_NUM.search(texto)
    if not m:
        return None
    raw = m.group(1)
    # Detecta formato BR (vírgula é decimal) vs US
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            # BR: 1.234,56
            raw = raw.replace(".", "").replace(",", ".")
        else:
            # US: 1,234.56
            raw = raw.replace(",", "")
    elif "," in raw:
        # Ambíguo — se tem 2 dígitos depois da vírgula, é decimal BR
        antes, depois = raw.rsplit(",", 1)
        if len(depois) <= 2:
            raw = antes.replace(".", "") + "." + depois
        else:
            raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_boolean(texto: str) -> Optional[bool]:
    """Sim/Não/1/0/true/false/ok/não/nao."""
    if not texto:
        return None
    t = texto.strip().lower()
    if t in ("sim", "s", "yes", "y", "1", "true", "ok", "confirmo", "confirmado", "aceito"):
        return True
    if t in ("nao", "não", "n", "no", "0", "false", "recuso", "cancelo", "não aceito"):
        return False
    return None


def parse_choice(texto: str, opcoes: List[str]) -> Optional[str]:
    """Casa texto contra lista de opções (case-insensitive, palavra-a-palavra)."""
    if not texto or not opcoes:
        return None
    t = texto.strip().lower()
    for op in opcoes:
        if op.lower() in t:
            return op
    return None


class RespostaColetor:
    """Coleta respostas do WhatsApp — cria contexto, faz match por telefone, parseia valor.

    Uso típico:
        coletor = RespostaColetor(db_url, schema="comercializacao")
        coletor.init_schema()

        # 1. Envia solicitação
        r_envio = sender.send_text(contato.whatsapp, "Qual valor da saca?")

        # 2. Registra que espera resposta
        coleta = coletor.criar(
            envio_id=envio_id_gravado,
            contato_id=contato.id,
            telefone_esperado=contato.whatsapp,
            tipo_esperado="valor_numerico",
            metadata={"produto": "arroz"},
            prazo_horas=48,
        )

        # 3. Webhook do agente-router chega no endpoint do consumidor:
        r = coletor.processar_resposta(
            telefone_origem=data["telefone"],
            texto_bruto=data["texto"],
        )
        # r = {"match": True, "coleta": Coleta(...), "valor_parseado": 45.50, "novo": True}
    """

    def __init__(self, db_url: str, schema: str = "notificacoes", match_ultimos_digitos: int = 8):
        if not db_url:
            raise RepoError("db_url vazio")
        if not schema or not schema.replace("_", "").isalnum():
            raise RepoError(f"schema inválido: '{schema}'")
        if match_ultimos_digitos < 6 or match_ultimos_digitos > 11:
            raise RepoError(
                f"match_ultimos_digitos fora do intervalo válido (6-11): {match_ultimos_digitos}"
            )
        self.db_url = db_url
        self.schema = schema
        self.match_ultimos_digitos = match_ultimos_digitos
        self._tabela = f'"{schema}".coletas_resposta'

    _CAMPOS = ("id, envio_id, contato_id, tipo_esperado, metadata, prazo_ate, "
               "respondido_em, texto_bruto, valor_parseado, telefone_esperado, "
               "ultimos_digitos, match_confianca, criado_em")

    # ---------- DDL ----------

    def init_schema(self, conn=None) -> None:
        """Cria tabela coletas_resposta se não existir. Idempotente."""
        from .exceptions import DDLError
        should_close = conn is None
        if should_close:
            import psycopg2
            conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                cur.execute(DDL_COLETAS.format(schema=self.schema))
            conn.commit()
            log.info("tabela coletas_resposta inicializada no schema '%s'", self.schema)
        except Exception as e:
            conn.rollback()
            raise DDLError(f"falha init_schema coletas: {e}") from e
        finally:
            if should_close:
                conn.close()

    def _conn(self):
        import psycopg2
        return psycopg2.connect(self.db_url)

    # ---------- Create ----------

    def criar(
        self,
        telefone_esperado: str,
        tipo_esperado: str = TIPO_VALOR_NUMERICO,
        envio_id: Optional[int] = None,
        contato_id: Optional[int] = None,
        metadata: Optional[dict] = None,
        prazo_horas: Optional[float] = None,
        conn=None,
    ) -> Coleta:
        """Registra que espera resposta desse telefone."""
        if tipo_esperado not in TIPOS_VALIDOS:
            raise RepoError(f"tipo_esperado inválido: {tipo_esperado}. Use: {TIPOS_VALIDOS}")
        if not telefone_esperado:
            raise RepoError("telefone_esperado vazio")
        ult = ultimos_n_digitos(telefone_esperado, self.match_ultimos_digitos)
        prazo_ate = None
        if prazo_horas:
            prazo_ate = datetime.now(timezone.utc) + timedelta(hours=prazo_horas)

        sql = f"""
            INSERT INTO {self._tabela}
                (envio_id, contato_id, tipo_esperado, metadata, prazo_ate,
                 telefone_esperado, ultimos_digitos)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING {self._CAMPOS}
        """
        args = (
            envio_id,
            contato_id,
            tipo_esperado,
            self._as_jsonb(metadata or {}),
            prazo_ate,
            telefone_esperado,
            ult,
        )
        return self._exec_returning(sql, args, conn)

    # ---------- Processar resposta ----------

    def processar_resposta(
        self,
        telefone_origem: str,
        texto_bruto: str,
        opcoes: Optional[List[str]] = None,
        conn=None,
    ) -> Dict[str, Any]:
        """Recebe resposta do webhook, casa por telefone, parseia valor, grava.

        Retorna dict:
          {
            "match": bool,
            "coleta": Coleta | None,
            "valor_parseado": Any,
            "texto_bruto": str,
            "telefone_origem": str,
            "ultimos_digitos": str,
            "novo": bool,   # False se coleta já tinha sido respondida
          }
        """
        ult = ultimos_n_digitos(telefone_origem, self.match_ultimos_digitos)
        # Busca coleta pendente pra esses últimos dígitos, mais recente primeiro
        sql_busca = f"""
            SELECT {self._CAMPOS} FROM {self._tabela}
            WHERE ultimos_digitos = %s AND respondido_em IS NULL
            ORDER BY criado_em DESC
            LIMIT 1
        """
        rows = self._exec(sql_busca, (ult,), conn, fetch=True)

        if not rows:
            return {
                "match": False,
                "coleta": None,
                "valor_parseado": None,
                "texto_bruto": texto_bruto,
                "telefone_origem": telefone_origem,
                "ultimos_digitos": ult,
                "novo": False,
            }

        coleta = Coleta.from_row(rows[0])

        # Parseia conforme tipo esperado
        valor = self._parsear(coleta.tipo_esperado, texto_bruto, opcoes)

        # Grava resposta
        sql_update = f"""
            UPDATE {self._tabela}
            SET respondido_em = NOW(),
                texto_bruto = %s,
                valor_parseado = %s,
                match_confianca = %s
            WHERE id = %s
            RETURNING {self._CAMPOS}
        """
        confianca = 1.0 if valor is not None else 0.5   # match por telefone mas parse falhou
        coleta_atualizada = self._exec_returning(
            sql_update,
            (texto_bruto, self._as_jsonb({"valor": valor}), confianca, coleta.id),
            conn,
            optional=True,
        )

        return {
            "match": True,
            "coleta": coleta_atualizada,
            "valor_parseado": valor,
            "texto_bruto": texto_bruto,
            "telefone_origem": telefone_origem,
            "ultimos_digitos": ult,
            "novo": True,
        }

    @staticmethod
    def _parsear(tipo: str, texto: str, opcoes: Optional[List[str]]) -> Any:
        if tipo == TIPO_VALOR_NUMERICO:
            return parse_valor_numerico(texto)
        if tipo == TIPO_BOOLEAN:
            return parse_boolean(texto)
        if tipo == TIPO_CHOICE:
            return parse_choice(texto, opcoes or [])
        if tipo == TIPO_TEXTO:
            return texto.strip() if texto else None
        return None

    # ---------- Read ----------

    def buscar_por_id(self, coleta_id: int, conn=None) -> Optional[Coleta]:
        sql = f"SELECT {self._CAMPOS} FROM {self._tabela} WHERE id = %s"
        rows = self._exec(sql, (coleta_id,), conn, fetch=True)
        if not rows:
            return None
        return Coleta.from_row(rows[0])

    def listar_pendentes(self, conn=None) -> List[Coleta]:
        """Coletas ainda sem resposta."""
        sql = f"SELECT {self._CAMPOS} FROM {self._tabela} WHERE respondido_em IS NULL ORDER BY criado_em DESC"
        rows = self._exec(sql, (), conn, fetch=True)
        return [Coleta.from_row(r) for r in rows]

    def listar_respondidas(self, horas_recentes: Optional[int] = None, conn=None) -> List[Coleta]:
        """Coletas já respondidas. Opcional: só das últimas N horas."""
        if horas_recentes:
            sql = f"""
                SELECT {self._CAMPOS} FROM {self._tabela}
                WHERE respondido_em IS NOT NULL
                  AND respondido_em >= NOW() - INTERVAL '%s hours'
                ORDER BY respondido_em DESC
            """
            args = (horas_recentes,)
        else:
            sql = f"SELECT {self._CAMPOS} FROM {self._tabela} WHERE respondido_em IS NOT NULL ORDER BY respondido_em DESC"
            args = ()
        rows = self._exec(sql, args, conn, fetch=True)
        return [Coleta.from_row(r) for r in rows]

    def listar_expiradas(self, conn=None) -> List[Coleta]:
        """Coletas com prazo vencido sem resposta."""
        sql = f"""
            SELECT {self._CAMPOS} FROM {self._tabela}
            WHERE respondido_em IS NULL
              AND prazo_ate IS NOT NULL
              AND prazo_ate < NOW()
            ORDER BY prazo_ate ASC
        """
        rows = self._exec(sql, (), conn, fetch=True)
        return [Coleta.from_row(r) for r in rows]

    # ---------- Helpers internos ----------

    def _exec(self, sql: str, args: tuple, conn, fetch: bool):
        should_close = conn is None
        if should_close:
            conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                if fetch:
                    return cur.fetchall()
                result = cur.rowcount
            if should_close:
                conn.commit()
            return result
        except Exception as e:
            if should_close:
                conn.rollback()
            raise RepoError(f"falha SQL coletor: {e}") from e
        finally:
            if should_close:
                conn.close()

    def _exec_returning(self, sql: str, args: tuple, conn, optional: bool = False) -> Optional[Coleta]:
        should_close = conn is None
        if should_close:
            conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                row = cur.fetchone()
            if should_close:
                conn.commit()
            if row:
                return Coleta.from_row(row)
            if optional:
                return None
            raise RepoError("nenhuma linha retornada")
        except RepoError:
            if should_close:
                conn.rollback()
            raise
        except Exception as e:
            if should_close:
                conn.rollback()
            raise RepoError(f"falha SQL coletor: {e}") from e
        finally:
            if should_close:
                conn.close()

    @staticmethod
    def _as_jsonb(d):
        try:
            from psycopg2.extras import Json
            return Json(d)
        except ImportError:
            return json.dumps(d)
