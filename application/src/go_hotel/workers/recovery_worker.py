import asyncio
import time
from go_hotel.services.recovery import recovery_worker

async def main():
    while True:
        result = await recovery_worker.run_once()
        if result["scanned"] == 0:
            await asyncio.sleep(1.0)

if __name__ == "__main__":
    asyncio.run(main())
