"""Exceções da habilidade — todas herdam de NotificationError."""


class NotificationError(Exception):
    """Base — qualquer erro da habilidade herda daqui."""


class ConfigError(NotificationError):
    """Env var faltando, URL inválida, config inconsistente."""


class RepoError(NotificationError):
    """Erro no CRUD de contatos (Postgres)."""


class DDLError(NotificationError):
    """Erro no init_schema (Postgres)."""


class SenderError(NotificationError):
    """Erro genérico no envio (fallback quando não classifica)."""


class HubUnauthorized(SenderError):
    """Hub retornou 401/403 — X-API-Key errada."""


class HubValidation(SenderError):
    """Hub retornou 400 — payload inválido (telefone, formato, etc)."""


class HubUnavailable(SenderError):
    """Hub retornou 5xx ou timeout — não é culpa do payload."""


class PayloadTooLarge(SenderError):
    """Documento ou imagem > 12 MB em base64."""


class ScheduleError(NotificationError):
    """Erro no agendamento (APScheduler)."""
