"""Testes do RespostaColetor com psycopg2 mockado."""
import sys
import types
from datetime import datetime, timezone
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

from mana_habilidade_notificacao_whatsapp import (  # noqa: E402
    Coleta,
    RespostaColetor,
    TIPO_BOOLEAN,
    TIPO_CHOICE,
    TIPO_TEXTO,
    TIPO_VALOR_NUMERICO,
    parse_boolean,
    parse_choice,
    parse_valor_numerico,
    ultimos_n_digitos,
)
from mana_habilidade_notificacao_whatsapp.exceptions import RepoError  # noqa: E402


DB_URL = "postgresql://test"


def _fake_conn_com_rows(rows):
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall = MagicMock(return_value=rows)
    cur.fetchone = MagicMock(return_value=rows[0] if rows else None)
    cur.rowcount = len(rows)
    conn.cursor = MagicMock(return_value=cur)
    return conn, cur


def _fake_row_coleta(id=1, envio_id=None, contato_id=None, tipo="valor_numerico",
                    metadata=None, prazo_ate=None, respondido_em=None,
                    texto_bruto=None, valor_parseado=None,
                    telefone_esperado="+5562999999999",
                    ultimos_digitos="99999999", match_confianca=None):
    dt = datetime.now(timezone.utc)
    return (id, envio_id, contato_id, tipo, metadata or {}, prazo_ate,
            respondido_em, texto_bruto, valor_parseado, telefone_esperado,
            ultimos_digitos, match_confianca, dt)


class TestUltimosNDigitos:
    def test_extrai_ultimos_8(self):
        assert ultimos_n_digitos("5562999999999", 8) == "99999999"

    def test_com_formatacao(self):
        assert ultimos_n_digitos("+55 (62) 9 9999-9999", 8) == "99999999"

    def test_sem_55(self):
        assert ultimos_n_digitos("62999999999", 8) == "99999999"

    def test_curto_retorna_tudo(self):
        assert ultimos_n_digitos("123", 8) == "123"

    def test_n_padrao_8(self):
        assert ultimos_n_digitos("5562999999999") == "99999999"


class TestParseValorNumerico:
    def test_reais_br(self):
        assert parse_valor_numerico("R$ 45,50 por saca") == 45.50

    def test_reais_us(self):
        assert parse_valor_numerico("$45.50") == 45.50

    def test_com_milhar_br(self):
        assert parse_valor_numerico("R$ 1.234,56") == 1234.56

    def test_com_milhar_us(self):
        assert parse_valor_numerico("1,234.56") == 1234.56

    def test_inteiro(self):
        assert parse_valor_numerico("250") == 250.0

    def test_sem_numero(self):
        assert parse_valor_numerico("não sei") is None

    def test_texto_vazio(self):
        assert parse_valor_numerico("") is None
        assert parse_valor_numerico(None) is None

    def test_primeiro_valor(self):
        assert parse_valor_numerico("45,50 hoje, 60,00 amanhã") == 45.50


class TestParseBoolean:
    def test_sim(self):
        for t in ["sim", "SIM", "Sim", "s", "yes", "y", "1", "true", "ok", "confirmo"]:
            assert parse_boolean(t) is True, f"falhou pra '{t}'"

    def test_nao(self):
        for t in ["nao", "não", "NÃO", "n", "no", "0", "false", "recuso"]:
            assert parse_boolean(t) is False, f"falhou pra '{t}'"

    def test_ambiguo(self):
        assert parse_boolean("talvez") is None
        assert parse_boolean("") is None


class TestParseChoice:
    def test_casa_case_insensitive(self):
        assert parse_choice("quero PIX por favor", ["PIX", "Boleto"]) == "PIX"

    def test_sem_match(self):
        assert parse_choice("dinheiro", ["PIX", "Boleto"]) is None

    def test_texto_vazio(self):
        assert parse_choice("", ["A"]) is None

    def test_opcoes_vazias(self):
        assert parse_choice("qualquer", []) is None


class TestRespostaColetorInit:
    def test_db_url_vazio_raises(self):
        with pytest.raises(RepoError):
            RespostaColetor(db_url="", schema="notificacoes")

    def test_schema_invalido_raises(self):
        with pytest.raises(RepoError):
            RespostaColetor(db_url=DB_URL, schema="drop; table")

    def test_ultimos_digitos_fora_intervalo(self):
        with pytest.raises(RepoError):
            RespostaColetor(db_url=DB_URL, match_ultimos_digitos=3)
        with pytest.raises(RepoError):
            RespostaColetor(db_url=DB_URL, match_ultimos_digitos=15)

    def test_ok(self):
        c = RespostaColetor(db_url=DB_URL, schema="notificacoes", match_ultimos_digitos=8)
        assert c.match_ultimos_digitos == 8


