from abc import ABC, abstractmethod
import json
from typing import Optional
from schemas import ChatMessage, ServerResponse


class Protocol(ABC):
    """Abstract base class for different wire protocols"""

    @abstractmethod
    def serialize_message(self, message: ChatMessage) -> bytes:
        """Convert a ChatMessage to bytes for transmission"""
        pass

    @abstractmethod
    def deserialize_message(self, data: bytes) -> ChatMessage:
        """Convert received bytes to a ChatMessage"""
        pass

    @abstractmethod
    def serialize_response(self, response: ServerResponse) -> bytes:
        """Convert a ServerResponse to bytes for transmission"""
        pass

    @abstractmethod
    def deserialize_response(self, data: bytes) -> ServerResponse:
        """Convert received bytes to a ServerResponse"""
        pass

    @abstractmethod
    def frame_message(self, data: bytes) -> bytes:
        """Add any necessary framing to the message (e.g., length prefix, delimiters)"""
        pass

    @abstractmethod
    def extract_message(self, buffer: bytes) -> tuple[Optional[bytes], bytes]:
        """Extract a complete message from a buffer of bytes, return (message, remaining_buffer)"""
        pass


class JSONProtocol(Protocol):
    """JSON-based protocol implementation using newline as message delimiter"""

    def serialize_message(self, message: ChatMessage) -> bytes:
        return message.model_dump_json().encode()

    def deserialize_message(self, data: bytes) -> ChatMessage:
        return ChatMessage.model_validate_json(data.decode())

    def serialize_response(self, response: ServerResponse) -> bytes:
        return response.model_dump_json().encode()

    def deserialize_response(self, data: bytes) -> ServerResponse:
        return ServerResponse.model_validate_json(data.decode())

    def frame_message(self, data: bytes) -> bytes:
        return data + b"\n"

    def extract_message(self, buffer: bytes) -> tuple[Optional[bytes], bytes]:
        if b"\n" not in buffer:
            return None, buffer
        message, _, remaining = buffer.partition(b"\n")
        return message, remaining


class CustomWireProtocol(Protocol):
    """
    Custom binary wire protocol implementation
    Format:
    [1 byte: message type][4 bytes: message length][N bytes: message payload]

    Message Types:
    0x01: ChatMessage
    0x02: ServerResponse

    Payload format is defined separately for each message type to be as efficient as possible
    """

    MESSAGE_TYPES = {"chat": 0x01, "server_response": 0x02}

    def __init__(self):
        # We'll implement the detailed binary format later
        pass

    def serialize_message(self, message: ChatMessage) -> bytes:
        # Placeholder for custom binary format
        # TODO: Implement efficient binary serialization
        data = json.dumps(message.model_dump()).encode()
        msg_type = self.MESSAGE_TYPES["chat"].to_bytes(1, "big")
        length = len(data).to_bytes(4, "big")
        return msg_type + length + data

    def deserialize_message(self, data: bytes) -> ChatMessage:
        # Placeholder for custom binary format
        # TODO: Implement efficient binary deserialization
        payload = data[5:]  # Skip type and length
        return ChatMessage.model_validate_json(payload.decode())

    def serialize_response(self, response: ServerResponse) -> bytes:
        # Placeholder for custom binary format
        # TODO: Implement efficient binary serialization
        data = json.dumps(response.model_dump()).encode()
        msg_type = self.MESSAGE_TYPES["server_response"].to_bytes(1, "big")
        length = len(data).to_bytes(4, "big")
        return msg_type + length + data

    def deserialize_response(self, data: bytes) -> ServerResponse:
        # Placeholder for custom binary format
        # TODO: Implement efficient binary deserialization
        payload = data[5:]  # Skip type and length
        return ServerResponse.model_validate_json(payload.decode())

    def frame_message(self, data: bytes) -> bytes:
        # No additional framing needed as we use length prefix
        return data

    def extract_message(self, buffer: bytes) -> tuple[Optional[bytes], bytes]:
        if len(buffer) < 5:  # Need at least type and length
            return None, buffer

        msg_length = int.from_bytes(buffer[1:5], "big")
        total_length = msg_length + 5

        if len(buffer) < total_length:
            return None, buffer

        return buffer[:total_length], buffer[total_length:]


class ProtocolFactory:
    """Factory to create protocol instances"""

    @staticmethod
    def create(protocol_type: str) -> Protocol:
        if protocol_type == "json":
            return JSONProtocol()
        elif protocol_type == "custom":
            return CustomWireProtocol()
        else:
            raise ValueError(f"Unknown protocol type: {protocol_type}")


# Example usage:
# protocol = ProtocolFactory.create("json")  # or "custom"
# client = ChatClient(username, protocol=protocol)
# server = ChatServer(protocol=protocol)
