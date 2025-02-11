from enum import Enum
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MessageType(str, Enum):
    SERVER_RESPONSE = "server_response"

    LOGIN = "login"
    LOGOUT = "logout"
    JOIN = "join"
    REGISTER = "register"

    CHAT = "chat"
    DM = "dm"
    FETCH = "fetch"
    MARK_READ = "mark_read"

    DELETE = "delete"
    DELETE_NOTIFICATION = "delete_notification"
    DELETE_ACCOUNT = "delete_account"


class Status(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class SystemMessage(str, Enum):
    # General messages
    NEW_MESSAGE = "new_message"

    # Authentication messages
    LOGIN_REQUIRED = "Please login or register first"
    USER_EXISTS = "Username already exists. Please login instead."
    PASSWORD_REQUIRED = "Password is required"
    REGISTRATION_SUCCESS = "Registration successful! Logging in..."
    REGISTRATION_FAILED = "Registration failed"
    INVALID_CREDENTIALS = "Invalid username or password"
    USER_ALREADY_LOGGED_IN = "User already logged in"
    LOGIN_SUCCESS = "Login successful"
    ACCOUNT_DELETED = "{} has deleted their account"

    # Connection messages
    CONNECTION_LOST = "Lost connection to server. The application will now close."
    CONNECTION_ERROR = (
        "Could not connect to server. Please check if the server is running."
    )

    # Validation messages
    EMPTY_CREDENTIALS = "Username and password are required"
    INVALID_MESSAGE_IDS = "Invalid message IDs"

    # Chat messages
    USER_JOINED = "{} has joined the chat"
    USER_LOGGED_OUT = "{} has logged out"
    MESSAGES_DELETED = "Deleted {} message(s)"
    UNREAD_MESSAGES = "You have {} unread messages"


class AuthMessage(BaseModel):
    """Authentication message format"""

    username: str
    password: str  # Will be hashed before transmission
    message_type: MessageType


class ChatMessage(BaseModel):
    username: str
    content: str
    timestamp: datetime = datetime.now()
    message_type: MessageType = MessageType.CHAT
    recipients: Optional[List[str]] = None  # List of usernames to receive the message
    message_id: Optional[int] = None  # Database ID for the message
    fetch_count: Optional[int] = None  # Number of messages to fetch
    message_ids: Optional[List[int]] = (
        None  # List of message IDs to mark as read or delete
    )
    password: Optional[str] = None  # For authentication messages
    active_users: Optional[List[str]] = None  # List of currently active users
    unread_count: Optional[int] = None  # Number of unread messages for notifications
    # None means broadcast to all (for CHAT type)

    def __str__(self) -> str:
        """String representation including message ID if available"""
        msg_id = f"[{self.message_id}] " if self.message_id is not None else ""
        if self.message_type == MessageType.DM and self.recipients:
            return f"{msg_id}DM to {self.recipients[0]}: {self.content}"
        return f"{msg_id}{self.content}"


class ServerResponse(BaseModel):
    status: Status = Status.SUCCESS
    message: str
    data: Optional[ChatMessage] = None
    unread_count: Optional[int] = None  # Number of remaining unread messages
