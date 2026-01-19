"""
General Utilities for Fuzzing
"""
import asyncio
import os
from threading import Thread, RLock
import traceback

def parallel_foreach(items, func):
    """
    Run a function over a list of values, running a number of jobs
    in parallel. OXIDE_JOBS should be set to the number of jobs to run,
    defaulting to 4.
    """
    if "OXIDE_JOBS" in os.environ:
        jobs = int(os.environ["OXIDE_JOBS"])
    else:
        jobs = 4
    items_queue = list(items)
    items_lock = RLock()

    exception = None
    print(f"Starting loop with {exception} jobs")
    
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
