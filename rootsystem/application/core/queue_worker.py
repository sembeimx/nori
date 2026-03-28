import asyncio
import importlib
import signal
from datetime import timedelta
from tortoise.timezone import now
from core.logger import get_logger

_log = get_logger('queue')
MAX_ATTEMPTS = 5
_should_exit = False

def _handle_exit(sig, frame):
    global _should_exit
    _log.info("Shutdown signal received, finishing current job...")
    _should_exit = True

async def execute_payload(payload: dict):
    mod_path, func_name = payload['func'].split(':')
    module = importlib.import_module(mod_path)
    func = getattr(module, func_name)
    if asyncio.iscoroutinefunction(func):
        await func(*payload.get('args', []), **payload.get('kwargs', {}))
    else:
        func(*payload.get('args', []), **payload.get('kwargs', {}))

async def work(queue_name: str = 'default', sleep: int = 3):
    from models.job import Job
    global _should_exit
    
    # Register signals for graceful shutdown
    try:
        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)
    except ValueError:
        # Signal only works in main thread
        pass

    _log.info("Queue worker started on: %s (Max attempts: %d)", queue_name, MAX_ATTEMPTS)

    while not _should_exit:
        # 1. Fetch a job that is available and not reserved
        job = await Job.filter(
            queue=queue_name, 
            reserved_at__isnull=True, 
            available_at__lte=now(),
            failed_at__isnull=True
        ).first()

        if not job:
            await asyncio.sleep(sleep)
            continue

        # 2. Atomic Reservation: Ensure no other worker grabbed it
        affected = await Job.filter(id=job.id, reserved_at__isnull=True).update(reserved_at=now())
        if affected == 0:
            continue # Someone else got it

        try:
            await execute_payload(job.payload)
            await job.delete()
        except Exception as e:
            job.attempts += 1
            job.reserved_at = None
            
            if job.attempts >= MAX_ATTEMPTS:
                job.failed_at = now()
                _log.error("Job %d failed permanently after %d attempts", job.id, MAX_ATTEMPTS)
            else:
                # Exponential backoff: 15s, 4m, 20m, 1h, 3h...
                wait_seconds = (job.attempts ** 4) * 15
                job.available_at = now() + timedelta(seconds=wait_seconds)
                _log.warning("Job %d failed (attempt %d). Retrying in %ds", job.id, job.attempts, wait_seconds)
            
            await job.save()
            await asyncio.sleep(sleep)

    _log.info("Worker stopped cleanly.")
