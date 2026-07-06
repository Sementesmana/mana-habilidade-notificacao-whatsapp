"""NotificationScheduler — wrapper APScheduler pra cron de notificações."""
import logging
from typing import Any, Callable, Dict, List, Optional

from .exceptions import ConfigError, ScheduleError

log = logging.getLogger("mana-habilidade-notificacao-whatsapp.scheduler")


class NotificationScheduler:
    """Wrapper simples do APScheduler pra jobs de notificação.

    Uso típico:
        scheduler = NotificationScheduler(sender=..., repo=...)
        scheduler.agendar_cron("meta-semanal", "0 8 * * MON", callback=lambda: ...)
        scheduler.start()

    Callback recebe o dict de contexto que o consumidor definir. O scheduler
    não impõe formato — só chama.

    Persistência: por padrão jobstore em memória. Pra persistir jobs entre
    restarts, use jobstores parametrizado (postgres/mongo/etc).
    """

    def __init__(
        self,
        sender=None,
        repo=None,
        jobstores: Optional[Dict] = None,
        executors: Optional[Dict] = None,
        job_defaults: Optional[Dict] = None,
        timezone: str = "America/Sao_Paulo",
    ):
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as e:
            raise ConfigError(
                "APScheduler não instalado. Adicione 'APScheduler>=3.10' no requirements."
            ) from e

        self.sender = sender
        self.repo = repo
        self._CronTrigger = CronTrigger
        self._jobs_agendados: Dict[str, Any] = {}

        default_defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
        if job_defaults:
            default_defaults.update(job_defaults)

        kwargs = {
            "timezone": timezone,
            "job_defaults": default_defaults,
        }
        if jobstores:
            kwargs["jobstores"] = jobstores
        if executors:
            kwargs["executors"] = executors

        self._scheduler = BackgroundScheduler(**kwargs)
        self._started = False

    def agendar_cron(
        self,
        nome: str,
        cron_expression: str,
        callback: Callable,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        replace_existing: bool = True,
    ) -> str:
        """Agenda job por expressão cron (formato: 'min hora dia mes dow').

        Ex: '0 8 * * MON' → toda segunda 08:00 no timezone do scheduler.
        Retorna job_id (mesmo que 'nome').
        """
        if not nome or not nome.strip():
            raise ScheduleError("nome vazio")
        if not cron_expression or not cron_expression.strip():
            raise ScheduleError("cron_expression vazia")
        if not callable(callback):
            raise ScheduleError(f"callback não é callable: {callback}")

        try:
            trigger = self._CronTrigger.from_crontab(cron_expression, timezone=self._scheduler.timezone)
        except Exception as e:
            raise ScheduleError(f"cron_expression inválida '{cron_expression}': {e}") from e

        try:
            job = self._scheduler.add_job(
                func=callback,
                trigger=trigger,
                id=nome,
                args=args or [],
                kwargs=kwargs or {},
                replace_existing=replace_existing,
            )
            self._jobs_agendados[nome] = job
            log.info("job cron agendado: %s → %s", nome, cron_expression)
            return job.id
        except Exception as e:
            raise ScheduleError(f"falha ao agendar '{nome}': {e}") from e

    def agendar_intervalo(
        self,
        nome: str,
        segundos: int,
        callback: Callable,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        replace_existing: bool = True,
    ) -> str:
        """Agenda job por intervalo em segundos."""
        if segundos <= 0:
            raise ScheduleError(f"segundos deve ser > 0, recebido: {segundos}")
        try:
            job = self._scheduler.add_job(
                func=callback,
                trigger="interval",
                seconds=segundos,
                id=nome,
                args=args or [],
                kwargs=kwargs or {},
                replace_existing=replace_existing,
            )
            self._jobs_agendados[nome] = job
            log.info("job intervalo agendado: %s → cada %ds", nome, segundos)
            return job.id
        except Exception as e:
            raise ScheduleError(f"falha ao agendar intervalo '{nome}': {e}") from e

    def remover(self, nome: str) -> bool:
        """Remove job. Retorna True se removeu, False se não existia."""
        try:
            self._scheduler.remove_job(nome)
            self._jobs_agendados.pop(nome, None)
            log.info("job removido: %s", nome)
            return True
        except Exception:
            return False

    def pausar(self, nome: str) -> bool:
        try:
            self._scheduler.pause_job(nome)
            return True
        except Exception:
            return False

    def retomar(self, nome: str) -> bool:
        try:
            self._scheduler.resume_job(nome)
            return True
        except Exception:
            return False

    def listar_jobs(self) -> List[Dict[str, Any]]:
        """Lista jobs ativos com próxima execução."""
        return [
            {
                "id": j.id,
                "nome": j.id,
                "trigger": str(j.trigger),
                "proximo_run": (getattr(j, "next_run_time", None).isoformat() if getattr(j, "next_run_time", None) else None),
            }
            for j in self._scheduler.get_jobs()
        ]

    def start(self) -> None:
        """Inicia o scheduler. Chame no startup do agente."""
        if self._started:
            log.warning("scheduler já iniciado")
            return
        self._scheduler.start()
        self._started = True
        log.info("scheduler iniciado (timezone=%s)", self._scheduler.timezone)

    def shutdown(self, wait: bool = False) -> None:
        """Para o scheduler. Chame no shutdown do agente."""
        if not self._started:
            return
        self._scheduler.shutdown(wait=wait)
        self._started = False
        log.info("scheduler parado")
