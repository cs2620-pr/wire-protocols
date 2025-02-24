"""SQLite database implementation for the chat application.

This module provides persistent storage for chat messages and user data using SQLite.
It handles:
- User account management (creation, authentication, deletion)
- Message storage and retrieval
- Message status tracking (read/unread, delivered)
- Chat history management
"""

import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
from schemas import ChatMessage, MessageType
import bcrypt


def adapt_datetime(dt: datetime) -> str:
    """Convert datetime object to ISO format string for SQLite storage.

    Args:
        dt: The datetime object to convert

    Returns:
        str: ISO format string representation of the datetime
    """
    return dt.isoformat()


def convert_datetime(val: bytes) -> datetime:
    """Convert SQLite datetime string back to datetime object.

    Args:
        val: Bytes containing the ISO format datetime string

    Returns:
        datetime: The parsed datetime object
    """
    return datetime.fromisoformat(val.decode())


class Database:
    """SQLite database manager for the chat application.

    This class handles all database operations including:
    - User management (registration, authentication)
    - Message storage and retrieval
    - Message status tracking
    - Chat history management

    Attributes:
        db_path (str): Path to the SQLite database file
        conn (sqlite3.Connection): Database connection
    """

    def __init__(self, db_path: str = "chat.db"):
        """Initialize database connection and schema.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        # Register datetime adapter and converter
        sqlite3.register_adapter(datetime, adapt_datetime)
        sqlite3.register_converter("TIMESTAMP", convert_datetime)
        # Connect with type detection
        def get_connection(self):
            """Create a new SQLite connection for each thread-safe operation."""
            conn = sqlite3.connect(
                self.db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            conn.row_factory = sqlite3.Row  # Enable named column access
            return conn

        self.init_db()

    def __del__(self):
        """Close database connection on object destruction."""
        if getattr(self, "conn", None):
            self.conn.close()

    def init_db(self):
        """Initialize the database schema.

        Creates the following tables if they don't exist:
        - users: Stores user accounts and credentials
        - messages: Stores chat messages and their metadata
        Also creates necessary indices for efficient querying.
        """
        cursor = self.conn.cursor()

        # Create users table with explicit TIMESTAMP type
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Create messages table with foreign key constraints and explicit TIMESTAMP type
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                message_type TEXT NOT NULL,
                read_status BOOLEAN DEFAULT FALSE,
                delivered BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (sender) REFERENCES users(username),
                FOREIGN KEY (recipient) REFERENCES users(username)
            )
        """
        )

        # Create indices for efficient querying
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

        self.conn.commit()

    def create_user(self, username: str, password: str) -> bool:
        """Create a new user account.

        Args:
            username: The username for the new account
            password: The password for the new account

        Returns:
            bool: True if user was created successfully, False if username exists

        The password is hashed using bcrypt before storage.
        """
        try:
            cursor = self.conn.cursor()
            # Hash the password with bcrypt
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Username already exists

    def verify_user(self, username: str, password: str) -> bool:
        """Verify user credentials.

        Args:
            username: The username to verify
            password: The password to verify

        Returns:
            bool: True if credentials are valid, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        )
        result = cursor.fetchone()
        if not result:
            return False
        stored_hash = result[0]
        return bcrypt.checkpw(password.encode(), stored_hash)

    def user_exists(self, username: str) -> bool:
        """Check if a user exists.

        Args:
            username: The username to check

        Returns:
            bool: True if user exists, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        return cursor.fetchone() is not None

    def store_message(self, message: ChatMessage) -> int:
        """Store a chat message in the database.

        Args:
            message: The ChatMessage to store

        Returns:
            int: The ID of the stored message

        Raises:
            RuntimeError: If message ID generation fails
        """
        cursor = self.conn.cursor()
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
                message.timestamp,
                message.message_type,
                False,
                False,
            ),
        )
        self.conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("Failed to generate message ID")
        return cursor.lastrowid

    def get_unread_messages(
        self, recipient: str, limit: Optional[int] = None
    ) -> List[ChatMessage]:
        """Get unread messages for a recipient.

        Args:
            recipient: Username of the message recipient
            limit: Maximum number of messages to return

        Returns:
            List[ChatMessage]: List of unread messages
        """
        cursor = self.conn.cursor()

        query = """
            SELECT id, sender, recipient, content, 
                   timestamp as "timestamp [TIMESTAMP]", message_type
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
                    timestamp=row[4],  # Now automatically converted
                    message_type=row[5],
                    recipients=[row[2]],
                )
            )

        return messages

    def mark_delivered(self, message_id: int):
        """Mark a message as delivered.

        Args:
            message_id: ID of the message to mark as delivered
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE messages
            SET delivered = TRUE
            WHERE id = ?
        """,
            (message_id,),
        )
        self.conn.commit()

    def mark_read(self, message_ids: List[int], username: str) -> None:
        """Mark specific messages as read for a user.

        Args:
            message_ids: List of message IDs to mark as read
            username: Username of the message recipient
        """
        cursor = self.conn.cursor()
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
        self.conn.commit()

    def mark_read_from_user(self, recipient: str, sender: str) -> None:
        """Mark all messages from a specific user as read.

        Args:
            recipient: Username of the message recipient
            sender: Username of the message sender
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE messages 
            SET read_status = TRUE 
            WHERE sender = ? AND recipient = ? AND read_status = FALSE
            """,
            (sender, recipient),
        )
        self.conn.commit()

    def get_unread_count(self, recipient: str) -> int:
        """Get count of unread messages for a recipient.

        Args:
            recipient: Username to get unread count for

        Returns:
            int: Number of unread messages
        """
        cursor = self.conn.cursor()
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
        """Delete messages between two users.

        Args:
            message_ids: List of message IDs to delete
            username: Username of the requesting user
            recipient: Username of the other user in the conversation

        Returns:
            tuple: (number_of_messages_deleted, list_of_deleted_message_info)
            - number_of_messages_deleted: Number of messages that were deleted
            - list_of_deleted_message_info: List of (recipient, was_unread) tuples
        """
        deleted_info = []
        cursor = self.conn.cursor()
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
        self.conn.commit()
        return cursor.rowcount, deleted_info

    def get_all_users(self) -> List[str]:
        """Get a list of all registered users.

        Returns:
            List[str]: List of all usernames
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT username FROM users")
        return [row[0] for row in cursor.fetchall()]

    def get_messages_between_users(
        self, user1: str, user2: str, limit: int = 50
    ) -> List[ChatMessage]:
        """Get chat history between two users.

        Args:
            user1: First username
            user2: Second username
            limit: Maximum number of messages to return

        Returns:
            List[ChatMessage]: List of messages between the users
        """
        query = """
            SELECT m.id, m.sender, m.recipient, m.content, 
                   m.timestamp as "timestamp [TIMESTAMP]", m.message_type
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
            cursor = self.conn.cursor()
            cursor.execute(query, (user1, user2, user2, user1, limit))
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
                    timestamp=row[4],  # Now automatically converted
                )
                messages.append(message)
            return messages
        except Exception as e:
            print(f"Error fetching messages between users: {e}")
            return []

    def delete_user(self, username: str) -> bool:
        """Delete a user account and all associated messages.

        Args:
            username: Username of the account to delete

        Returns:
            bool: True if user was deleted successfully
        """
        try:
            cursor = self.conn.cursor()
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
            self.conn.commit()
            # Return True only if a user was actually deleted
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False
