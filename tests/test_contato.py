"""Testes do ContatoRepo com psycopg2 mockado."""
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Mock psycopg2 antes do import (não precisa PG real pra rodar CI)
if "psycopg2" not in sys.modules:
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_psycopg2.connect = MagicMock()
    fake_extras = types.ModuleType("psycopg2.extras")
    fake_extras.Json = lambda d: {"__json__": d}
    fake_psycopg2.extras = fake_extras
    sys.modules["psycopg2"] = fake_psycopg2
    sys.modules["psycopg2.extras"] = fake_extras

from mana_habilidade_notificacao_whatsapp import Contato, ContatoRepo  # noqa: E402
from mana_habilidade_notificacao_whatsapp.exceptions import RepoError  # noqa: E402


DB_URL = "postgresql://test"


def _fake_conn_com_rows(rows):
    """Helper: cria conn mockada que retorna `rows` no fetchall/fetchone."""
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall = MagicMock(return_value=rows)
    cur.fetchone = MagicMock(return_value=rows[0] if rows else None)
    cur.rowcount = len(rows)
    conn.cursor = MagicMock(return_value=cur)
    return conn, cur


def _fake_row(id=1, nome="João", whatsapp="5562999999999", email=None, ativo=True,
              tags=None, metadata=None):
    dt = datetime.now(timezone.utc)
    return (id, nome, whatsapp, email, ativo, tags or [], metadata or {}, dt, dt)


class TestContatoRepoInit:
    def test_db_url_vazio_raises(self):
        with pytest.raises(RepoError):
            ContatoRepo(db_url="", schema="notificacoes")

    def test_schema_invalido_raises(self):
        with pytest.raises(RepoError):
            ContatoRepo(db_url=DB_URL, schema="foo; DROP TABLE")

    def test_ok(self):
        r = ContatoRepo(db_url=DB_URL, schema="notificacoes")
        assert r.schema == "notificacoes"


class TestContatoRepoCriar:
    def test_criar_ok(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row()])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.criar(nome="João", whatsapp="62999999999")
        assert c.nome == "João"
        assert c.whatsapp == "5562999999999"

    def test_criar_nome_vazio_raises(self):
        repo = ContatoRepo(DB_URL)
        with pytest.raises(RepoError):
            repo.criar(nome="", whatsapp="62999999999")

    def test_criar_whatsapp_invalido_raises(self):
        repo = ContatoRepo(DB_URL)
        with pytest.raises(RepoError):
            repo.criar(nome="João", whatsapp="")

    def test_criar_com_tags_e_metadata(self):
        repo = ContatoRepo(DB_URL)
        row = _fake_row(tags=["revendedores"], metadata={"origem": "manual"})
        conn, cur = _fake_conn_com_rows([row])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.criar(nome="João", whatsapp="62999999999",
                           tags=["revendedores"], metadata={"origem": "manual"})
        assert c.tags == ["revendedores"]
        assert c.metadata == {"origem": "manual"}


class TestContatoRepoBuscar:
    def test_buscar_por_id_encontra(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row(id=42, nome="Maria")])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.buscar_por_id(42)
        assert c is not None
        assert c.id == 42
        assert c.nome == "Maria"

    def test_buscar_por_id_nao_encontra(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.buscar_por_id(999)
        assert c is None

    def test_buscar_por_whatsapp_normaliza(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row(whatsapp="5562999999999")])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.buscar_por_whatsapp("+55 62 99999-9999")
        assert c is not None
        # SQL foi chamado com telefone normalizado
        call_args = cur.execute.call_args
        assert call_args.args[1] == ("5562999999999",)

    def test_buscar_por_whatsapp_vazio_retorna_none(self):
        repo = ContatoRepo(DB_URL)
        assert repo.buscar_por_whatsapp("") is None


class TestContatoRepoListar:
    def test_listar_todos(self):
        repo = ContatoRepo(DB_URL)
        rows = [_fake_row(id=1, nome="A"), _fake_row(id=2, nome="B")]
        conn, cur = _fake_conn_com_rows(rows)
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            lista = repo.listar()
        assert len(lista) == 2
        assert lista[0].nome == "A"

    def test_listar_ativos_com_tags(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row(tags=["revendedores"])])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            lista = repo.listar_ativos(tags=["revendedores"])
        assert len(lista) == 1
        # SQL foi chamado com tags array
        call_args = cur.execute.call_args
        assert call_args.args[1] == (["revendedores"],)

    def test_listar_ativos_sem_tags_chama_listar(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row()])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            lista = repo.listar_ativos()
        assert len(lista) == 1


class TestContatoRepoAtualizar:
    def test_atualizar_nome(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row(nome="Novo Nome")])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.atualizar(1, nome="Novo Nome")
        assert c.nome == "Novo Nome"

    def test_atualizar_sem_campos_busca(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row()])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.atualizar(1)
        assert c is not None

    def test_atualizar_whatsapp_invalido_raises(self):
        repo = ContatoRepo(DB_URL)
        with pytest.raises(RepoError):
            repo.atualizar(1, whatsapp="")

    def test_ativar_desativar(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row(ativo=False)])
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            c = repo.desativar(1)
        assert c.ativo is False


class TestContatoRepoDeletar:
    def test_deletar(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row()])
        cur.rowcount = 1
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            assert repo.deletar(1) is True

    def test_deletar_nao_encontrado(self):
        repo = ContatoRepo(DB_URL)
        conn, cur = _fake_conn_com_rows([])
        cur.rowcount = 0
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            assert repo.deletar(999) is False


class TestContatoRepoLote:
    def test_criar_lote_ok(self):
        repo = ContatoRepo(DB_URL)
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        # Cada criar precisa retornar 1 row
        rows_iter = iter([_fake_row(id=1), _fake_row(id=2)])
        cur.fetchone = MagicMock(side_effect=lambda: next(rows_iter))
        conn.cursor = MagicMock(return_value=cur)
        with patch("mana_habilidade_notificacao_whatsapp.contato.ContatoRepo._conn", return_value=conn):
            criados = repo.criar_lote([
                {"nome": "A", "whatsapp": "62999999991"},
                {"nome": "B", "whatsapp": "62999999992"},
            ])
        assert len(criados) == 2


class TestContatoRow:
    def test_from_row_completo(self):
        dt = datetime.now(timezone.utc)
        row = (5, "João", "5562999", "j@x.com", True, ["tag1"], {"k": "v"}, dt, dt)
        c = Contato.from_row(row)
        assert c.id == 5
        assert c.email == "j@x.com"
        assert c.tags == ["tag1"]
        assert c.metadata == {"k": "v"}
        assert c.criado_em == dt.isoformat()

    def test_from_row_nulls(self):
        row = (1, "X", "5562", None, True, None, None, None, None)
        c = Contato.from_row(row)
        assert c.tags == []
        assert c.metadata == {}
        assert c.criado_em is None
