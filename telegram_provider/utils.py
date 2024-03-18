import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Coroutine


async def infinite_retry_on_error(fn: "Coroutine", *args, **kwargs) -> "Coroutine":
    while True:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            print(e)
            await asyncio.sleep(10)
