from enum import Enum
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MessageType(str, Enum):
    JOIN = "join"
    LEAVE = "leave"
    CHAT = "chat"
    DM = "dm"  # New type for direct messages
    FETCH = "fetch"  # Request stored messages
    MARK_READ = "mark_read"  # Mark messages as read


class Status(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ChatMessage(BaseModel):
    username: str
    content: str
    timestamp: datetime = datetime.now()
    message_type: MessageType = MessageType.CHAT
    recipients: Optional[List[str]] = None  # List of usernames to receive the message
    message_id: Optional[int] = None  # Database ID for the message
    fetch_count: Optional[int] = None  # Number of messages to fetch
    message_ids: Optional[List[int]] = None  # List of message IDs to mark as read
    # None means broadcast to all (for CHAT type)


class ServerResponse(BaseModel):
    status: Status = Status.SUCCESS
    message: str
    data: Optional[ChatMessage] = None
    unread_count: Optional[int] = None  # Number of remaining unread messages
