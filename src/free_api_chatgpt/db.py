import json
import sqlite3
from pathlib import Path
from typing import Any

DATABASE_PATH = Path("./data/chat.db")


class Database:
    def __init__(
        self,
        path: str | Path = DATABASE_PATH,
    ):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            self.path,
        )

        connection.row_factory = sqlite3.Row

        connection.execute("PRAGMA foreign_keys = ON")

        return connection

    def initialize(self):
        with self.connect() as connection:
            if not self._entries_table_exists(connection):
                self._create_entries_table(connection)
            elif not self._entries_schema_is_current(connection):
                self._migrate_entries_table(connection)

            if not self._history_table_exists(connection):
                self._create_history_table(connection)
            elif not self._history_schema_is_current(connection):
                self._migrate_history_table(connection)

            self._create_indexes(connection)

            connection.commit()

    @staticmethod
    def _entries_table_exists(
        connection: sqlite3.Connection,
    ) -> bool:
        row = connection.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'entries'
            LIMIT 1
        """).fetchone()

        return row is not None

    @staticmethod
    def _create_entries_table(
        connection: sqlite3.Connection,
    ):
        connection.execute("""
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY,

                key TEXT NOT NULL UNIQUE,

                title TEXT NOT NULL,

                category TEXT NOT NULL,

                data TEXT NOT NULL
                    CHECK (
                        json_valid(data)
                        AND json_type(data) = 'object'
                    ),

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                CHECK (length(trim(key)) > 0),
                CHECK (length(trim(title)) > 0),
                CHECK (length(trim(category)) > 0)
            ) STRICT
        """)

    @staticmethod
    def _entries_schema_is_current(
        connection: sqlite3.Connection,
    ) -> bool:
        table_sql = connection.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'entries'
        """).fetchone()

        if table_sql is None:
            return False

        sql = (table_sql["sql"] or "").upper()

        if "STRICT" not in sql:
            return False

        if "AUTOINCREMENT" in sql:
            return False

        required_columns = {
            "id",
            "key",
            "title",
            "category",
            "data",
            "created_at",
            "updated_at",
        }

        rows = connection.execute("PRAGMA table_info(entries)").fetchall()

        columns = {row["name"] for row in rows}

        return columns == required_columns

    def _migrate_entries_table(
        self,
        connection: sqlite3.Connection,
    ):
        rows = connection.execute("""
            SELECT
                id,
                key,
                title,
                category,
                data,
                created_at,
                updated_at
            FROM entries
            ORDER BY id
        """).fetchall()

        for row in rows:
            try:
                data = json.loads(row["data"])
            except (
                TypeError,
                json.JSONDecodeError,
            ) as exc:
                raise ValueError(f"Invalid JSON in entry {row['id']}.") from exc

            self._validate_entry_values(
                key=row["key"],
                title=row["title"],
                category=row["category"],
                data=data,
            )

        connection.execute("ALTER TABLE entries RENAME TO entries_old")

        self._create_entries_table(connection)

        connection.executemany(
            """
            INSERT INTO entries (
                id,
                key,
                title,
                category,
                data,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["key"],
                    row["title"],
                    row["category"],
                    row["data"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows
            ],
        )

        connection.execute("DROP TABLE entries_old")

    @staticmethod
    def _history_table_exists(
        connection: sqlite3.Connection,
    ) -> bool:
        row = connection.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'history'
            LIMIT 1
        """).fetchone()

        return row is not None

    @staticmethod
    def _create_history_table(
        connection: sqlite3.Connection,
    ):
        connection.execute("""
            CREATE TABLE history (
                id INTEGER PRIMARY KEY,

                entry_id INTEGER,

                action TEXT NOT NULL,

                key TEXT,

                title TEXT,

                category TEXT,

                data TEXT
                    CHECK (
                        data IS NULL
                        OR (
                            json_valid(data)
                            AND json_type(data) = 'object'
                        )
                    ),

                message TEXT,

                response TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (entry_id)
                    REFERENCES entries(id)
                    ON DELETE SET NULL,

                CHECK (
                    action IN (
                        'message',
                        'create',
                        'update',
                        'delete'
                    )
                )
            ) STRICT
        """)

    @staticmethod
    def _history_schema_is_current(
        connection: sqlite3.Connection,
    ) -> bool:
        table_sql = connection.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'history'
        """).fetchone()

        if table_sql is None:
            return False

        sql = (table_sql["sql"] or "").upper()

        if "STRICT" not in sql:
            return False

        required_columns = {
            "id",
            "entry_id",
            "action",
            "key",
            "title",
            "category",
            "data",
            "message",
            "response",
            "created_at",
        }

        rows = connection.execute("PRAGMA table_info(history)").fetchall()

        columns = {row["name"] for row in rows}

        return columns == required_columns

    def _migrate_history_table(
        self,
        connection: sqlite3.Connection,
    ):
        rows = connection.execute("""
            SELECT
                id,
                entry_id,
                action,
                key,
                title,
                category,
                data,
                message,
                response,
                created_at
            FROM history
            ORDER BY id
        """).fetchall()

        connection.execute("ALTER TABLE history RENAME TO history_old")

        self._create_history_table(connection)

        connection.executemany(
            """
            INSERT INTO history (
                id,
                entry_id,
                action,
                key,
                title,
                category,
                data,
                message,
                response,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["entry_id"],
                    row["action"],
                    row["key"],
                    row["title"],
                    row["category"],
                    row["data"],
                    row["message"],
                    row["response"],
                    row["created_at"],
                )
                for row in rows
            ],
        )

        connection.execute("DROP TABLE history_old")

    @staticmethod
    def _create_indexes(
        connection: sqlite3.Connection,
    ):
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_category
            ON entries(category)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_title
            ON entries(title)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_updated_at
            ON entries(updated_at DESC)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_entry_id
            ON history(entry_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_action
            ON history(action)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_created_at
            ON history(created_at DESC, id DESC)
        """)

    def get_stats(self) -> dict:
        tables = self.get_tables()

        return {
            "tables": len(tables),
            "rows": sum(table["rows"] for table in tables),
            "table_stats": tables,
        }

    def get_database_overview(self) -> dict:
        tables = self.get_tables()

        overview = []

        for table in tables:
            overview.append(
                {
                    "name": table["name"],
                    "rows": table["rows"],
                    "columns": self.get_table_info(table["name"]),
                }
            )

        return {
            "tables": len(overview),
            "rows": sum(table["rows"] for table in overview),
            "table_stats": overview,
        }

    def get_tables(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """).fetchall()

            tables = []

            for row in rows:
                name = row["name"]

                quoted_name = self._quote_identifier(name)

                count = connection.execute(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM {quoted_name}
                    """
                ).fetchone()["count"]

                tables.append(
                    {
                        "name": name,
                        "rows": count,
                    }
                )

        return tables

    def table_exists(
        self,
        table_name: str,
    ) -> bool:
        return any(table["name"] == table_name for table in self.get_tables())

    def get_table_info(
        self,
        table_name: str,
    ) -> list[dict]:
        if not self.table_exists(table_name):
            return []

        quoted_name = self._quote_identifier(table_name)

        with self.connect() as connection:
            rows = connection.execute(f"PRAGMA table_info({quoted_name})").fetchall()

        return [
            {
                "cid": row["cid"],
                "name": row["name"],
                "type": row["type"],
                "notnull": bool(row["notnull"]),
                "default": row["dflt_value"],
                "primary_key": bool(row["pk"]),
            }
            for row in rows
        ]

    def get_table_rows(
        self,
        table_name: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        if not self.table_exists(table_name):
            return []

        limit = max(
            1,
            min(limit, 500),
        )

        offset = max(
            0,
            offset,
        )

        quoted_name = self._quote_identifier(table_name)

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM {quoted_name}
                LIMIT ? OFFSET ?
                """,
                (
                    limit,
                    offset,
                ),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_table_row_count(
        self,
        table_name: str,
    ) -> int:
        if not self.table_exists(table_name):
            return 0

        quoted_name = self._quote_identifier(table_name)

        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {quoted_name}
                """
            ).fetchone()

        return row["count"]

    def get_table_row(
        self,
        table_name: str,
        row_id: int,
    ) -> dict | None:
        if not self.table_exists(table_name):
            return None

        columns = self.get_table_info(table_name)

        primary_key = next(
            (column["name"] for column in columns if column["primary_key"]),
            None,
        )

        if primary_key is None:
            return None

        quoted_table = self._quote_identifier(table_name)

        quoted_primary_key = self._quote_identifier(primary_key)

        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM {quoted_table}
                WHERE {quoted_primary_key} = ?
                LIMIT 1
                """,
                (row_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def list_entries(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        limit = max(
            1,
            min(limit, 500),
        )

        with self.connect() as connection:
            if category:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        key,
                        title,
                        category,
                        created_at,
                        updated_at
                    FROM entries
                    WHERE category = ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (
                        category,
                        limit,
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        key,
                        title,
                        category,
                        created_at,
                        updated_at
                    FROM entries
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        return [dict(row) for row in rows]

    def get_entry(
        self,
        entry_id: int,
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    key,
                    title,
                    category,
                    data,
                    created_at,
                    updated_at
                FROM entries
                WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()

        if row is None:
            return None

        entry = dict(row)

        entry["data"] = json.loads(entry["data"])

        return entry

    def get_entry_by_key(
        self,
        key: str,
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    key,
                    title,
                    category,
                    data,
                    created_at,
                    updated_at
                FROM entries
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return None

        entry = dict(row)

        entry["data"] = json.loads(entry["data"])

        return entry

    def search_entries(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        limit = max(
            1,
            min(limit, 100),
        )

        pattern = f"%{query}%"

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    key,
                    title,
                    category
                FROM entries
                WHERE key LIKE ?
                OR title LIKE ?
                OR category LIKE ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (
                    pattern,
                    pattern,
                    pattern,
                    limit,
                ),
            ).fetchall()

        return [dict(row) for row in rows]

    def create_entry(
        self,
        key: str,
        title: str,
        category: str,
        data: dict[str, Any],
    ) -> dict | None:
        self._validate_entry_values(
            key=key,
            title=title,
            category=category,
            data=data,
        )

        encoded_data = json.dumps(
            data,
            ensure_ascii=False,
        )

        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT
                    id,
                    key,
                    title,
                    category,
                    data
                FROM entries
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO entries (
                        key,
                        title,
                        category,
                        data
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        key,
                        title,
                        category,
                        encoded_data,
                    ),
                )

                entry_id = cursor.lastrowid

                if entry_id is None:
                    return None

                self._create_history(
                    connection,
                    entry_id=entry_id,
                    action="create",
                    key=key,
                    title=title,
                    category=category,
                    data=data,
                )

            else:
                entry_id = existing["id"]

                connection.execute(
                    """
                    UPDATE entries
                    SET
                        title = ?,
                        category = ?,
                        data = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        title,
                        category,
                        encoded_data,
                        entry_id,
                    ),
                )

                self._create_history(
                    connection,
                    entry_id=entry_id,
                    action="update",
                    key=key,
                    title=title,
                    category=category,
                    data=data,
                )

            connection.commit()

        return self.get_entry(entry_id)

    def update_entry(
        self,
        entry_id: int,
        title: str | None = None,
        category: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict | None:
        current = self.get_entry(entry_id)

        if current is None:
            return None

        new_title = title if title is not None else current["title"]

        new_category = category if category is not None else current["category"]

        new_data = data if data is not None else current["data"]

        self._validate_entry_values(
            key=current["key"],
            title=new_title,
            category=new_category,
            data=new_data,
        )

        encoded_data = json.dumps(
            new_data,
            ensure_ascii=False,
        )

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE entries
                SET
                    title = ?,
                    category = ?,
                    data = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_title,
                    new_category,
                    encoded_data,
                    entry_id,
                ),
            )

            self._create_history(
                connection,
                entry_id=entry_id,
                action="update",
                key=current["key"],
                title=new_title,
                category=new_category,
                data=new_data,
            )

            connection.commit()

        return self.get_entry(entry_id)

    def delete_entry(
        self,
        entry_id: int,
    ) -> bool:
        current = self.get_entry(entry_id)

        if current is None:
            return False

        with self.connect() as connection:
            self._create_history(
                connection,
                entry_id=entry_id,
                action="delete",
                key=current["key"],
                title=current["title"],
                category=current["category"],
                data=current["data"],
            )

            cursor = connection.execute(
                """
                DELETE FROM entries
                WHERE id = ?
                """,
                (entry_id,),
            )

            connection.commit()

            return cursor.rowcount > 0

    def log_interaction(
        self,
        message: str,
        response: str | None = None,
    ) -> dict:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO history (
                    action,
                    message,
                    response
                )
                VALUES (?, ?, ?)
                """,
                (
                    "message",
                    message,
                    response,
                ),
            )

            history_id = cursor.lastrowid

            if history_id is None:
                raise RuntimeError("Failed to create history record.")

            connection.commit()

        history = self.get_history(history_id)

        if history is None:
            raise RuntimeError("History record could not be retrieved.")

        return history

    def _create_history(
        self,
        connection: sqlite3.Connection,
        *,
        entry_id: int | None,
        action: str,
        key: str | None,
        title: str | None,
        category: str | None,
        data: dict[str, Any] | None,
    ):
        encoded_data = (
            json.dumps(
                data,
                ensure_ascii=False,
            )
            if data is not None
            else None
        )

        connection.execute(
            """
            INSERT INTO history (
                entry_id,
                action,
                key,
                title,
                category,
                data
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                action,
                key,
                title,
                category,
                encoded_data,
            ),
        )

    def list_history(
        self,
        entry_id: int | None = None,
        action: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        limit = max(
            1,
            min(limit, 500),
        )

        with self.connect() as connection:
            conditions = []
            parameters = []

            if entry_id is not None:
                conditions.append("entry_id = ?")
                parameters.append(entry_id)

            if action is not None:
                conditions.append("action = ?")
                parameters.append(action)

            if created_after is not None:
                conditions.append("created_at >= ?")
                parameters.append(created_after)

            if created_before is not None:
                conditions.append("created_at <= ?")
                parameters.append(created_before)

            where = ""

            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            parameters.append(limit)

            rows = connection.execute(
                f"""
                SELECT
                    id,
                    entry_id,
                    action,
                    key,
                    title,
                    category,
                    data,
                    message,
                    response,
                    created_at
                FROM history
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        return [self._decode_history_row(row) for row in rows]

    def get_history(
        self,
        history_id: int,
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    entry_id,
                    action,
                    key,
                    title,
                    category,
                    data,
                    message,
                    response,
                    created_at
                FROM history
                WHERE id = ?
                """,
                (history_id,),
            ).fetchone()

        if row is None:
            return None

        return self._decode_history_row(row)

    def update_history(
        self,
        history_id: int,
        *,
        title: str | None = None,
        category: str | None = None,
        data: dict[str, Any] | None = None,
        message: str | None = None,
        response: str | None = None,
    ) -> dict | None:
        current = self.get_history(history_id)

        if current is None:
            return None

        if data is not None and not isinstance(
            data,
            dict,
        ):
            raise TypeError("History data must be a JSON object.")

        if title is not None and not isinstance(
            title,
            str,
        ):
            raise TypeError("History title must be a string.")

        if category is not None and not isinstance(
            category,
            str,
        ):
            raise TypeError("History category must be a string.")

        if message is not None and not isinstance(
            message,
            str,
        ):
            raise TypeError("History message must be a string.")

        if response is not None and not isinstance(
            response,
            str,
        ):
            raise TypeError("History response must be a string.")

        new_title = title if title is not None else current["title"]

        new_category = category if category is not None else current["category"]

        new_data = data if data is not None else current["data"]

        new_message = message if message is not None else current["message"]

        new_response = response if response is not None else current["response"]

        encoded_data = (
            json.dumps(
                new_data,
                ensure_ascii=False,
            )
            if new_data is not None
            else None
        )

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE history
                SET
                    title = ?,
                    category = ?,
                    data = ?,
                    message = ?,
                    response = ?
                WHERE id = ?
                """,
                (
                    new_title,
                    new_category,
                    encoded_data,
                    new_message,
                    new_response,
                    history_id,
                ),
            )

            connection.commit()

        return self.get_history(history_id)

    def delete_history(
        self,
        history_id: int,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM history
                WHERE id = ?
                """,
                (history_id,),
            )

            connection.commit()

            return cursor.rowcount > 0

    @staticmethod
    def _decode_history_row(
        row: sqlite3.Row,
    ) -> dict:
        history = dict(row)

        if history["data"] is not None:
            history["data"] = json.loads(history["data"])

        return history

    @staticmethod
    def _validate_entry_values(
        *,
        key: str,
        title: str,
        category: str,
        data: dict[str, Any],
    ):
        if (
            not isinstance(
                key,
                str,
            )
            or not key.strip()
        ):
            raise ValueError("Entry key must be a non-empty string.")

        if (
            not isinstance(
                title,
                str,
            )
            or not title.strip()
        ):
            raise ValueError("Entry title must be a non-empty string.")

        if (
            not isinstance(
                category,
                str,
            )
            or not category.strip()
        ):
            raise ValueError("Entry category must be a non-empty string.")

        if not isinstance(
            data,
            dict,
        ):
            raise TypeError("Entry data must be a JSON object.")

        try:
            json.dumps(
                data,
                ensure_ascii=False,
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise TypeError("Entry data must contain JSON-compatible values.") from exc

    @staticmethod
    def _quote_identifier(
        identifier: str,
    ) -> str:
        return (
            '"'
            + identifier.replace(
                '"',
                '""',
            )
            + '"'
        )
