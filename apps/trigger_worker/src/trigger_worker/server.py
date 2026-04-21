from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from trigger_worker.adapters.schedule import cron_trigger


API_URL = os.environ.get("AGENTFORGE_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("TRIGGER_WORKER_INTERNAL_API_KEY") or os.environ.get("AGENTFORGE_API_KEY", "dev-key")


class TriggerWorker:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()

    async def refresh_from_api(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{API_URL}/api/v1/triggers",
                headers={"X-API-Key": API_KEY},
            )
            response.raise_for_status()
            triggers = response.json().get("data", [])

        self.scheduler.remove_all_jobs()
        for trigger in triggers:
            if trigger["source"] != "schedule" or trigger["status"] != "enabled":
                continue
            cron = trigger["config"].get("cron")
            if not cron:
                continue
            self.scheduler.add_job(
                self.fire_trigger,
                cron_trigger(cron),
                args=[trigger["id"]],
                id=trigger["id"],
                replace_existing=True,
            )

    async def fire_trigger(self, trigger_id: str) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{API_URL}/api/v1/triggers/internal/fire",
                json={"trigger_id": trigger_id},
                headers={"X-API-Key": API_KEY},
            )


worker = TriggerWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker.scheduler.start()
    try:
        await worker.refresh_from_api()
    except Exception:
        pass
    try:
        yield
    finally:
        worker.scheduler.shutdown(wait=False)


app = FastAPI(title="AgentForge Trigger Worker", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "scheduler_running": worker.scheduler.running,
        "jobs": len(worker.scheduler.get_jobs()),
    }
