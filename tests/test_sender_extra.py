"""Testes extras do WhatsAppSender — broadcast_pdf/image, send_audio, send_document raw."""
from unittest.mock import MagicMock, patch

from mana_habilidade_notificacao_whatsapp import Contato, WhatsAppSender


HUB_URL = "https://hub.test"
HUB_KEY = "test-key"


class TestSendAudio:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_audio_com_voz(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp
        r = self.sender.send_audio("62999999999", "Mensagem", voz="onyx")
        assert r["sucesso"] is True
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["modo"] == "audio"
        assert body["voz"] == "onyx"

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_audio_sem_voz(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp
        r = self.sender.send_audio("62999999999", "Mensagem")
        assert r["sucesso"] is True
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["modo"] == "audio"
        assert "voz" not in body


class TestSendDocumentRaw:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_send_document_extension_custom(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp
        r = self.sender.send_document("62999999999", b"XLSX content",
                                       filename="relatorio.xlsx", extension="xlsx",
                                       caption="Q1")
        assert r["sucesso"] is True
        body = mock_requests.post.call_args.kwargs["json"]
        assert body["extension"] == "xlsx"
        assert body["caption"] == "Q1"


class TestBroadcastPdf:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_broadcast_pdf_para_lista(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp

        contatos = [
            Contato(id=1, nome="A", whatsapp="5562999999991"),
            Contato(id=2, nome="B", whatsapp="5562999999992"),
        ]
        resultados = self.sender.broadcast_pdf(contatos, b"PDF", filename="rel.pdf")
        assert len(resultados) == 2
        assert all(r["sucesso"] for r in resultados)
        # 2 chamadas separadas ao endpoint (hub não tem lote pra doc)
        assert mock_requests.post.call_count == 2


class TestBroadcastImage:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_broadcast_image_para_lista(self, mock_requests):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_requests.post.return_value = mock_resp

        contatos = [
            Contato(id=1, nome="A", whatsapp="5562999999991"),
            Contato(id=2, nome="B", whatsapp="5562999999992"),
        ]
        resultados = self.sender.broadcast_image(contatos, b"PNG", extension="png",
                                                  caption="cap")
        assert len(resultados) == 2
        assert mock_requests.post.call_count == 2


class TestBroadcastTextFallback:
    """Se hub rejeitar /send-whatsapp-lista com 400, cai pra individual."""

    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    @patch("mana_habilidade_notificacao_whatsapp.sender.requests")
    def test_fallback_individual_quando_lista_falha(self, mock_requests):
        # Primeira chamada (/send-whatsapp-lista) → 400
        # Chamadas seguintes (/send-whatsapp) → 200
        respostas = [
            MagicMock(status_code=400, text="lista não suportado"),
            MagicMock(status_code=200),
            MagicMock(status_code=200),
        ]
        for r in respostas[1:]:
            r.json.return_value = {"ok": True}
        mock_requests.post.side_effect = respostas

        contatos = [
            Contato(id=1, nome="A", whatsapp="5562999999991"),
            Contato(id=2, nome="B", whatsapp="5562999999992"),
        ]
        resultados = self.sender.broadcast_text(contatos, "Olá {nome}")
        # 1 tentativa de lote + 2 individuais = 3 chamadas
        assert mock_requests.post.call_count == 3
        assert len(resultados) == 2


class TestSendTextValidacoes:
    def setup_method(self):
        self.sender = WhatsAppSender(hub_url=HUB_URL, hub_key=HUB_KEY, agente_nome="teste")

    def test_telefone_invalido_raises(self):
        from mana_habilidade_notificacao_whatsapp.exceptions import HubValidation
        import pytest
        with pytest.raises(HubValidation):
            self.sender.send_text("", "msg")

    def test_classe_invalida_raises(self):
        from mana_habilidade_notificacao_whatsapp.exceptions import HubValidation
        import pytest
        with pytest.raises(HubValidation):
            self.sender.send_text("62999999999", "msg", classe="foo")
