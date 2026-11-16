import sqlite3
from pathlib import Path


class SeenStore:
    """Correos ya procesados (Resend puede entregar el mismo webhook más de una vez)."""

    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS seen (email_id TEXT PRIMARY KEY)")
        self._db.commit()

    def add(self, email_id: str) -> bool:
        """True si es la primera vez que se ve este id."""
        try:
            self._db.execute("INSERT INTO seen (email_id) VALUES (?)", (email_id,))
            self._db.commit()
            return True
        except sqlite3.IntegrityError:
            return False
