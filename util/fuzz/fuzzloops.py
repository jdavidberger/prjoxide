"""
General Utilities for Fuzzing
"""
import asyncio
import concurrent
import logging
import os
import shutil
import signal
import threading
import time
from asyncio import CancelledError
from pathlib import Path
from signal import SIGINT, SIGTERM

import lapie

from collections import defaultdict

from concurrent.futures import ThreadPoolExecutor, Future
from contextlib import contextmanager
from threading import Thread, RLock
import traceback

is_in_loop = False

def jobs():
    if "OXIDE_JOBS" in os.environ:
        jobs = int(os.environ["OXIDE_JOBS"])
    else:
        jobs = 4
    return jobs

@contextmanager
def Executor(executor=None):
    cleanup = executor is None
    if executor is None:
        executor = ThreadPoolExecutor(jobs())
    try:
        yield executor
    finally:
        if cleanup:
            executor.shutdown(wait=True)


def parallel_foreach(items, func, jobs = None):
    """
    Run a function over a list of values, running a number of jobs
    in parallel. OXIDE_JOBS should be set to the number of jobs to run,
    defaulting to 4.
    """
    if jobs is None:
        if "OXIDE_JOBS" in os.environ:
            jobs = int(os.environ["OXIDE_JOBS"])
        else:
            jobs = 4

    items_queue = list(items)
    items_lock = RLock()

    exception = None
    print(f"Starting loop with {exception} jobs")

    global is_in_loop
    is_in_loop = True
    def runner():
        nonlocal exception

        try:            
            while True:
                with items_lock:
                    if len(items_queue) == 0:
                        return
                    item = items_queue[0]
                    items_queue.pop(0)
                    print(f"{len(items_queue)} jobs remaining")

                func(item)
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            
            exception = e
            with items_lock:
                items_queue.clear()

    threads = [Thread(target=runner) for i in range(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if exception is not None:
        raise exception
    is_in_loop = False

def gather_futures(futures, name = None):
    """
    Returns a Future that completes when all input futures complete.
    Result is a list of results in the same order.
    """
    out = Future()
    n = len(futures)
    results = [None] * n
    remaining = n
    lock = threading.Lock()

    def _done(i, fut):
        nonlocal remaining
        try:
            if hasattr(fut, "result"):
                res = fut.result()
            else:
                res = fut
        except Exception as e:
            # fail fast: propagate first exception
            with lock:
                if not out.done():
                    out.set_exception(e)
            return

        with lock:
            if out.done():
                return
            results[i] = res
            remaining -= 1
            if remaining == 0:
                out.set_result(results)

    executor = None
    for i, fut in enumerate(futures):
        if hasattr(fut, 'executor'):
            executor = fut.executor
        if hasattr(fut, "result"):
            fut.add_done_callback(lambda f, i=i: _done(i, f))
        else:
            _done(i, fut)

    if executor is not None:
        executor.register_future(out)

    if name is not None:
        out.name = name

    if n == 0:
        out.set_result([])

    return out

def chain(future, func, name = None, *args, **kwargs):
    if isinstance(future, list):
        future = gather_futures(future)

    fut = Future()

    def _done(f):
        r = None
        try:
            r = f.result()
            fut.set_result(func(r, *args, **kwargs))
        except BaseException as e:
            logging.error(f"Encountered exception while calling {func} with {r} {args} {kwargs}")
            traceback.print_exception(e)
            try:
                raise RuntimeError(f"Encountered exception while calling {func} with {r} {args} {kwargs}") from e
            except BaseException as f:
                fut.set_exception(f)

        except:
            fut.set_exception(Exception("Unknown exception in future"))

    future.add_done_callback(_done)
    if hasattr(future, 'executor'):
        future.executor.register_future(fut)

    if name is not None:
        fut.name = name

    return fut

class AsyncExecutor:
    def __init__(self):
        self.futures = []
        self.lock = RLock()
        self.loop = asyncio.get_running_loop()

    def submit(self, f, *args, **kwargs):
        future = self.loop.run_in_executor(None, lambda args=args,kwargs=kwargs: f(*args, **kwargs))
        future.name = f.__name__
        self.register_future(future)
        return future

    def register_future(self, future):
        future.executor = self
        with self.lock:
            self.futures.append(future)

    def iterate_futures(self):
        with self.lock:
            local_futures = self.futures
            self.futures = []

        new_futures = []
        for f in local_futures:
            yield f
            if not f.done():
                new_futures.append(f)

        with self.lock:
            self.futures.extend(new_futures)

    def busy(self):
        return len(self.futures) > 0

    def task_count(self):
        return len(self.futures)

def FuzzerAsyncMain(f):
    from fuzzconfig import FuzzConfig

    import rich
    import rich.console
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    console = rich.console.Console()
    import sys
    sys.stdout = console.file

    from rich.logging import RichHandler

    LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()

    logging.basicConfig(
        level=LOGLEVEL,
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )


    start_time = time.time()

    async def start(f):
        async_executor = None

        main_task = asyncio.current_task()
        int_count = 0
        def sighandler(sig, frame):
            nonlocal int_count
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! SIG HANDLER !!!!!!!!!!!!!!!!!!!!!!! {int_count}")
            if int_count > 1:
                sys.exit(-1)

            main_task.cancel()
            int_count = int_count + 1

        for sig in [SIGINT, SIGTERM]:
            signal.signal(sig, sighandler)

        try:
            def status_panel(status: str) -> Panel:
                return Panel(
                    f"[bold cyan]{status}[/bold cyan]",
                    title="Status",
                    border_style="blue",
                    height=3,
                )

            async def ui(async_executor):
                with Live(status_panel(""), refresh_per_second=10, console=console) as live:
                    finished_tasks = 0

                    while async_executor.busy() or not task.done():
                        histogram = defaultdict(int)

                        def process_future(fut):
                            nonlocal finished_tasks

                            name = "anon"
                            if hasattr(fut, "name"):
                                name = fut.name
                            elif hasattr(fut, "get_stack"):
                                fn = fut.get_stack()[-1].f_code.co_name
                                if fn != "ui" and fn != "start":
                                    ln = fut.get_stack()[-1].f_lineno
                                    name = f"{fn}:{ln}"
                                else:
                                    name = None

                            if name is not None:
                                histogram[name] = histogram[name] + 1

                            if fut.done():
                                if fut.exception() is not None:
                                    all_exceptions.append(fut.exception())
                                else:
                                    finished_tasks = finished_tasks + 1
                                    fut.result()

                        for fut in async_executor.iterate_futures(): process_future(fut)
                        for fut in asyncio.all_tasks(): process_future(fut)

                        width = shutil.get_terminal_size().columns
                        text = f"{list(histogram.items())} {async_executor.task_count()} {finished_tasks} finished {len(all_exceptions)} errors, built/cached {FuzzConfig.radiant_builds}/{FuzzConfig.radiant_cache_hits} tool queries {lapie.run_with_udb_cnt} {int(time.time() - start_time)}s"
                        # print("{text:>{width}}".format(text=text, width=width), end="\r")
                        live.update(status_panel(text))
                        await asyncio.sleep(.1)


            with Executor() as executor:
                try:
                    asyncio.get_running_loop().set_default_executor(executor)

                    async_executor = AsyncExecutor()

                    all_exceptions = []

                    ui_task = asyncio.create_task(ui(async_executor))
                    task = asyncio.create_task(f(async_executor))

                    await asyncio.gather(task, ui_task)
                except CancelledError:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise


        except KeyboardInterrupt:
            logging.warning("Keyboard interrupt")
        except CancelledError:
            if int_count > 1:
                sys.exit(-1)
            int_count = int_count + 1


        if len(all_exceptions):
            logging.error(f"Encountered the following {len(all_exceptions)} errors:")
            for e in all_exceptions:
                traceback.print_exception(e)

        logging.info(f"Processed {FuzzConfig.radiant_builds}/{FuzzConfig.radiant_cache_hits} bitfiles in {time.time() - start_time} seconds. Skipped {FuzzConfig.delta_skips} solves due to existing .delta files")

    asyncio.run(start(f))



def FuzzerMain(f):
    async def async_main(executor):
        return f(executor)

    FuzzerAsyncMain(async_main)