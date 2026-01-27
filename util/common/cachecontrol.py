import hashlib
import os
import pickle

import cachier
from sqlalchemy import create_engine

from database import get_cache_dir

radiant_version = os.environ.get("RADIANTVERSION", None)
engine = create_engine(f'sqlite:///{get_cache_dir()}/cache.db')
#@cachier.cachier(backend="sql", sql_engine=engine, cache_dir=database.get_cache_dir(), pickle_reload=False,separate_files=True)

def cache_fn():
    RADIANT_DIR = os.environ.get("RADIANTDIR")

    def hashfunc(args, kwds):
        # Sort the kwargs to ensure consistent ordering
        kwds["RADIANT_DIR"] = RADIANT_DIR
        kwds["RADIANT_VERSION"] = radiant_version

        sorted_kwargs = sorted(kwds.items())
        # Serialize args and sorted_kwargs using pickle or similar
        serialized = pickle.dumps((args, sorted_kwargs))
        # Create a hash of the serialized data
        return hashlib.sha256(serialized).hexdigest()

    return cachier.cachier(hash_func=hashfunc, backend="sql", sql_engine=engine, pickle_reload=False,separate_files=True, wait_for_calc_timeout=5)