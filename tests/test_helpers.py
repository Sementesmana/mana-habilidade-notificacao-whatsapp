"""Testes dos helpers puros — sem I/O."""
import pytest

from mana_habilidade_notificacao_whatsapp.helpers import (
    format_template,
    gerar_idempotency_key,
    normalizar_telefone,
    so_digitos,
    truncate_str,
)


class TestSoDigitos:
    def test_string_normal(self):
        assert so_digitos("62 99999-9999") == "62999999999"

    def test_ja_so_digitos(self):
        assert so_digitos("62999999999") == "62999999999"

    def test_vazio(self):
        assert so_digitos("") == ""
        assert so_digitos(None) == ""

    def test_int(self):
        assert so_digitos(62999999999) == "62999999999"

    def test_so_letras(self):
        assert so_digitos("abc") == ""


class TestNormalizarTelefone:
    def test_com_ddd_sem_55(self):
        assert normalizar_telefone("62999999999") == "5562999999999"

    def test_com_ddd_e_55(self):
        assert normalizar_telefone("5562999999999") == "5562999999999"

    def test_com_mais_e_espacos(self):
        assert normalizar_telefone("+55 62 99999-9999") == "5562999999999"

    def test_grupo_group(self):
        assert normalizar_telefone("120363XYZ-group") == "120363XYZ-group"

    def test_grupo_gus(self):
        assert normalizar_telefone("abc@g.us") == "abc@g.us"

    def test_vazio(self):
        assert normalizar_telefone("") == ""
        assert normalizar_telefone(None) == ""

    def test_10_digitos(self):
        assert normalizar_telefone("6299999999") == "556299999999"


class TestIdempotencyKey:
    def test_deterministico(self):
        k1 = gerar_idempotency_key("test", "62999999999", "extra1")
        k2 = gerar_idempotency_key("test", "62999999999", "extra1")
        assert k1 == k2

    def test_prefixo_no_inicio(self):
        k = gerar_idempotency_key("meu-prefixo", "62999999999")
        assert k.startswith("meu-prefixo:")

    def test_extras_diferentes_geram_keys_diferentes(self):
        k1 = gerar_idempotency_key("t", "62999999999", "a")
        k2 = gerar_idempotency_key("t", "62999999999", "b")
        assert k1 != k2

    def test_telefones_diferentes_mesmo_normalizado_geram_igual(self):
        k1 = gerar_idempotency_key("t", "62999999999")
        k2 = gerar_idempotency_key("t", "+55 62 99999-9999")
        assert k1 == k2, "normalizar deveria produzir mesma key"


class TestTruncateStr:
    def test_menor_que_limite(self):
        assert truncate_str("abc", 10) == "abc"

    def test_maior_que_limite(self):
        result = truncate_str("abcdefghij", 5)
        assert result == "abcd…"
        assert len(result) == 5

    def test_none(self):
        assert truncate_str(None, 10) == ""

    def test_vazio(self):
        assert truncate_str("", 10) == ""


class TestFormatTemplate:
    def test_substituicao_simples(self):
        assert format_template("Olá {nome}", {"nome": "João"}) == "Olá João"

    def test_multiplas_variaveis(self):
        r = format_template("{a}+{b}={c}", {"a": "1", "b": "2", "c": "3"})
        assert r == "1+2=3"

    def test_chave_faltante_preserva_placeholder(self):
        r = format_template("Olá {nome}, {saudacao}", {"nome": "João"})
        assert r == "Olá João, {saudacao}"

    def test_sem_variaveis(self):
        assert format_template("texto puro", None) == "texto puro"

    def test_template_vazio(self):
        assert format_template("", {"a": "b"}) == ""
