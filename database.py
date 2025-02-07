import sqlite3
from datetime import datetime
from typing import List, Optional
from schemas import ChatMessage, MessageType


class Database:
    def __init__(self, db_path: str = "chat.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize the database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create messages table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    message_type TEXT NOT NULL,
                    read_status BOOLEAN DEFAULT FALSE,
                    delivered BOOLEAN DEFAULT FALSE
                )
            """
            )

            # Create indices
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_recipient_status 
                ON messages(recipient, read_status)
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON messages(timestamp)
            """
            )

            conn.commit()

    def store_message(self, message: ChatMessage) -> int:
        """Store a message and return its ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (
                    sender, recipient, content, timestamp, 
                    message_type, read_status, delivered
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message.username,
                    message.recipients[0] if message.recipients else None,
                    message.content,
                    datetime.now(),
                    message.message_type,
                    False,
                    False,
                ),
            )
            conn.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to generate message ID")
            return cursor.lastrowid

    def get_unread_messages(
        self, recipient: str, limit: Optional[int] = None
    ) -> List[ChatMessage]:
        """Get unread messages for a recipient"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            query = """
                SELECT id, sender, recipient, content, timestamp, message_type
                FROM messages
                WHERE recipient = ? AND read_status = FALSE AND delivered = FALSE
                ORDER BY timestamp ASC
            """
            if limit:
                query += f" LIMIT {limit}"

            cursor.execute(query, (recipient,))
            messages = []

            for row in cursor.fetchall():
                messages.append(
                    ChatMessage(
                        message_id=row[0],
                        username=row[1],
                        content=row[3],
                        timestamp=datetime.fromisoformat(row[4]),
                        message_type=row[5],
                        recipients=[row[2]],
                    )
                )

            return messages

    def mark_delivered(self, message_id: int):
        """Mark a message as delivered"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE messages
                SET delivered = TRUE
                WHERE id = ?
            """,
                (message_id,),
            )
            conn.commit()

    def mark_read(self, message_ids: List[int], recipient: str):
        """Mark messages as read for a recipient"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE messages
                SET read_status = TRUE
                WHERE id IN ({}) AND recipient = ?
            """.format(
                    ",".join("?" * len(message_ids))
                ),
                (*message_ids, recipient),
            )
            conn.commit()

    def get_unread_count(self, recipient: str) -> int:
        """Get count of unread messages for a recipient"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE recipient = ? AND read_status = FALSE AND delivered = FALSE
            """,
                (recipient,),
            )
            return cursor.fetchone()[0]

    def delete_messages(self, message_ids: List[int], username: str) -> int:
        """Delete messages for a user (must be sender or recipient)
        Returns number of messages deleted"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM messages 
                WHERE id IN ({}) AND (sender = ? OR recipient = ?)
            """.format(
                    ",".join("?" * len(message_ids))
                ),
                (*message_ids, username, username),
            )
            conn.commit()
            return cursor.rowcount
