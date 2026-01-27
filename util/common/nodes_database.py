import logging
import sqlite3
from threading import RLock


class NodesDatabase:
    _dbs = {}
    _lock = RLock()

    @staticmethod
    def get(device):
        with NodesDatabase._lock:
            if device not in NodesDatabase._dbs:
                NodesDatabase._dbs[device] = NodesDatabase(device)
            return NodesDatabase._dbs[device]

    def __init__(self, device):
        import database

        self.db_path = f"{database.get_cache_dir()}/{device}-nodes.sqlite"
        logging.info(f"Opening node database at {self.db_path}")

        self.device = device
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.lock = RLock()
        self.init_db()

    def init_db(self):
        with self.lock:
            conn = self.conn
            conn.execute("PRAGMA foreign_keys = ON")
            cur = conn.cursor()

            cur.execute("""
    CREATE TABLE IF NOT EXISTS nodes (
        id   INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        has_full_data INTEGER NOT NULL DEFAULT 0 CHECK (has_full_data IN (0, 1))
    );
            """)

            # PIPs table:
            # from_wire and to_wire are node IDs
            # bidir = 0 (unidirectional) or 1 (bidirectional)
            cur.execute("""
    CREATE TABLE IF NOT EXISTS pips (
        from_id INTEGER NOT NULL,
        to_id   INTEGER NOT NULL,
        bidir INTEGER NOT NULL CHECK (bidir IN (0,1)),
        jumpwire INTEGER NOT NULL CHECK (jumpwire IN (0,1)) DEFAULT 0,
        flags INTEGER NOT NULL DEFAULT 0,
        buffertype TEXT NOT NULL DEFAULT "",
        PRIMARY KEY (from_id, to_id),
        FOREIGN KEY (from_id) REFERENCES nodes(id),
        FOREIGN KEY (to_id)   REFERENCES nodes(id)
    ) WITHOUT ROWID;
            """)

            try:
                cur.execute("ALTER TABLE pips ADD COLUMN jumpwire INTEGER")
            except sqlite3.OperationalError as e:
                pass

            cur.execute("""
    CREATE TEMP TABLE IF NOT EXISTS tmp_node_names (
        name TEXT PRIMARY KEY
    );
            """)

            cur.execute("""
    CREATE TEMP TABLE IF NOT EXISTS tmp_node_ids (
        id   INTEGER PRIMARY KEY
    );            
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                id   INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                x    INTEGER NOT NULL,
                y    INTEGER NOT NULL
            );
            """)

            cur.execute("""
CREATE TABLE IF NOT EXISTS site_pins (
    site_id INTEGER NOT NULL,
    pin_name TEXT NOT NULL,
    node_id INTEGER NOT NULL,

    PRIMARY KEY (site_id, pin_name),

    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES nodes(id)
) WITHOUT ROWID;
                        """)

            conn.commit()

    def _populate_tmp(self, cur, type, values):
        cur.execute(f"DELETE FROM tmp_node_{type}s")

        cur.executemany(
            f"INSERT INTO tmp_node_{type}s ({type}) VALUES (?)",
            ((n,) for n in values)
        )

    def get_node_ids(self, names):
        conn = self.conn
        cur = conn.cursor()
        self._populate_tmp(cur, "name", names)

        cur.executemany(
            "INSERT OR IGNORE INTO nodes (name) VALUES (?)",
            ((ni,) for ni in names)
        )

        cur.execute(
            f"SELECT id, name FROM nodes where name IN (SELECT name from tmp_node_names)",
        )

        id_to_name = dict(cur.fetchall())
        name_to_id = {v: k for k, v in id_to_name.items()}
        return name_to_id

    def get_jumpwires(self):
        conn = self.conn
        cur = conn.cursor()

        cur.execute(f"""
            SELECT n1.name, n2.name, p.bidir, p.flags, p.buffertype
            FROM pips p
            JOIN nodes n1 ON n1.id = p.from_id
            JOIN nodes n2 ON n2.id = p.to_id
            WHERE jumpwire = 1
        """)

        for from_name, to_name, bidir, flags, bt in cur.fetchall():
            yield from_name, to_name

    def insert_jumpwires(self, jumpwires):
        conn = self.conn
        cur = conn.cursor()

        touched_names = set([w for ni in jumpwires for w in ni])

        cur.executemany(
            "INSERT OR IGNORE INTO nodes (name) VALUES (?)",
            ((ni,) for ni in touched_names)
        )

        self._populate_tmp(cur, "name", touched_names)

        cur.execute(
            f"SELECT id, name FROM nodes WHERE name IN (SELECT name from tmp_node_names)"
        )
        id_to_name = dict(cur.fetchall())
        name_to_id = {v: k for k, v in id_to_name.items()}

        cur.executemany(
            """
            INSERT OR IGNORE INTO pips (from_id, to_id, bidir, flags, buffertype) VALUES (?, ?, ?, ?, ?)
            """,
            [(name_to_id[j[0]], name_to_id[j[1]], 0, -1, "") for j in jumpwires]
        )

        cur.executemany(
            """
            UPDATE pips 
            SET jumpwire = 1
            WHERE from_id = ? AND to_id = ?
            """,
            [(name_to_id[j[0]], name_to_id[j[1]]) for j in jumpwires]
        )
        print("jmp", len(jumpwires))

        conn.commit()

    def get_node_data(self, names):
        from lapie import NodeInfo, PipInfo

        with self.lock:
            conn = self.conn
            cur = conn.cursor()

            self._populate_tmp(cur, "name", names)

            cur.execute(
                f"SELECT id, name FROM nodes WHERE has_full_data = 1 and name IN (SELECT name from tmp_node_names)",
            )
            id_to_name = dict(cur.fetchall())
            name_to_id = {v:k for k,v in id_to_name.items()}

            # Prepare result dict
            result = {name: NodeInfo(name) for name in name_to_id}

            self._populate_tmp(cur, "id", list(id_to_name.keys()))
            # ---- Downhill PIPs ----
            cur.execute(f"""
                SELECT p.from_id, n2.name, p.bidir, p.flags, p.buffertype
                FROM pips p
                JOIN nodes n2 ON n2.id = p.to_id
                WHERE p.from_id IN (SELECT id from tmp_node_ids)
            """)

            for from_id, to_name, bidir, flags, bt in cur.fetchall():
                from_name = id_to_name[from_id]
                result[from_name].downhill_pips.append(
                    PipInfo(from_name, to_name,
                            is_bidi=bool(bidir),
                            flags=flags,
                            buffertype=bt)
                )

            # ---- Uphill PIPs ----
            cur.execute(f"""
                SELECT p.to_id, n1.name, p.bidir, p.flags, p.buffertype
                FROM pips p
                JOIN nodes n1 ON n1.id = p.from_id
                WHERE p.to_id IN (SELECT id from tmp_node_ids)
            """)

            for to_id, from_name, bidir, flags, bt in cur.fetchall():
                to_name = id_to_name[to_id]
                result[to_name].uphill_pips.append(
                    PipInfo(from_name, to_name,
                            is_bidi=bool(bidir),
                            flags=flags,
                            buffertype=bt)
                )

        return result

    def insert_nodeinfos(self, nodeinfos):
        with self.lock:
            conn = self.conn
            cur = conn.cursor()

            touched_names = set([w for ni in nodeinfos for p in ni.pips() for w in [p.to_wire, p.from_wire]]) | set([n.name for n in nodeinfos])

            # 1. Insert all nodes
            cur.executemany(
                "INSERT OR IGNORE INTO nodes (name) VALUES (?)",
                ((ni,) for ni in touched_names)
            )

            self._populate_tmp(cur, "name", {n.name for n in nodeinfos})

            cur.execute(
                f"""
                    UPDATE nodes
                    SET has_full_data = 1
                    WHERE name IN (SELECT name from tmp_node_names)
                    """
            )
            # 2. Resolve node ids
            names = [ni.name for ni in nodeinfos]

            self._populate_tmp(cur, "name", touched_names)

            cur.execute(
                f"SELECT id, name FROM nodes WHERE name IN (SELECT name from tmp_node_names)"
            )
            id_to_name = dict(cur.fetchall())
            name_to_id = {v:k for k,v in id_to_name.items()}

            pip_rows = []

            for ni in nodeinfos:
                for p in ni.pips():
                    from_id = name_to_id.get(p.from_wire)
                    to_id = name_to_id.get(p.to_wire)

                    pip_rows.append(
                        (from_id, to_id,
                         1 if p.is_bidi else 0,
                         p.flags,
                         p.buffertype)
                    )

            cur.executemany(
                """
                INSERT OR IGNORE INTO pips
                (from_id, to_id, bidir, flags, buffertype)
                VALUES (?, ?, ?, ?, ?)
                """,
                pip_rows
            )

            conn.commit()

    def insert_sites_and_fetch_ids(self, sites):
        if not sites:
            return {}

        with self.conn:
            cur = self.conn.cursor()

            self._populate_tmp(cur, "name", {s for s in sites})

            cur.execute("""
                        INSERT INTO sites (name)
                        SELECT t.name
                        FROM tmp_node_names t
                                 LEFT JOIN sites s ON s.name = t.name
                        WHERE s.name IS NULL
                        """)

            rows = cur.execute("""
                               SELECT s.name, s.id
                               FROM sites s
                                        JOIN tmp_names t ON t.name = s.name
                               """).fetchall()

        return dict(rows)

    def insert_sites(self, sites):
        conn = self.conn
        cur = conn.cursor()

        # ---- Insert sites ----
        site_rows = [
            (name,
             data["type"],
             int(data["x"]),
             int(data["y"]))
            for name, data in sites.items()
        ]

        cur.executemany(
            """
            INSERT OR IGNORE INTO sites (name, type, x, y)
            VALUES (?, ?, ?, ?)
            """,
            site_rows
        )

        site2id = dict(cur.execute("""
                           SELECT s.name, s.id
                           FROM sites s
                           """).fetchall())

        # ---- Resolve node IDs (from pin_node) ----
        node_names = {
            pin["pin_node"]
            for data in sites.values()
            for pin in data["pins"]
        }

        node2id = self.get_node_ids(node_names)

        # ---- Insert pins ----
        pin_rows = []

        for site_name, data in sites.items():
            sid = site2id[site_name]

            for pin in data["pins"]:
                nid = node2id.get(pin["pin_node"])
                if nid is None:
                    continue  # or raise if missing nodes are an error

                pin_rows.append(
                    (sid, pin["pin_name"], nid)
                )

        cur.executemany(
            """
            INSERT OR IGNORE INTO site_pins
            (site_id, pin_name, node_id)
            VALUES (?, ?, ?)
            """,
            pin_rows
        )

        conn.commit()

    def get_sites(self):
        conn = self.conn
        cur = conn.cursor()
        result = {}

        # ---- Fetch sites ----
        cur.execute(
            f"""
            SELECT id, name, type, x, y
            FROM sites
            """,
        )

        site_rows = cur.fetchall()
        if not site_rows:
            return result

        site_id = {}
        for sid, name, typ, x, y in site_rows:
            site_id[sid] = name
            result[name] = {
                "type": typ,
                "x": x,
                "y": y,
                "pins": []
            }

        # ---- Fetch pins ----
        cur.execute(
            f"""
            SELECT sp.site_id, sp.pin_name, n.name
            FROM site_pins sp
            JOIN nodes n ON n.id = sp.node_id
            """,
        )

        for sid, pin_name, node_name in cur.fetchall():
            result[site_id[sid]]["pins"].append({
                "pin_name": pin_name,
                "pin_node": node_name
            })

        return result
