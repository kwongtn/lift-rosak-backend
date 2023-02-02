import argparse
import inspect
import time
from typing import Any, Callable

argParser = argparse.ArgumentParser()
argParser.add_argument("-f", "--file", help="Input filename.")
args = argParser.parse_args()
INPUT_FILENAME: str = args.file
FILENAME = INPUT_FILENAME.split("/")[-1]
FILENAME = ""

sleep_time = 5
chunk_size = int(1e5)


def wrap_errors(
    fn: Callable[[Any], Any],
    *args,
    debug_prefix="",
    **kwargs,
):
    global sleep_time

    while True:
        try:
            argspec = inspect.getfullargspec(fn)

            if "debug_prefix" in getattr(
                argspec, "args", []
            ) or "debug_prefix" in getattr(argspec, "kwargs", []):
                fn_return = fn(debug_prefix=debug_prefix, *args, **kwargs)

            else:
                fn_return = fn(*args, **kwargs)

            sleep_time = 5

            return fn_return

        except Exception as e:
            print(e)
            print(
                f"{FILENAME} ❗ {debug_prefix} Error, retrying in {sleep_time} seconds..."
            )
            time.sleep(sleep_time)
            sleep_time += 5

            continue
