"""ContatoRepo — CRUD dos contatos_notificacao."""
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

from .exceptions import RepoError
from .helpers import normalizar_telefone, now_utc_iso

log = logging.getLogger("mana-habilidade-notificacao-whatsapp.contato")


@dataclass
class Contato:
    """Representação de um contato de notificação."""
    id: Optional[int] = None
    nome: str = ""
    whatsapp: str = ""
    email: Optional[str] = None
    ativo: bool = True
    tags: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    criado_em: Optional[str] = None
    atualizado_em: Optional[str] = None

    @classmethod
    def from_row(cls, row: tuple) -> "Contato":
        return cls(
            id=row[0],
            nome=row[1],
            whatsapp=row[2],
            email=row[3],
            ativo=row[4],
            tags=list(row[5]) if row[5] else [],
            metadata=row[6] if row[6] else {},
            criado_em=row[7].isoformat() if row[7] else None,
            atualizado_em=row[8].isoformat() if row[8] else None,
        )


class ContatoRepo:
    """CRUD dos contatos_notificacao no Postgres.

    Consumidor abre e injeta a conexão (padrão banco-mana com pool próprio).
    Ou o repo abre/fecha conexão sozinho a cada operação.
    """

    _CAMPOS = "id, nome, whatsapp, email, ativo, tags, metadata, criado_em, atualizado_em"

    def __init__(self, db_url: str, schema: str = "notificacoes"):
        if not db_url:
            raise RepoError("db_url vazio")
        if not schema or not schema.replace("_", "").isalnum():
            raise RepoError(f"schema inválido: '{schema}'")
        self.db_url = db_url
        self.schema = schema
        self._tabela = f'"{schema}".contatos_notificacao'

    # ---------- Conexão ----------

    def _conn(self):
        import psycopg2
        return psycopg2.connect(self.db_url)

    # ---------- Create ----------

    def criar(
        self,
        nome: str,
        whatsapp: str,
        email: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
        ativo: bool = True,
        conn=None,
    ) -> Contato:
        """Cria contato novo. Se whatsapp já existe, RepoError."""
        if not nome or not nome.strip():
            raise RepoError("nome vazio")
        tel_norm = normalizar_telefone(whatsapp)
        if not tel_norm:
            raise RepoError(f"whatsapp inválido: '{whatsapp}'")
        tags = tags or []
        metadata = metadata or {}

        sql = f"""
            INSERT INTO {self._tabela} (nome, whatsapp, email, ativo, tags, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {self._CAMPOS}
        """
        args = (nome.strip(), tel_norm, email, ativo, tags, self._as_jsonb(metadata))
        return self._exec_returning(sql, args, conn)

    # ---------- Read ----------

    def buscar_por_id(self, contato_id: int, conn=None) -> Optional[Contato]:
        sql = f"SELECT {self._CAMPOS} FROM {self._tabela} WHERE id = %s"
        rows = self._exec(sql, (contato_id,), conn, fetch=True)
        if not rows:
            return None
        return Contato.from_row(rows[0])

    def buscar_por_whatsapp(self, whatsapp: str, conn=None) -> Optional[Contato]:
        tel_norm = normalizar_telefone(whatsapp)
        if not tel_norm:
            return None
        sql = f"SELECT {self._CAMPOS} FROM {self._tabela} WHERE whatsapp = %s"
        rows = self._exec(sql, (tel_norm,), conn, fetch=True)
        if not rows:
            return None
        return Contato.from_row(rows[0])

    def listar(self, ativo: Optional[bool] = None, conn=None) -> List[Contato]:
        """Lista TODOS os contatos. `ativo` opcionalmente filtra."""
        if ativo is None:
            sql = f"SELECT {self._CAMPOS} FROM {self._tabela} ORDER BY nome"
            args = ()
        else:
            sql = f"SELECT {self._CAMPOS} FROM {self._tabela} WHERE ativo = %s ORDER BY nome"
            args = (ativo,)
        rows = self._exec(sql, args, conn, fetch=True)
        return [Contato.from_row(r) for r in rows]

    def listar_ativos(self, tags: Optional[List[str]] = None, conn=None) -> List[Contato]:
        """Lista contatos ativos, opcionalmente filtrando por tags (contém QUALQUER tag)."""
        if not tags:
            return self.listar(ativo=True, conn=conn)
        sql = f"""
            SELECT {self._CAMPOS} FROM {self._tabela}
            WHERE ativo = TRUE AND tags && %s::text[]
            ORDER BY nome
        """
        rows = self._exec(sql, (tags,), conn, fetch=True)
        return [Contato.from_row(r) for r in rows]

    # ---------- Update ----------

    def atualizar(
        self,
        contato_id: int,
        nome: Optional[str] = None,
        whatsapp: Optional[str] = None,
        email: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
        conn=None,
    ) -> Optional[Contato]:
        """Atualiza campos passados. Campos None não mudam."""
        campos = []
        args = []
        if nome is not None:
            campos.append("nome = %s")
            args.append(nome.strip())
        if whatsapp is not None:
            tel = normalizar_telefone(whatsapp)
            if not tel:
                raise RepoError(f"whatsapp inválido: '{whatsapp}'")
            campos.append("whatsapp = %s")
            args.append(tel)
        if email is not None:
            campos.append("email = %s")
            args.append(email)
        if tags is not None:
            campos.append("tags = %s")
            args.append(tags)
        if metadata is not None:
            campos.append("metadata = %s")
            args.append(self._as_jsonb(metadata))
        if not campos:
            return self.buscar_por_id(contato_id, conn)
        campos.append("atualizado_em = NOW()")
        args.append(contato_id)
        sql = f"UPDATE {self._tabela} SET {', '.join(campos)} WHERE id = %s RETURNING {self._CAMPOS}"
        return self._exec_returning(sql, tuple(args), conn, optional=True)

    def ativar(self, contato_id: int, conn=None) -> Optional[Contato]:
        return self._set_ativo(contato_id, True, conn)

    def desativar(self, contato_id: int, conn=None) -> Optional[Contato]:
        return self._set_ativo(contato_id, False, conn)

    def _set_ativo(self, contato_id: int, valor: bool, conn) -> Optional[Contato]:
        sql = f"UPDATE {self._tabela} SET ativo = %s, atualizado_em = NOW() WHERE id = %s RETURNING {self._CAMPOS}"
        return self._exec_returning(sql, (valor, contato_id), conn, optional=True)

    # ---------- Delete ----------

    def deletar(self, contato_id: int, conn=None) -> bool:
        sql = f"DELETE FROM {self._tabela} WHERE id = %s"
        rows_affected = self._exec(sql, (contato_id,), conn, fetch=False)
        return rows_affected > 0

    # ---------- Bulk ----------

    def criar_lote(self, contatos: List[dict], conn=None) -> List[Contato]:
        """Cria vários contatos numa transação. Cada dict precisa de {nome, whatsapp}."""
        criados = []
        should_close = conn is None
        if should_close:
            conn = self._conn()
        try:
            for c in contatos:
                criado = self.criar(
                    nome=c["nome"],
                    whatsapp=c["whatsapp"],
                    email=c.get("email"),
                    tags=c.get("tags"),
                    metadata=c.get("metadata"),
                    ativo=c.get("ativo", True),
                    conn=conn,
                )
                criados.append(criado)
            conn.commit()
            return criados
        except Exception as e:
            conn.rollback()
            raise RepoError(f"falha criar_lote: {e}") from e
        finally:
            if should_close:
                conn.close()

    # ---------- Helpers internos ----------

    def _exec(self, sql: str, args: tuple, conn, fetch: bool):
        """Executa SQL. Se fetch=True retorna rows; senão retorna rowcount."""
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
            raise RepoError(f"falha SQL: {e}") from e
        finally:
            if should_close:
                conn.close()

    def _exec_returning(self, sql: str, args: tuple, conn, optional: bool = False) -> Optional[Contato]:
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
                return Contato.from_row(row)
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
            raise RepoError(f"falha SQL: {e}") from e
        finally:
            if should_close:
                conn.close()

    @staticmethod
    def _as_jsonb(d: dict):
        """psycopg2 aceita dict pra jsonb via Json wrapper."""
        try:
            from psycopg2.extras import Json
            return Json(d)
        except ImportError:
            import json
            return json.dumps(d)
