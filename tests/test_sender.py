"""Testes do WhatsAppSender com hub mockado."""
import base64
import pytest
from unittest.mock import MagicMock, patch

from mana_habilidade_notificacao_whatsapp import WhatsAppSender
from mana_habilidade_notificacao_whatsapp.exceptions import (
    ConfigError,
    HubUnauthorized,
    HubValidation,
    PayloadTooLarge,
)


HUB_URL = "https://hub.test"
HUB_KEY = "test-key"


class TestSenderInit:
    def test_url_vazio_raises(self):
        with pytest.raises(ConfigError):
            WhatsAppSender(hub_url="", hub_key="k", agente_nome="a")

    def test_key_vazio_raises(self):
        with pytest.raises(ConfigError):
            WhatsAppSender(hub_url=HUB_URL, hub_key="", agente_nome="a")

    def test_agente_vazio_raises(self):
        with pytest.raises(ConfigError):
            WhatsAppSender(hub_url=HUB_URL, hub_key="k", agente_nome="")

    def test_classe_invalida_raises(self):
        with pytest.raises(ConfigError):
            WhatsAppSender(hub_url=HUB_URL, hub_key="k", agente_nome="a", classe_default="foo")

    def test_trailing_slash_no_hub_url_removida(self):
        s = WhatsAppSender(hub_url=HUB_URL + "/", hub_key="k", agente_nome="a")
        assert s.hub_url == HUB_URL


class TestSenderSendText:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_text_sucesso(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp

        r = self.sender.send_text("62999999999", "Olá mundo")

        assert r["sucesso"] is True
        assert r["hub_response"] == {"ok": True}
        assert r["telefone"] == "5562999999999"
        assert "idempotency_key" in r

        call = mock_requests.post.call_args
        body = call.kwargs["json"]
        assert body["telefone"] == "5562999999999"
        assert body["mensagem"] == "Olá mundo"
        assert body["agente"] == "teste"
        assert body["classe"] == "transacional"
        assert "idempotency_key" in body

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_text_401_retorna_sucesso_false(self, mock_requests):
        mock_resp = MagicMock(status_code=401)
        mock_resp.text = "unauthorized"
        mock_requests.post.return_value = mock_resp

        r = self.sender.send_text("62999999999", "Olá")

        assert r["sucesso"] is False
        assert "HubUnauthorized" in r["erro_tipo"]

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_text_500_retorna_sucesso_false(self, mock_requests):
        mock_resp = MagicMock(status_code=500)
        mock_resp.text = "internal error"
        mock_requests.post.return_value = mock_resp

        r = self.sender.send_text("62999999999", "Olá")

        assert r["sucesso"] is False
        assert r["erro_tipo"] == "HubUnavailable"

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_text_idempotency_key_custom(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp

        r = self.sender.send_text("62999999999", "msg", idempotency_key="MEU-KEY-123")

        assert r["idempotency_key"] == "MEU-KEY-123"
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["idempotency_key"] == "MEU-KEY-123"


class TestSenderSendPdf:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_pdf_encoda_base64(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp

        pdf = b"%PDF-1.4\n%test binary"
        r = self.sender.send_pdf("62999999999", pdf, filename="rel.pdf", caption="Legenda")

        assert r["sucesso"] is True
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["documento"] == base64.b64encode(pdf).decode("ascii")
        assert body["filename"] == "rel.pdf"
        assert body["extension"] == "pdf"
        assert body["caption"] == "Legenda"

    def test_send_pdf_payload_grande_raises(self):
        pdf_grande = b"x" * (10 * 1024 * 1024)
        with pytest.raises(PayloadTooLarge):
            self.sender.send_pdf("62999999999", pdf_grande, filename="grande.pdf")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_pdf_filename_sanitizado(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp

        self.sender.send_pdf("62999999999", b"pdf", filename="rel/tarde;drop.pdf")
        body = mock_requests.post.call_args.kwargs["json"]
        assert "/" not in body["filename"]
        assert ";" not in body["filename"]


class TestSenderSendImage:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_image_png_default(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp

        img = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        r = self.sender.send_image("62999999999", img, caption="cap")

        assert r["sucesso"] is True
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["imagem"] == base64.b64encode(img).decode("ascii")
        assert body["extension"] == "png"
        assert body["caption"] == "cap"

    def test_send_image_extension_invalida(self):
        with pytest.raises(HubValidation):
            self.sender.send_image("62999999999", b"gif89a", extension="gif")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_image_jpeg_ok(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp
        r = self.sender.send_image("62999999999", b"jpeg", extension="jpeg")
        assert r["sucesso"] is True


class TestSenderBroadcast:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_broadcast_text_usa_endpoint_lista(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"processados": 2}
        mock_requests.post.return_value = mock_resp

        from mana_habilidade_notificacao_whatsapp import Contato
        contatos = [
            Contato(id=1, nome="João", whatsapp="5562999999999"),
            Contato(id=2, nome="Maria", whatsapp="5562888888888"),
        ]
        resultados = self.sender.broadcast_text(contatos, "Olá {nome}")

        assert len(resultados) == 2
        # Só 1 chamada HTTP (endpoint /send-whatsapp-lista)
        assert mock_requests.post.call_count == 1
        call = mock_requests.post.call_args
        assert call.args[0].endswith("/send-whatsapp-lista")
        body = call.kwargs["json"]
        assert len(body["itens"]) == 2
        assert body["itens"][0]["mensagem"] == "Olá João"
        assert body["itens"][1]["mensagem"] == "Olá Maria"
