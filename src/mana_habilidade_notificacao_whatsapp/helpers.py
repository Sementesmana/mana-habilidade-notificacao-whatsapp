"""Helpers puros — sem side effects, sem I/O."""
import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional


_RE_SO_DIGITOS = re.compile(r"\D+")


def so_digitos(s: Any) -> str:
    """Remove tudo que não é dígito. `None`/vazio → ''."""
    if not s:
        return ""
    return _RE_SO_DIGITOS.sub("", str(s))


def normalizar_telefone(telefone: Any) -> str:
    """Normaliza telefone brasileiro pra formato Z-API (55 + DDD + número).

    Aceita:
      - "62999999999" → "5562999999999"
      - "5562999999999" → "5562999999999"
      - "+55 62 99999-9999" → "5562999999999"
      - "120363XYZ-group" (grupo Z-API) → "120363XYZ-group" (passa direto)
      - "abc@g.us" (grupo Z-API v2) → "abc@g.us" (passa direto)
    """
    if not telefone:
        return ""
    s = str(telefone).strip()
    # Grupos Z-API — não normaliza
    if s.endswith("-group") or s.endswith("@g.us"):
        return s
    d = so_digitos(s)
    if not d:
        return ""
    # Se já começa com 55 e tem 12-13 dígitos, ok
    if d.startswith("55") and 12 <= len(d) <= 13:
        return d
    # Se tem 10 ou 11 dígitos (DDD + número), prepend 55
    if 10 <= len(d) <= 11:
        return "55" + d
    return d


def gerar_idempotency_key(prefixo: str, telefone: str, extra: str = "") -> str:
    """Gera idempotency_key determinístico pra evitar envio duplicado.

    Formato: <prefixo>:<hash8>
    onde hash8 = primeiros 8 chars do sha256(prefixo + telefone + extra).
    """
    base = f"{prefixo}|{normalizar_telefone(telefone)}|{extra}"
    h = hashlib.sha256(base.encode("utf-8")).hexdigest()[:8]
    return f"{prefixo}:{h}"


def now_utc_iso() -> str:
    """Timestamp ISO 8601 em UTC — usado em logs e default de created_at."""
    return datetime.now(timezone.utc).isoformat()


def truncate_str(s: Optional[str], max_len: int) -> str:
    """Trunca string preservando primeiros N chars. Adiciona `…` se cortou."""
    if not s:
        return ""
    s = str(s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def format_template(template: str, variaveis: dict) -> str:
    """Preenche template com {chave} — silencioso pra chaves faltantes.

    Ex: format_template("Olá {nome}", {"nome": "João"}) → "Olá João"
    """
    if not template:
        return ""
    if not variaveis:
        return template
    try:
        return template.format_map(_SilentDict(variaveis))
    except Exception:
        return template


class _SilentDict(dict):
    """dict que retorna '{chave}' se a chave não existe — pra format_map não crashar."""

    def __missing__(self, key):
        return "{" + key + "}"
