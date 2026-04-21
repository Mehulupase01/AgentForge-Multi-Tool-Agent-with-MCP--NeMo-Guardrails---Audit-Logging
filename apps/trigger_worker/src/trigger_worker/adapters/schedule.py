from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger


def cron_trigger(expression: str) -> CronTrigger:
    return CronTrigger.from_crontab(expression)
