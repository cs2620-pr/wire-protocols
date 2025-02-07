from enum import Enum
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MessageType(str, Enum):
    JOIN = "join"
    LEAVE = "leave"
    CHAT = "chat"


class Status(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ChatMessage(BaseModel):
    username: str
    content: str
    timestamp: datetime = datetime.now()
    message_type: MessageType = MessageType.CHAT


class ServerResponse(BaseModel):
    status: Status = Status.SUCCESS
    message: str
    data: Optional[ChatMessage] = None
