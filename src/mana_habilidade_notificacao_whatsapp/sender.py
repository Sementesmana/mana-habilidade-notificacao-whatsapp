"""WhatsAppSender — cliente do hub agente-whatsapp (texto, PDF, imagem, lista)."""
import base64
import hashlib
import logging
from typing import Any, Dict, List, Optional, Union

import requests

from .exceptions import (
    ConfigError,
    HubUnauthorized,
    HubUnavailable,
    HubValidation,
    PayloadTooLarge,
    SenderError,
)
from .helpers import gerar_idempotency_key, normalizar_telefone, truncate_str

log = logging.getLogger("mana-habilidade-notificacao-whatsapp.sender")


# Limites do hub (ADR 2026-06-11 documenta 12 MB de base64)
LIMITE_BYTES_B64 = 12 * 1024 * 1024
CLASSES_VALIDAS = ("conversacional", "transacional", "massa")


class WhatsAppSender:
    """Cliente do hub agente-whatsapp.

    Métodos:
      - send_text(telefone, mensagem) — POST /send-whatsapp
      - send_audio(telefone, mensagem) — POST /send-whatsapp com modo=audio (TTS local no hub)
      - send_pdf(telefone, pdf_bytes, filename) — POST /send-document
      - send_image(telefone, imagem_bytes, caption) — POST /send-image
      - broadcast_text(contatos, template) — POST /send-whatsapp-lista (envio em lote nativo)
      - broadcast_pdf/image(contatos, ...) — loop chamando send_pdf/send_image

    Todos os métodos:
      - Adicionam classe/agente/idempotency_key automaticamente
      - Retornam dict com {sucesso, hub_response, idempotency_key, telefone}
      - Não levantam exceção pra hub 4xx/5xx — retornam sucesso=False com detalhe
    """

    def __init__(
        self,
        hub_url: str,
        hub_key: str,
        agente_nome: str,
        classe_default: str = "transacional",
        timeout_s: int = 30,
    ):
        if not hub_url:
            raise ConfigError("hub_url vazio")
        if not hub_key:
            raise ConfigError("hub_key vazio")
        if not agente_nome:
            raise ConfigError("agente_nome vazio")
        if classe_default not in CLASSES_VALIDAS:
            raise ConfigError(f"classe_default inválida: {classe_default}. Use: {CLASSES_VALIDAS}")
        self.hub_url = hub_url.rstrip("/")
        self.hub_key = hub_key
        self.agente_nome = agente_nome
        self.classe_default = classe_default
        self.timeout_s = timeout_s

    # ---------- Texto ----------

    def send_text(
        self,
        telefone: str,
        mensagem: str,
        classe: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        idempotency_prefix: str = "text",
    ) -> Dict[str, Any]:
        """Envia mensagem de texto via POST /send-whatsapp."""
        return self._enviar_individual(
            endpoint="/send-whatsapp",
            telefone=telefone,
            body={"mensagem": mensagem},
            classe=classe,
            idempotency_key=idempotency_key,
            idempotency_prefix=idempotency_prefix,
            hash_conteudo=mensagem,
        )

    def send_audio(
        self,
        telefone: str,
        mensagem: str,
        voz: Optional[str] = None,
        classe: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        idempotency_prefix: str = "audio",
    ) -> Dict[str, Any]:
        """Envia mensagem como áudio (TTS local no hub). Voz opcional: onyx/nova/etc."""
        body: Dict[str, Any] = {"mensagem": mensagem, "modo": "audio"}
        if voz:
            body["voz"] = voz
        return self._enviar_individual(
            endpoint="/send-whatsapp",
            telefone=telefone,
            body=body,
            classe=classe,
            idempotency_key=idempotency_key,
            idempotency_prefix=idempotency_prefix,
            hash_conteudo=f"audio|{voz or ''}|{mensagem}",
        )

    # ---------- Documento (PDF) ----------

    def send_pdf(
        self,
        telefone: str,
        pdf_bytes: bytes,
        filename: str,
        caption: Optional[str] = None,
        classe: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        idempotency_prefix: str = "pdf",
    ) -> Dict[str, Any]:
        """Envia PDF como anexo via POST /send-document."""
        return self._enviar_documento(
            telefone=telefone,
            binario=pdf_bytes,
            filename=filename,
            caption=caption,
            extension="pdf",
            classe=classe,
            idempotency_key=idempotency_key,
            idempotency_prefix=idempotency_prefix,
        )

    def send_document(
        self,
        telefone: str,
        binario: bytes,
        filename: str,
        extension: str,
        caption: Optional[str] = None,
        classe: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        idempotency_prefix: str = "doc",
    ) -> Dict[str, Any]:
        """Envia qualquer documento (extension explícita)."""
        return self._enviar_documento(
            telefone=telefone,
            binario=binario,
            filename=filename,
            caption=caption,
            extension=extension,
            classe=classe,
            idempotency_key=idempotency_key,
            idempotency_prefix=idempotency_prefix,
        )

    # ---------- Imagem ----------

    def send_image(
        self,
        telefone: str,
        imagem_bytes: bytes,
        extension: str = "png",
        caption: Optional[str] = None,
        classe: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        idempotency_prefix: str = "img",
    ) -> Dict[str, Any]:
        """Envia imagem inline (preview no chat) via POST /send-image."""
        extension = extension.lower().lstrip(".")
        if extension not in ("png", "jpg", "jpeg"):
            raise HubValidation(f"extension inválida: '{extension}'. Use png|jpg|jpeg.")
        b64 = self._b64_com_limite(imagem_bytes)
        tel = normalizar_telefone(telefone)
        idk = idempotency_key or gerar_idempotency_key(
            idempotency_prefix, tel, hashlib.sha256(imagem_bytes).hexdigest()[:8]
        )
        body = {
            "telefone": tel,
            "imagem": b64,
            "extension": extension,
            "classe": classe or self.classe_default,
            "idempotency_key": idk,
            "agente": self.agente_nome,
        }
        if caption:
            body["caption"] = truncate_str(caption, 1024)
        return self._post(endpoint="/send-image", body=body, idempotency_key=idk, telefone=tel)

    # ---------- Broadcast ----------

    def broadcast_text(
        self,
        contatos: List[Any],
        template: str,
        variaveis_por_contato: Optional[Dict[int, dict]] = None,
        classe: Optional[str] = None,
        idempotency_prefix: str = "bcast",
    ) -> List[Dict[str, Any]]:
        """Envia texto em massa usando POST /send-whatsapp-lista do hub.

        Suporta template com {nome} substituído por variaveis_por_contato[contato.id].
        Retorna lista de {telefone, sucesso, idempotency_key}.
        """
        from .helpers import format_template

        classe = classe or self.classe_default
        itens = []
        idks = []
        for contato in contatos:
            tel = normalizar_telefone(getattr(contato, "whatsapp", contato))
            variaveis = {"nome": getattr(contato, "nome", "")}
            if variaveis_por_contato and getattr(contato, "id", None) in variaveis_por_contato:
                variaveis.update(variaveis_por_contato[contato.id])
            msg = format_template(template, variaveis)
            idk = gerar_idempotency_key(idempotency_prefix, tel, msg[:32])
            idks.append(idk)
            itens.append({
                "telefone": tel,
                "mensagem": msg,
                "classe": classe,
                "idempotency_key": idk,
                "agente": self.agente_nome,
            })

        # Tenta lote nativo do hub primeiro (mais eficiente)
        try:
            r = self._post_raw("/send-whatsapp-lista", {"itens": itens})
            resposta_hub = r
        except HubValidation:
            # Fallback: hub não aceita lote — envia individual
            log.warning("hub rejeitou /send-whatsapp-lista, caindo pra individuais")
            resultados = []
            for i, item in enumerate(itens):
                res = self.send_text(
                    telefone=item["telefone"],
                    mensagem=item["mensagem"],
                    classe=classe,
                    idempotency_key=item["idempotency_key"],
                )
                resultados.append(res)
            return resultados

        # Sucesso no lote — monta resposta uniforme
        resultados = []
        for i, item in enumerate(itens):
            resultados.append({
                "telefone": item["telefone"],
                "sucesso": True,
                "idempotency_key": item["idempotency_key"],
                "hub_response": resposta_hub,
                "tipo": "texto",
            })
        return resultados

    def broadcast_pdf(
        self,
        contatos: List[Any],
        pdf_bytes: bytes,
        filename: str,
        caption: Optional[str] = None,
        classe: Optional[str] = None,
        idempotency_prefix: str = "bcast-pdf",
    ) -> List[Dict[str, Any]]:
        """PDF individualizado por contato (hub não tem endpoint de lote pra doc)."""
        resultados = []
        for contato in contatos:
            tel = normalizar_telefone(getattr(contato, "whatsapp", contato))
            r = self.send_pdf(
                telefone=tel,
                pdf_bytes=pdf_bytes,
                filename=filename,
                caption=caption,
                classe=classe,
                idempotency_prefix=idempotency_prefix,
            )
            resultados.append(r)
        return resultados

    def broadcast_image(
        self,
        contatos: List[Any],
        imagem_bytes: bytes,
        extension: str = "png",
        caption: Optional[str] = None,
        classe: Optional[str] = None,
        idempotency_prefix: str = "bcast-img",
    ) -> List[Dict[str, Any]]:
        """Imagem individualizada por contato."""
        resultados = []
        for contato in contatos:
            tel = normalizar_telefone(getattr(contato, "whatsapp", contato))
            r = self.send_image(
                telefone=tel,
                imagem_bytes=imagem_bytes,
                extension=extension,
                caption=caption,
                classe=classe,
                idempotency_prefix=idempotency_prefix,
            )
            resultados.append(r)
        return resultados

    # ---------- Internos ----------

    def _enviar_individual(
        self,
        endpoint: str,
        telefone: str,
        body: Dict[str, Any],
        classe: Optional[str],
        idempotency_key: Optional[str],
        idempotency_prefix: str,
        hash_conteudo: str,
    ) -> Dict[str, Any]:
        tel = normalizar_telefone(telefone)
        if not tel:
            raise HubValidation(f"telefone inválido: '{telefone}'")
        classe = classe or self.classe_default
        if classe not in CLASSES_VALIDAS:
            raise HubValidation(f"classe inválida: {classe}")
        idk = idempotency_key or gerar_idempotency_key(
            idempotency_prefix, tel, hashlib.sha256(hash_conteudo.encode()).hexdigest()[:8]
        )
        body_final = {
            "telefone": tel,
            **body,
            "classe": classe,
            "idempotency_key": idk,
            "agente": self.agente_nome,
        }
        return self._post(endpoint=endpoint, body=body_final, idempotency_key=idk, telefone=tel)

    def _enviar_documento(
        self,
        telefone: str,
        binario: bytes,
        filename: str,
        caption: Optional[str],
        extension: str,
        classe: Optional[str],
        idempotency_key: Optional[str],
        idempotency_prefix: str,
    ) -> Dict[str, Any]:
        b64 = self._b64_com_limite(binario)
        tel = normalizar_telefone(telefone)
        if not tel:
            raise HubValidation(f"telefone inválido: '{telefone}'")
        classe = classe or self.classe_default
        if classe not in CLASSES_VALIDAS:
            raise HubValidation(f"classe inválida: {classe}")
        idk = idempotency_key or gerar_idempotency_key(
            idempotency_prefix, tel, hashlib.sha256(binario).hexdigest()[:8]
        )
        body = {
            "telefone": tel,
            "documento": b64,
            "filename": self._sanitize_filename(filename),
            "extension": extension.lower().lstrip("."),
            "classe": classe,
            "idempotency_key": idk,
            "agente": self.agente_nome,
        }
        if caption:
            body["caption"] = truncate_str(caption, 1024)
        return self._post(endpoint="/send-document", body=body, idempotency_key=idk, telefone=tel)

    def _post(
        self,
        endpoint: str,
        body: Dict[str, Any],
        idempotency_key: str,
        telefone: str,
    ) -> Dict[str, Any]:
        """POST no hub — não levanta pra erros HTTP; retorna sucesso=False."""
        try:
            r = self._post_raw(endpoint, body)
            return {
                "sucesso": True,
                "hub_response": r,
                "idempotency_key": idempotency_key,
                "telefone": telefone,
            }
        except (HubUnauthorized, HubValidation, HubUnavailable) as e:
            log.error("hub retornou erro em %s: %s", endpoint, e)
            return {
                "sucesso": False,
                "erro": str(e),
                "erro_tipo": type(e).__name__,
                "idempotency_key": idempotency_key,
                "telefone": telefone,
            }
        except Exception as e:
            log.exception("erro inesperado no _post %s", endpoint)
            return {
                "sucesso": False,
                "erro": f"erro inesperado: {e}",
                "erro_tipo": "UnknownError",
                "idempotency_key": idempotency_key,
                "telefone": telefone,
            }

    def _post_raw(self, endpoint: str, body: Dict[str, Any]) -> Any:
        """POST cru — levanta HubXxx conforme status. Só use se quiser tratar exceção fora."""
        url = f"{self.hub_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.hub_key,
        }
        try:
            r = requests.post(url, json=body, headers=headers, timeout=self.timeout_s)
        except requests.exceptions.Timeout as e:
            raise HubUnavailable(f"timeout {self.timeout_s}s no hub: {e}") from e
        except requests.exceptions.ConnectionError as e:
            raise HubUnavailable(f"connection error no hub: {e}") from e
        except Exception as e:
            raise SenderError(f"erro no request: {e}") from e

        if r.status_code in (401, 403):
            raise HubUnauthorized(f"hub {r.status_code}: X-API-Key errada ou sem permissão")
        if r.status_code == 400:
            raise HubValidation(f"hub 400: payload inválido — {r.text[:200]}")
        if 500 <= r.status_code < 600:
            raise HubUnavailable(f"hub {r.status_code}: {r.text[:200]}")
        if not (200 <= r.status_code < 300):
            raise SenderError(f"hub {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text[:500]}

    def _b64_com_limite(self, binario: bytes) -> str:
        b64 = base64.b64encode(binario).decode("ascii")
        if len(b64) > LIMITE_BYTES_B64:
            raise PayloadTooLarge(
                f"payload {len(b64)/1024/1024:.1f} MB > limite {LIMITE_BYTES_B64/1024/1024:.0f} MB"
            )
        return b64

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Remove chars perigosos do filename."""
        import re
        clean = re.sub(r"[^\w\-.]+", "_", filename or "documento")
        return clean[:120]  # limite razoável
