import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
from schemas import ChatMessage, MessageType
import bcrypt


class Database:
    def __init__(self, db_path: str = "chat.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize the database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create users table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash BLOB NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Create messages table with foreign key constraints
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
                    delivered BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (sender) REFERENCES users(username),
                    FOREIGN KEY (recipient) REFERENCES users(username)
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

    def create_user(self, username: str, password: str) -> bool:
        """Create a new user. Returns True if successful, False if username exists"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Hash the password with bcrypt
                password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False  # Username already exists

    def verify_user(self, username: str, password: str) -> bool:
        """Verify user credentials. Returns True if valid."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)
            )
            result = cursor.fetchone()
            if not result:
                return False
            stored_hash = result[0]
            return bcrypt.checkpw(password.encode(), stored_hash)

    def user_exists(self, username: str) -> bool:
        """Check if a user exists"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            return cursor.fetchone() is not None

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
                WHERE recipient = ? AND read_status = FALSE
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

    def mark_read(self, message_ids: List[int], username: str) -> None:
        """Mark messages as read for a specific user"""
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
                (*message_ids, username),
            )

    def mark_read_from_user(self, recipient: str, sender: str) -> None:
        """Mark all messages from a specific user as read"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE messages 
                SET read_status = TRUE 
                WHERE sender = ? AND recipient = ? AND read_status = FALSE
                """,
                (sender, recipient),
            )

    def get_unread_count(self, recipient: str) -> int:
        """Get count of unread messages for a recipient"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE recipient = ? AND read_status = FALSE
                """,
                (recipient,),
            )
            return cursor.fetchone()[0]

    def delete_messages(
        self, message_ids: List[int], username: str, recipient: str
    ) -> Tuple[int, List[Tuple[str, bool]]]:
        """Delete messages for a user (must be between sender and recipient)
        Returns tuple of (number of messages deleted, list of (recipient, was_unread) tuples)
        """
        deleted_info = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # First get info about messages to be deleted
            cursor.execute(
                """
                SELECT recipient, read_status = FALSE
                FROM messages 
                WHERE id IN ({}) AND (
                    (sender = ? AND recipient = ?) OR
                    (sender = ? AND recipient = ?)
                )
                """.format(
                    ",".join("?" * len(message_ids))
                ),
                (*message_ids, username, recipient, recipient, username),
            )
            deleted_info = cursor.fetchall()

            # Then delete the messages
            cursor.execute(
                """
                DELETE FROM messages 
                WHERE id IN ({}) AND (
                    (sender = ? AND recipient = ?) OR
                    (sender = ? AND recipient = ?)
                )
                """.format(
                    ",".join("?" * len(message_ids))
                ),
                (*message_ids, username, recipient, recipient, username),
            )
            conn.commit()
            return cursor.rowcount, deleted_info

    def get_all_users(self) -> List[str]:
        """Get a list of all registered users"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users")
            return [row[0] for row in cursor.fetchall()]

    def get_messages_between_users(
        self, user1: str, user2: str, limit: int = 50
    ) -> List[ChatMessage]:
        """Get messages exchanged between two users"""
        query = """
            SELECT m.id, m.sender, m.recipient, m.content, m.timestamp, m.message_type
            FROM messages m
            WHERE (
                (m.sender = ? AND m.recipient = ?)
                OR 
                (m.sender = ? AND m.recipient = ?)
            )
            ORDER BY m.timestamp ASC
            LIMIT ?
        """

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(query, (user1, user2, user2, user1, limit))
                rows = cursor.fetchall()
                messages = []
                for row in rows:
                    # row indices: 0=id, 1=sender, 2=recipient, 3=content, 4=timestamp, 5=message_type
                    message = ChatMessage(
                        username=row[1],  # sender
                        content=row[3],
                        message_type=MessageType.DM,
                        message_id=row[0],
                        recipients=[row[2]],  # recipient
                        timestamp=datetime.fromisoformat(row[4]),
                    )
                    messages.append(message)
                return messages
        except Exception as e:
            print(f"Error fetching messages between users: {e}")
            return []

    def delete_user(self, username: str) -> bool:
        """Delete a user and all their messages. Returns True if successful."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Delete all messages where user is sender or recipient
                cursor.execute(
                    """
                    DELETE FROM messages 
                    WHERE sender = ? OR recipient = ?
                    """,
                    (username, username),
                )
                # Delete the user
                cursor.execute(
                    """
                    DELETE FROM users 
                    WHERE username = ?
                    """,
                    (username,),
                )
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False
