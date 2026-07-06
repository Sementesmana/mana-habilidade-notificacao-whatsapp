"""mana-habilidade-notificacao-whatsapp
==========================================

Cadastro de contatos + agendamento cron + envio de notificações WhatsApp
(texto, PDF, imagem) via hub agente-whatsapp.

Consolida padrão fan-out DM usado em 4 agentes Maná (gestor-comercial,
gestor-estoque, premiacao, comercio-revendas).

Uso mínimo:

    from mana_habilidade_notificacao_whatsapp import (
        ContatoDDL, ContatoRepo, WhatsAppSender, NotificationScheduler,
    )

    # Setup (1x no startup)
    ddl = ContatoDDL(DATABASE_URL, schema="comercializacao")
    ddl.init_schema()

    repo = ContatoRepo(DATABASE_URL, schema="comercializacao")
    sender = WhatsAppSender(
        hub_url=AGENTE_WHATSAPP_URL,
        hub_key=AGENTE_WHATSAPP_API_KEY,
        agente_nome="comercio-revendas",
    )

    # CRUD
    repo.criar(nome="João", whatsapp="+5562999999999", tags=["revendedores"])

    # Envio
    sender.send_text(telefone, "Olá!", classe="transacional")
    sender.send_pdf(telefone, pdf_bytes, filename="relatorio.pdf")
    sender.send_image(telefone, png_bytes, caption="Meta semanal")

    # Broadcast (usa /send-whatsapp-lista nativo do hub)
    contatos = repo.listar_ativos(tags=["revendedores"])
    sender.broadcast_text(contatos, "Olá {nome}, ...")

    # Cron
    scheduler = NotificationScheduler(sender=sender, repo=repo)
    scheduler.agendar_cron("meta-semanal", "0 8 * * MON", callback=fn)
    scheduler.start()

Ver SKILL.md pra referência completa.
"""

__version__ = "0.1.0"

from .contato import Contato, ContatoRepo
from .ddl import ContatoDDL
from .exceptions import (
    ConfigError,
    DDLError,
    HubUnauthorized,
    HubUnavailable,
    HubValidation,
    NotificationError,
    PayloadTooLarge,
    RepoError,
    ScheduleError,
    SenderError,
)
from .scheduler import NotificationScheduler
from .sender import WhatsAppSender

__all__ = [
    # Versão
    "__version__",
    # Classes principais
    "ContatoDDL",
    "ContatoRepo",
    "Contato",
    "WhatsAppSender",
    "NotificationScheduler",
    # Exceções
    "NotificationError",
    "ConfigError",
    "DDLError",
    "RepoError",
    "SenderError",
    "HubUnauthorized",
    "HubValidation",
    "HubUnavailable",
    "PayloadTooLarge",
    "ScheduleError",
]
