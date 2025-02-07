from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
import json
import time


class Protocol(str, Enum):
    """Protocol types for wire communication"""

    JSON = "json"
    CUSTOM = "custom"


class MessageType(str, Enum):
    """Types of messages that can be sent"""

    AUTH = "auth"
    CHAT = "chat"
    SYSTEM = "system"
    ERROR = "error"


class CommandType(str, Enum):
    """Available commands"""

    CREATE_ACCOUNT = "create_account"
    LOGIN = "login"
    LOGOUT = "logout"
    LIST_USERS = "list_users"
    SEND_MESSAGE = "send_message"
    READ_MESSAGES = "read_messages"
    DELETE_MESSAGES = "delete_messages"
    DELETE_ACCOUNT = "delete_account"


class ResponseStatus(str, Enum):
    """Response status types"""

    SUCCESS = "success"
    ERROR = "error"


# Base Models
class BaseMessage(BaseModel):
    """Base message format"""

    type: MessageType
    command: CommandType
    timestamp: float = Field(default_factory=lambda: time.time())


class BaseResponse(BaseModel):
    """Base response format"""

    status: ResponseStatus
    message: str
    data: Optional[Dict[str, Any]] = None


# Auth Models
class AuthRequest(BaseMessage):
    """Authentication request format"""

    username: str
    password: str


class AuthResponse(BaseResponse):
    """Authentication response format"""

    token: Optional[str] = None
    unread_count: Optional[int] = None


# Chat Models
class ChatMessage(BaseModel):
    """Chat message format"""

    id: Optional[int] = None
    sender: str
    recipient: str
    content: str
    timestamp: float
    read: bool = False


class SendMessageRequest(BaseMessage):
    """Message sending request format"""

    sender: str
    recipient: str
    content: str


class ListUsersRequest(BaseMessage):
    """Request format for listing users"""

    type: MessageType = MessageType.SYSTEM
    command: CommandType = CommandType.LIST_USERS
    pattern: str = "%"
    page: int = 1
    page_size: int = 20


class ListUsersResponse(BaseResponse):
    """User listing response format"""

    users: List[str]
    total_count: int
    page: int
    total_pages: int


class DeleteAccountRequest(BaseMessage):
    """Account deletion request format"""

    username: str


class ReadMessagesRequest(BaseMessage):
    """Message reading request format"""

    username: str
    limit: int = 50
    offset: int = 0


class DeleteMessagesRequest(BaseMessage):
    """Message deletion request format"""

    message_ids: List[int]


# Protocol Helpers
class ProtocolHelper:
    """Helper class for protocol encoding/decoding"""

    @staticmethod
    def encode(data: BaseModel, protocol: Protocol) -> bytes:
        """Encode data according to protocol"""
        if protocol == Protocol.JSON:
            return json.dumps(data.model_dump()).encode()
        else:
            # Custom protocol implementation
            data_json = json.dumps(data.model_dump())
            msg_type = getattr(data, "type", MessageType.SYSTEM)
            command = getattr(data, "command", CommandType.SEND_MESSAGE)
            header = f"{msg_type}|{command}|{len(data_json)}|"
            return header.encode() + data_json.encode()

    @staticmethod
    def decode(data: bytes, protocol: Protocol) -> Dict:
        """Decode data according to protocol"""
        if protocol == Protocol.JSON:
            return json.loads(data.decode())
        else:
            # Custom protocol implementation
            parts = data.decode().split("|", 3)
            if len(parts) != 4:
                raise ValueError("Invalid message format")
            msg_type, command, length, payload = parts
            return json.loads(payload)
