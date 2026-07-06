"""Testes do ContatoDDL com psycopg2 mockado."""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

if "psycopg2" not in sys.modules:
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_psycopg2.connect = MagicMock()
    fake_extras = types.ModuleType("psycopg2.extras")
    fake_extras.Json = lambda d: {"__json__": d}
    fake_psycopg2.extras = fake_extras
    sys.modules["psycopg2"] = fake_psycopg2
    sys.modules["psycopg2.extras"] = fake_extras

from mana_habilidade_notificacao_whatsapp import ContatoDDL  # noqa: E402
from mana_habilidade_notificacao_whatsapp.exceptions import DDLError  # noqa: E402


DB_URL = "postgresql://test"


def _fake_conn():
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor = MagicMock(return_value=cur)
    return conn, cur


class TestDDLInit:
    def test_db_url_vazio_raises(self):
        with pytest.raises(DDLError):
            ContatoDDL(db_url="", schema="notificacoes")

    def test_schema_invalido_raises(self):
        with pytest.raises(DDLError):
            ContatoDDL(db_url=DB_URL, schema="drop table")


class TestDDLInitSchema:
    def test_init_schema_com_conn_externa(self):
        conn, cur = _fake_conn()
        ddl = ContatoDDL(db_url=DB_URL, schema="notificacoes")
        ddl.init_schema(conn=conn)

        # Chamou execute 4 vezes (CREATE SCHEMA + 3 tabelas)
        assert cur.execute.call_count == 4
        # Primeiro é CREATE SCHEMA
        primeiro_sql = cur.execute.call_args_list[0].args[0]
        assert "CREATE SCHEMA IF NOT EXISTS" in primeiro_sql
        assert "notificacoes" in primeiro_sql
        # Commit foi chamado
        conn.commit.assert_called_once()

    def test_init_schema_erro_dispara_rollback(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.execute = MagicMock(side_effect=Exception("boom"))
        conn.cursor = MagicMock(return_value=cur)
        ddl = ContatoDDL(db_url=DB_URL)
        with pytest.raises(DDLError):
            ddl.init_schema(conn=conn)
        conn.rollback.assert_called_once()

    def test_drop_all(self):
        conn, cur = _fake_conn()
        ddl = ContatoDDL(db_url=DB_URL, schema="notificacoes")
        ddl.drop_all(conn=conn)
        # 3 DROPs
        assert cur.execute.call_count == 3
        for call in cur.execute.call_args_list:
            assert "DROP TABLE IF EXISTS" in call.args[0]
        conn.commit.assert_called_once()
