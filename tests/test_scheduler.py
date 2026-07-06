"""Testes do NotificationScheduler."""
import pytest
from mana_habilidade_notificacao_whatsapp import NotificationScheduler
from mana_habilidade_notificacao_whatsapp.exceptions import ScheduleError


class TestScheduler:
    def test_agendar_cron_ok(self):
        s = NotificationScheduler()
        called = []
        job_id = s.agendar_cron("teste", "0 8 * * MON", callback=lambda: called.append(1))
        assert job_id == "teste"
        assert "teste" in s._jobs_agendados

    def test_agendar_cron_expressao_invalida(self):
        s = NotificationScheduler()
        with pytest.raises(ScheduleError):
            s.agendar_cron("teste", "isso não é cron", callback=lambda: None)

    def test_agendar_cron_nome_vazio(self):
        s = NotificationScheduler()
        with pytest.raises(ScheduleError):
            s.agendar_cron("", "0 8 * * MON", callback=lambda: None)

    def test_agendar_cron_callback_nao_callable(self):
        s = NotificationScheduler()
        with pytest.raises(ScheduleError):
            s.agendar_cron("t", "0 8 * * MON", callback="não é função")

    def test_agendar_intervalo(self):
        s = NotificationScheduler()
        job_id = s.agendar_intervalo("intervalo", 60, callback=lambda: None)
        assert job_id == "intervalo"

    def test_agendar_intervalo_segundos_negativo(self):
        s = NotificationScheduler()
        with pytest.raises(ScheduleError):
            s.agendar_intervalo("t", -1, callback=lambda: None)

    def test_remover_job(self):
        s = NotificationScheduler()
        s.agendar_cron("t", "0 8 * * MON", callback=lambda: None)
        assert s.remover("t") is True
        assert s.remover("nao-existe") is False

    def test_listar_jobs(self):
        s = NotificationScheduler()
        s.agendar_cron("a", "0 8 * * MON", callback=lambda: None)
        s.agendar_cron("b", "0 12 * * *", callback=lambda: None)
        jobs = s.listar_jobs()
        ids = {j["id"] for j in jobs}
        assert {"a", "b"}.issubset(ids)

    def test_start_e_shutdown(self):
        s = NotificationScheduler()
        s.start()
        assert s._started is True
        s.shutdown(wait=False)
        assert s._started is False

    def test_start_duplo_nao_quebra(self):
        s = NotificationScheduler()
        s.start()
        s.start()  # noop, warn
        assert s._started is True
        s.shutdown(wait=False)


class TestSchedulerImportGate:
    def test_apscheduler_ausente_config_error(self, monkeypatch):
        # Simula APScheduler não instalado
        import sys
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("apscheduler"):
                raise ImportError("no apscheduler")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        from mana_habilidade_notificacao_whatsapp.exceptions import ConfigError
        with pytest.raises(ConfigError):
            NotificationScheduler()