class TestRespostaColetorCriar:
    def test_criar_ok(self):
        coletor = RespostaColetor(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row_coleta()])
        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            c = coletor.criar(
                telefone_esperado="+5562999999999",
                tipo_esperado=TIPO_VALOR_NUMERICO,
                envio_id=42,
                contato_id=5,
                metadata={"produto": "arroz"},
                prazo_horas=48,
            )
        assert c is not None
        assert c.tipo_esperado == "valor_numerico"

    def test_tipo_invalido_raises(self):
        coletor = RespostaColetor(DB_URL)
        with pytest.raises(RepoError):
            coletor.criar(telefone_esperado="+5562999999999", tipo_esperado="foo")

    def test_telefone_vazio_raises(self):
        coletor = RespostaColetor(DB_URL)
        with pytest.raises(RepoError):
            coletor.criar(telefone_esperado="")


class TestRespostaColetorProcessarResposta:
    def test_match_com_valor_parseado(self):
        coletor = RespostaColetor(DB_URL)
        # Primeiro busca por coleta pendente
        # Depois UPDATE retornando atualizada
        pendente = _fake_row_coleta(
            id=100,
            tipo="valor_numerico",
            ultimos_digitos="99999999",
        )
        atualizada = _fake_row_coleta(
            id=100,
            tipo="valor_numerico",
            respondido_em=datetime.now(timezone.utc),
            texto_bruto="R$ 45,50",
            valor_parseado={"valor": 45.50},
            match_confianca=1.0,
        )

        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall = MagicMock(return_value=[pendente])
        # fetchone: primeira chamada retorna pendente, segunda retorna atualizada
        cur.fetchone = MagicMock(side_effect=[pendente, atualizada])
        conn.cursor = MagicMock(return_value=cur)

        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            r = coletor.processar_resposta(
                telefone_origem="+5562999999999",
                texto_bruto="R$ 45,50 por saca",
            )

        assert r["match"] is True
        assert r["novo"] is True
        assert r["valor_parseado"] == 45.50
        assert r["ultimos_digitos"] == "99999999"

    def test_sem_match(self):
        coletor = RespostaColetor(DB_URL)
        conn, cur = _fake_conn_com_rows([])
        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            r = coletor.processar_resposta(
                telefone_origem="+5562999999999",
                texto_bruto="Olá, quem é?",
            )
        assert r["match"] is False
        assert r["novo"] is False
        assert r["coleta"] is None
        assert r["ultimos_digitos"] == "99999999"

    def test_match_boolean(self):
        coletor = RespostaColetor(DB_URL)
        pendente = _fake_row_coleta(id=1, tipo=TIPO_BOOLEAN, ultimos_digitos="99999999")
        atualizada = _fake_row_coleta(id=1, tipo=TIPO_BOOLEAN,
                                       respondido_em=datetime.now(timezone.utc),
                                       texto_bruto="sim", valor_parseado={"valor": True})
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall = MagicMock(return_value=[pendente])
        cur.fetchone = MagicMock(side_effect=[pendente, atualizada])
        conn.cursor = MagicMock(return_value=cur)
        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            r = coletor.processar_resposta("+5562999999999", "sim")
        assert r["match"] is True
        assert r["valor_parseado"] is True

    def test_match_choice(self):
        coletor = RespostaColetor(DB_URL)
        pendente = _fake_row_coleta(id=1, tipo=TIPO_CHOICE, ultimos_digitos="99999999")
        atualizada = _fake_row_coleta(id=1, tipo=TIPO_CHOICE,
                                       respondido_em=datetime.now(timezone.utc),
                                       texto_bruto="pix", valor_parseado={"valor": "PIX"})
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall = MagicMock(return_value=[pendente])
        cur.fetchone = MagicMock(side_effect=[pendente, atualizada])
        conn.cursor = MagicMock(return_value=cur)
        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            r = coletor.processar_resposta("+5562999999999", "quero PIX",
                                            opcoes=["PIX", "Boleto"])
        assert r["match"] is True
        assert r["valor_parseado"] == "PIX"


class TestRespostaColetorListar:
    def test_listar_pendentes(self):
        coletor = RespostaColetor(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row_coleta(id=1), _fake_row_coleta(id=2)])
        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            lista = coletor.listar_pendentes()
        assert len(lista) == 2

    def test_listar_respondidas(self):
        coletor = RespostaColetor(DB_URL)
        dt = datetime.now(timezone.utc)
        conn, cur = _fake_conn_com_rows([_fake_row_coleta(id=1, respondido_em=dt)])
        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            lista = coletor.listar_respondidas(horas_recentes=24)
        assert len(lista) == 1

    def test_listar_expiradas(self):
        coletor = RespostaColetor(DB_URL)
        conn, cur = _fake_conn_com_rows([_fake_row_coleta(id=1)])
        with patch("mana_habilidade_notificacao_whatsapp.coletor.RespostaColetor._conn",
                   return_value=conn):
            lista = coletor.listar_expiradas()
        assert len(lista) == 1


class TestRespostaColetorInitSchema:
    def test_init_schema_com_conn(self):
        coletor = RespostaColetor(DB_URL, schema="notificacoes")
        conn, cur = _fake_conn_com_rows([])
        coletor.init_schema(conn=conn)
        # Executou 2 comandos: CREATE SCHEMA + CREATE TABLE + INDEX
        assert cur.execute.call_count >= 2
