"""Data models and enums for the chat application.

This module defines the core data structures used throughout the chat application:
- Message types and status enums
- System message constants
- Chat message and server response models

These models are used for:
- Client-server communication
- Message serialization/deserialization
- Status and error handling
"""

from enum import Enum
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MessageType(str, Enum):
    """Enumeration of possible message types in the chat system.

    This enum defines all valid message types that can be exchanged between
    client and server. Each type represents a different kind of interaction
    or operation in the chat system.

    Values:
        SERVER_RESPONSE: Response from server to client
        LOGIN: User login request/response
        LOGOUT: User logout notification
        JOIN: User join notification
        REGISTER: New user registration
        CHAT: Regular chat message
        DM: Direct message to specific user(s)
        FETCH: Request to fetch message history
        MARK_READ: Mark messages as read
        DELETE: Delete specific messages
        DELETE_NOTIFICATION: Notification of message deletion
        DELETE_ACCOUNT: Account deletion request/notification
    """

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
    """Enumeration of possible server response statuses.

    Values:
        SUCCESS: Operation completed successfully
        ERROR: Operation failed with error
    """

    SUCCESS = "success"
    ERROR = "error"


class SystemMessage(str, Enum):
    """Enumeration of system message templates.

    These messages are used for various system notifications and errors
    throughout the application. They provide consistent messaging for
    common scenarios.

    Categories:
        - General messages
        - Authentication messages
        - Connection messages
        - Validation messages
        - Chat messages
    """

    # General messages
    NEW_MESSAGE = "new_message"

    # Authentication messages
    LOGIN_REQUIRED = "Please login or register first"
    USER_EXISTS = "Username already exists. Please login instead."
    PASSWORD_REQUIRED = "Password is required"
    USERNAME_REQUIRED = "Username is required"
    USERNAME_TOO_SHORT = "Username must be at least 2 characters"
    INVALID_USERNAME = "Username can only contain letters, numbers, and underscores"
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


class ChatMessage(BaseModel):
    """Chat message model representing all types of messages in the system.

    This is the core message model used throughout the application. It can
    represent various types of messages including regular chat messages,
    direct messages, system notifications, and control messages.

    Attributes:
        username (str): Sender's username
        content (str): Message content
        timestamp (datetime): Message timestamp (defaults to now)
        message_type (MessageType): Type of message (defaults to CHAT)
        recipients (Optional[List[str]]): List of recipient usernames
        message_id (Optional[int]): Database ID for the message
        fetch_count (Optional[int]): Number of messages to fetch
        message_ids (Optional[List[int]]): List of message IDs for operations
        password (Optional[str]): For authentication messages
        active_users (Optional[List[str]]): List of currently active users
        unread_count (Optional[int]): Number of unread messages
    """

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

    def __str__(self) -> str:
        """String representation of the message.

        Returns:
            str: Formatted string representation including message ID if available
                and special formatting for DMs
        """
        msg_id = f"[{self.message_id}] " if self.message_id is not None else ""
        if self.message_type == MessageType.DM and self.recipients:
            return f"{msg_id}DM to {self.recipients[0]}: {self.content}"
        return f"{msg_id}{self.content}"


class ServerResponse(BaseModel):
    """Server response model for all client requests.

    This model represents the server's response to any client request,
    including status, message, and optional data payload.

    Attributes:
        status (Status): Response status (SUCCESS/ERROR)
        message (str): Response message or error description
        data (Optional[ChatMessage]): Optional message payload
        unread_count (Optional[int]): Number of remaining unread messages
    """

    status: Status = Status.SUCCESS
    message: str
    data: Optional[ChatMessage] = None
    unread_count: Optional[int] = None  # Number of remaining unread messages
