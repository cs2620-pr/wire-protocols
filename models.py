from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
from pydantic import BaseModel, GetCoreSchemaHandler, ConfigDict
from pydantic_core import CoreSchema, core_schema


class Username(str):
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: type[str] | None = None,
        _handler: GetCoreSchemaHandler | None = None,
    ) -> CoreSchema:
        return core_schema.str_schema()


class Password(str):
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: type[str] | None = None,
        _handler: GetCoreSchemaHandler | None = None,
    ) -> CoreSchema:
        return core_schema.str_schema()


class Protocol(str, Enum):
    JSON = "json"
    CUSTOM = "custom"

    def __str__(self) -> str:
        return self.value


class CommandType(str, Enum):
    CREATE_ACCOUNT = "create_account"
    LOGIN = "login"
    LIST_ACCOUNTS = "list_accounts"
    SEND_MESSAGE = "send_message"
    READ_MESSAGES = "read_messages"
    DELETE_MESSAGES = "delete_messages"
    DELETE_ACCOUNT = "delete_account"

    def __str__(self) -> str:
        return self.value


class ResponseStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


class MessageType(Enum):
    NEW_MESSAGE = "new_message"

    def __str__(self) -> str:
        return self.value


# Base Request/Response Models
class BaseResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ResponseStatus
    message: str

    def __str__(self) -> str:
        return self.message


class AuthRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    command: CommandType
    username: str
    password: str


class ListAccountsRequest(BaseModel):
    command: CommandType
    pattern: str = "%"
    page: int = 1
    page_size: int = 10


class ListAccountsResponse(BaseResponse):
    accounts: List[str]
    total_count: int
    page: int
    total_pages: int
    message: str


class SendMessageRequest(BaseModel):
    command: CommandType
    sender: str
    recipient: str
    content: str


class NewMessageNotification(BaseResponse):
    type: MessageType
    sender: Username
    content: str


class ReadMessagesRequest(BaseModel):
    command: CommandType = CommandType.READ_MESSAGES
    username: str
    recipient: Optional[str] = None
    limit: int
    sent: bool = False
    pattern: Optional[str] = None


class Message(BaseModel):
    id: Optional[int] = None
    sender: str
    recipient: str
    content: str
    timestamp: float
    read: bool = False


class DeleteMessagesRequest(BaseModel):
    command: CommandType
    username: str
    message_ids: List[int]


class DeleteAccountRequest(BaseModel):
    command: CommandType
    username: str


class LoginResponse(BaseResponse):
    unread_messages: int


class ReadMessagesResponse(BaseResponse):
    messages: List[Message]
