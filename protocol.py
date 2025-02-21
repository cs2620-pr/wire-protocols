"""Wire protocol implementations for the chat application.

This module provides protocol implementations for serializing and deserializing
chat messages between client and server. It includes:
- Abstract Protocol base class defining the interface
- JSONProtocol implementation using JSON serialization with newline delimiters
- CustomWireProtocol implementation using binary format for efficiency
- Protocol metrics logging functionality
"""

from abc import ABC, abstractmethod
import json
from typing import Optional, Tuple
from schemas import ChatMessage, ServerResponse, MessageType, Status
import logging
import os

# Set up logging with a NullHandler by default
protocol_logger = logging.getLogger("protocol_metrics")
protocol_logger.addHandler(logging.NullHandler())


def configure_protocol_logging(
    enabled: bool = False, log_file: str = "protocol_metrics.log"
):
    """Configure protocol metrics logging.

    Args:
        enabled: Whether to enable logging
        log_file: Path to the log file relative to the logs directory

    The function:
    1. Creates a logs directory if it doesn't exist
    2. Sets up file logging if enabled
    3. Suppresses logs if disabled
    """
    global protocol_logger
    protocol_logger.handlers.clear()  # Remove existing handlers

    if enabled:
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        handler = logging.FileHandler(os.path.join(log_dir, log_file))
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        protocol_logger.setLevel(logging.INFO)
        protocol_logger.addHandler(handler)
    else:
        protocol_logger.addHandler(logging.NullHandler())
        protocol_logger.setLevel(logging.WARNING)  # Suppress most logs


class Protocol(ABC):
    """Abstract base class defining the wire protocol interface.

    This class defines the required methods that any protocol implementation
    must provide for serializing and deserializing chat messages.

    Attributes:
        protocol_name (str): Name of the protocol implementation
    """

    def __init__(self):
        """Initialize the protocol with its class name."""
        self.protocol_name = self.__class__.__name__

    def log_message_size(
        self, message_type: str, data: bytes, direction: str, specific_type: str = ""
    ):
        """Log metrics about message sizes.

        Args:
            message_type: Type of message (ChatMessage or ServerResponse)
            data: The serialized message bytes
            direction: Message direction (Incoming or Outgoing)
            specific_type: Specific message subtype (e.g., LOGIN, CHAT)
        """
        size = len(data)
        protocol_logger.info(
            f"{self.protocol_name} - {direction} - {message_type}{f' ({specific_type})' if specific_type else ''} - Size: {size} bytes"
        )

    @abstractmethod
    def serialize_message(self, message: ChatMessage, should_log: bool = True) -> bytes:
        """Convert a ChatMessage to bytes for transmission.

        Args:
            message: The ChatMessage to serialize
            should_log: Whether to log message metrics

        Returns:
            bytes: The serialized message
        """
        pass

    @abstractmethod
    def deserialize_message(self, data: bytes, should_log: bool = True) -> ChatMessage:
        """Convert received bytes to a ChatMessage.

        Args:
            data: The received bytes to deserialize
            should_log: Whether to log message metrics

        Returns:
            ChatMessage: The deserialized message
        """
        pass

    @abstractmethod
    def serialize_response(
        self, response: ServerResponse, should_log: bool = True
    ) -> bytes:
        """Convert a ServerResponse to bytes for transmission.

        Args:
            response: The ServerResponse to serialize
            should_log: Whether to log message metrics

        Returns:
            bytes: The serialized response
        """
        pass

    @abstractmethod
    def deserialize_response(
        self, data: bytes, should_log: bool = True
    ) -> ServerResponse:
        """Convert received bytes to a ServerResponse.

        Args:
            data: The received bytes to deserialize
            should_log: Whether to log message metrics

        Returns:
            ServerResponse: The deserialized response
        """
        pass

    @abstractmethod
    def frame_message(self, data: bytes) -> bytes:
        """Add message framing for transmission.

        Args:
            data: The message data to frame

        Returns:
            bytes: The framed message ready for transmission
        """
        pass

    @abstractmethod
    def extract_message(self, buffer: bytes) -> tuple[Optional[bytes], bytes]:
        """Extract a complete message from a buffer of received bytes.

        Args:
            buffer: Buffer containing received bytes

        Returns:
            tuple: (message_data, remaining_buffer)
            - message_data: Complete message if one was extracted, None otherwise
            - remaining_buffer: Remaining bytes in buffer after extraction
        """
        pass


class JSONProtocol(Protocol):
    """JSON-based protocol implementation using newline delimiters.

    This protocol:
    - Serializes messages as JSON
    - Uses newlines as message delimiters
    - Enforces message size limits
    - Provides human-readable message format
    """

    def serialize_message(self, message: ChatMessage, should_log: bool = True) -> bytes:
        """Serialize a ChatMessage to JSON bytes.

        Args:
            message: The ChatMessage to serialize
            should_log: Whether to log message metrics

        Returns:
            bytes: JSON-encoded message

        Raises:
            ValueError: If message content exceeds size limit
        """
        # Add size check at the beginning
        content_size = len(message.content.encode("utf-8"))
        if content_size > 1_000_000:  # 1MB limit
            raise ValueError("Message content exceeds 1MB limit")

        data = message.model_dump_json().encode()
        if should_log:
            self.log_message_size(
                "ChatMessage", data, "Outgoing", message.message_type.value
            )
        return data

    def deserialize_message(self, data: bytes, should_log: bool = True) -> ChatMessage:
        """Deserialize JSON bytes to a ChatMessage.

        Args:
            data: The JSON bytes to deserialize
            should_log: Whether to log message metrics

        Returns:
            ChatMessage: The deserialized message

        Raises:
            ValueError: If message content exceeds size limit
        """
        msg = ChatMessage.model_validate_json(data.decode())

        # Check content size after deserialization
        content_size = len(msg.content.encode("utf-8"))
        if content_size > 1_000_000:  # 1MB limit
            raise ValueError("Message content exceeds 1MB limit")

        if should_log:
            self.log_message_size(
                "ChatMessage", data, "Incoming", msg.message_type.value
            )
        return msg

    def serialize_response(
        self, response: ServerResponse, should_log: bool = True
    ) -> bytes:
        """Serialize a ServerResponse to JSON bytes.

        Args:
            response: The ServerResponse to serialize
            should_log: Whether to log message metrics

        Returns:
            bytes: JSON-encoded response
        """
        data = response.model_dump_json().encode()
        if should_log:
            msg_type = response.data.message_type.value if response.data else "NO_DATA"
            self.log_message_size("ServerResponse", data, "Outgoing", msg_type)
        return data

    def deserialize_response(
        self, data: bytes, should_log: bool = True
    ) -> ServerResponse:
        """Deserialize JSON bytes to a ServerResponse.

        Args:
            data: The JSON bytes to deserialize
            should_log: Whether to log message metrics

        Returns:
            ServerResponse: The deserialized response
        """
        resp = ServerResponse.model_validate_json(data.decode())
        if should_log:
            msg_type = resp.data.message_type.value if resp.data else "NO_DATA"
            self.log_message_size("ServerResponse", data, "Incoming", msg_type)
        return resp

    def frame_message(self, data: bytes) -> bytes:
        """Add newline delimiter to message.

        Args:
            data: Message data to frame

        Returns:
            bytes: Message with newline delimiter
        """
        return data + b"\n"

    def extract_message(self, buffer: bytes) -> tuple[Optional[bytes], bytes]:
        """Extract a newline-delimited message from the buffer.

        Args:
            buffer: Buffer containing received bytes

        Returns:
            tuple: (message_data, remaining_buffer)
            - message_data: Complete message if newline found, None otherwise
            - remaining_buffer: Remaining bytes after newline
        """
        if b"\n" not in buffer:
            return None, buffer
        message, _, remaining = buffer.partition(b"\n")
        return message, remaining


import struct
from datetime import datetime
from typing import Optional, Tuple
from schemas import ChatMessage, ServerResponse, MessageType, Status
from protocol import Protocol


class CustomWireProtocol(Protocol):
    """Custom binary wire protocol implementation for efficient message transmission.

    This protocol uses a compact binary format with the following structure:
    Overall frame:
      [1 byte: message type][4 bytes: payload length][payload]

    Message Types (header byte values, dynamically assigned based on MessageType enum order):
      0x00: MessageType.SERVER_RESPONSE
      0x01: MessageType.LOGIN
      0x02: MessageType.LOGOUT
      0x03: MessageType.JOIN
      0x04: MessageType.REGISTER
      0x05: MessageType.CHAT
      0x06: MessageType.DM
      0x07: MessageType.FETCH
      0x08: MessageType.MARK_READ
      0x09: MessageType.DELETE
      0x0A: MessageType.DELETE_NOTIFICATION
      0x0B: MessageType.DELETE_ACCOUNT

    Attributes:
        MESSAGE_TYPES (dict): Maps message type names to byte values
        REVERSE_MESSAGE_TYPES (dict): Maps byte values to message type names
    """

    def __init__(self):
        """Initialize protocol with message type mappings."""
        super().__init__()
        # Create mapping from message type value (lowercase) to hex byte value
        self.MESSAGE_TYPES = {
            message_type.value.lower(): i for i, message_type in enumerate(MessageType)
        }
        # Create reverse mapping for deserialization (hex byte value to message type)
        self.REVERSE_MESSAGE_TYPES = {v: k for k, v in self.MESSAGE_TYPES.items()}
        # Log the actual message type mappings for debugging
        protocol_logger.debug("Initialized message type mappings:")
        for msg_type, hex_val in self.MESSAGE_TYPES.items():
            protocol_logger.debug(f"  {hex_val}: {msg_type}")

    def serialize_string(self, s: str) -> bytes:
        """Serialize a string to length-prefixed bytes.

        Format: [4 bytes: length][N bytes: UTF-8 data]

        Args:
            s: String to serialize

        Returns:
            bytes: Length-prefixed UTF-8 encoded string
        """
        encoded = s.encode("utf-8")
        length = len(encoded)
        protocol_logger.debug(f"Serializing string: length={length}, content='{s}'")
        return struct.pack("!I", length) + encoded

    def deserialize_string(self, data: bytes, offset: int) -> Tuple[str, int]:
        """Deserialize a length-prefixed string from bytes.

        Args:
            data: Bytes containing the string
            offset: Starting position in the bytes

        Returns:
            tuple: (string, new_offset)
            - string: The deserialized string
            - new_offset: Position after the string in the bytes
        """
        length = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        s = data[offset : offset + length].decode("utf-8")
        protocol_logger.debug(
            f"Deserialized string: offset={offset-4}, length={length}, content='{s}'"
        )
        offset += length
        return s, offset

    def serialize_message(self, message: ChatMessage, should_log: bool = True) -> bytes:
        """Serialize a ChatMessage to binary format.

        The message format includes:
        Header:
          1. message_type: 1 byte
          2. payload_length: 4 bytes
        Payload:
          1. message_id: 4 bytes (0 means None)
          2. username: length-prefixed string
          3. content: length-prefixed string
          4. timestamp: 8 bytes (double; seconds since epoch)
          5. recipients: 1 byte count, then each as a length-prefixed string
          6. fetch_count: 4 bytes (0 if not set)
          7. password: length-prefixed string (empty if None)
          8. active_users: 1 byte count, then each as a length-prefixed string
          9. unread_count: 4 bytes (0 if not set)

        Args:
            message: The ChatMessage to serialize
            should_log: Whether to log message metrics

        Returns:
            bytes: The serialized message

        Raises:
            ValueError: If message content exceeds size limit
        """
        # Add size check at the beginning
        content_size = len(message.content.encode("utf-8"))
        if content_size > 1_000_000:  # 1MB limit
            raise ValueError("Message content exceeds 1MB limit")

        msg_type_key = message.message_type.value.lower()
        if msg_type_key not in self.MESSAGE_TYPES:
            protocol_logger.debug(
                f"Unknown message type '{msg_type_key}', defaulting to 'chat'."
            )
            msg_type_key = MessageType.CHAT.value.lower()
        header_type = self.MESSAGE_TYPES[msg_type_key].to_bytes(1, "big")
        protocol_logger.debug(
            f"Serializing message of type '{message.message_type.value}' as header byte: {header_type.hex()}"
        )

        payload = b""
        # 1. message_id
        msg_id = message.message_id if message.message_id is not None else 0
        payload += struct.pack("!I", msg_id)
        protocol_logger.debug(f"Serialized message_id: {msg_id}")
        # 2. username
        payload += self.serialize_string(message.username)
        # 3. content
        payload += self.serialize_string(message.content)
        # 4. timestamp
        ts = message.timestamp.timestamp()
        payload += struct.pack("!d", ts)
        protocol_logger.debug(f"Serialized timestamp: {ts} (from {message.timestamp})")
        # 5. recipients
        recipients = message.recipients if message.recipients else []
        payload += struct.pack("!B", len(recipients))
        protocol_logger.debug(f"Serialized {len(recipients)} recipient(s).")
        for recipient in recipients:
            payload += self.serialize_string(recipient)
        # 6. fetch_count
        fetch_count = message.fetch_count if message.fetch_count is not None else 0
        payload += struct.pack("!I", fetch_count)
        protocol_logger.debug(f"Serialized fetch_count: {fetch_count}")
        # 7. password
        password_str = message.password if message.password is not None else ""
        payload += self.serialize_string(password_str)
        protocol_logger.debug(f"Serialized password: '{password_str}'")
        # 8. active_users
        active_users = message.active_users if message.active_users else []
        payload += struct.pack("!B", len(active_users))
        protocol_logger.debug(f"Serialized {len(active_users)} active user(s).")
        for user in active_users:
            payload += self.serialize_string(user)
        # 9. unread_count
        unread = message.unread_count if message.unread_count is not None else 0
        payload += struct.pack("!I", unread)
        protocol_logger.debug(f"Serialized unread_count: {unread}")

        payload_length = len(payload)
        protocol_logger.debug(f"Total payload length: {payload_length} bytes")
        length_bytes = payload_length.to_bytes(4, "big")
        final_message = header_type + length_bytes + payload
        protocol_logger.debug(
            f"Final serialized message length: {len(final_message)} bytes"
        )
        if should_log:
            self.log_message_size(
                "ChatMessage", final_message, "Outgoing", message.message_type.value
            )
        return final_message

    def deserialize_message(self, data: bytes, should_log: bool = True) -> ChatMessage:
        """Deserialize a binary message to ChatMessage.

        Args:
            data: The binary data to deserialize
            should_log: Whether to log message metrics

        Returns:
            ChatMessage: The deserialized message
        """
        header_type = data[0]
        msg_type_str = self.REVERSE_MESSAGE_TYPES.get(
            header_type, MessageType.CHAT.value.lower()
        )
        # Only log if this is actually a ChatMessage type (not a ServerResponse)
        is_chat_message = msg_type_str != "server_response"
        protocol_logger.debug(
            f"Deserializing message with header byte: {header_type:#04x} mapped to type '{msg_type_str}'"
        )
        offset = 5  # Skip header.
        # 1. message_id
        msg_id = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        protocol_logger.debug(f"Deserialized message_id: {msg_id}")
        # 2. username
        username, offset = self.deserialize_string(data, offset)
        # 3. content
        content, offset = self.deserialize_string(data, offset)
        # 4. timestamp
        ts = struct.unpack_from("!d", data, offset)[0]
        offset += 8
        timestamp = datetime.fromtimestamp(ts)
        protocol_logger.debug(f"Deserialized timestamp: {ts} -> {timestamp}")
        # 5. recipients
        rec_count = struct.unpack_from("!B", data, offset)[0]
        offset += 1
        protocol_logger.debug(f"Deserialized recipient count: {rec_count}")
        recipients = []
        for _ in range(rec_count):
            rec, offset = self.deserialize_string(data, offset)
            recipients.append(rec)
        # 6. fetch_count
        fetch_count = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        protocol_logger.debug(f"Deserialized fetch_count: {fetch_count}")
        # 7. password
        password, offset = self.deserialize_string(data, offset)
        protocol_logger.debug(f"Deserialized password: '{password}'")
        # 8. active_users
        active_count = struct.unpack_from("!B", data, offset)[0]
        offset += 1
        protocol_logger.debug(f"Deserialized active user count: {active_count}")
        active_users = []
        for _ in range(active_count):
            user, offset = self.deserialize_string(data, offset)
            active_users.append(user)
        # 9. unread_count
        unread = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        protocol_logger.debug(f"Deserialized unread_count: {unread}")

        msg = ChatMessage(
            message_id=msg_id if msg_id != 0 else None,
            message_type=MessageType(msg_type_str),
            username=username,
            content=content,
            timestamp=timestamp,
            recipients=recipients if recipients else None,
            fetch_count=fetch_count if fetch_count != 0 else None,
            password=password if password != "" else None,
            active_users=active_users if active_users else None,
            unread_count=unread if unread != 0 else None,
        )
        if should_log and is_chat_message:
            self.log_message_size(
                "ChatMessage", data, "Incoming", msg.message_type.value
            )
        return msg

    def serialize_response(
        self, response: ServerResponse, should_log: bool = True
    ) -> bytes:
        """Serialize a ServerResponse to binary format.

        The response format includes:
        Payload:
          1. status: 1 byte (0 for SUCCESS, 1 for ERROR)
          2. message: length-prefixed string
          3. unread_count: 4 bytes (0 if not set)
          4. data flag: 1 byte (1 if response.data exists, 0 otherwise)
          5. (if data flag == 1) an embedded ChatMessage

        Args:
            response: The ServerResponse to serialize
            should_log: Whether to log message metrics

        Returns:
            bytes: The serialized response
        """
        header_type = self.MESSAGE_TYPES["server_response"].to_bytes(1, "big")
        protocol_logger.debug(
            f"Serializing ServerResponse with header byte: {header_type.hex()}"
        )
        payload = b""
        # 1. status
        status_val = 0 if response.status == Status.SUCCESS else 1
        payload += struct.pack("!B", status_val)
        protocol_logger.debug(
            f"Serialized response status: {response.status} as {status_val}"
        )
        # 2. message
        payload += self.serialize_string(response.message)
        # 3. unread_count
        unread = response.unread_count if response.unread_count is not None else 0
        payload += struct.pack("!I", unread)
        protocol_logger.debug(f"Serialized unread_count: {unread}")
        # 4. data flag and embedded ChatMessage if present.
        if response.data is not None:
            payload += struct.pack("!B", 1)
            chat_bytes = self.serialize_message(response.data, should_log=False)
            protocol_logger.debug(
                f"Serialized embedded ChatMessage of length {len(chat_bytes)} bytes"
            )
            payload += chat_bytes
        else:
            payload += struct.pack("!B", 0)
            protocol_logger.debug(f"No embedded ChatMessage in response.")

        length_bytes = len(payload).to_bytes(4, "big")
        final_response = header_type + length_bytes + payload
        protocol_logger.debug(
            f"Final serialized response length: {len(final_response)} bytes"
        )
        msg_type = response.data.message_type.value if response.data else "NO_DATA"
        if should_log:
            self.log_message_size(
                "ServerResponse", final_response, "Outgoing", msg_type
            )
        return final_response

    def deserialize_response(
        self, data: bytes, should_log: bool = True
    ) -> ServerResponse:
        """Deserialize binary data to ServerResponse.

        Args:
            data: The binary data to deserialize
            should_log: Whether to log message metrics

        Returns:
            ServerResponse: The deserialized response
        """
        protocol_logger.debug(
            f"Deserializing ServerResponse from data length: {len(data)} bytes"
        )
        offset = 5  # Skip header.
        # 1. status
        status_val = struct.unpack_from("!B", data, offset)[0]
        offset += 1
        status = Status.SUCCESS if status_val == 0 else Status.ERROR
        protocol_logger.debug(
            f"Deserialized response status: {status} (raw value: {status_val})"
        )
        # 2. message
        message, offset = self.deserialize_string(data, offset)
        # 3. unread_count
        unread = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        protocol_logger.debug(f"Deserialized unread_count: {unread}")
        # 4. data flag
        flag = struct.unpack_from("!B", data, offset)[0]
        offset += 1
        chat_data = None
        if flag == 1:
            # The remaining bytes should contain a full ChatMessage.
            embedded, _ = self.extract_message(data[offset:])
            if embedded is not None:
                chat_data = self.deserialize_message(embedded, should_log=False)
                protocol_logger.debug(f"Deserialized embedded ChatMessage.")
            else:
                protocol_logger.debug(
                    f"Data flag set but unable to extract embedded ChatMessage."
                )
        else:
            protocol_logger.debug(f"No embedded ChatMessage in response.")

        resp = ServerResponse(
            status=status,
            message=message,
            unread_count=unread if unread != 0 else None,
            data=chat_data,
        )
        if should_log:
            msg_type = resp.data.message_type.value if resp.data else "NO_DATA"
            self.log_message_size("ServerResponse", data, "Incoming", msg_type)
        return resp

    def frame_message(self, data: bytes) -> bytes:
        """Return the data as-is since framing is included in serialization.

        Args:
            data: The message data

        Returns:
            bytes: The same data (already framed)
        """
        protocol_logger.debug(f"Framing message: total length {len(data)} bytes")
        return data

    def extract_message(self, buffer: bytes) -> Tuple[Optional[bytes], bytes]:
        """Extract a complete message from the buffer.

        Messages are expected to be in the format:
        [1 byte: type][4 bytes: payload length][payload]

        Args:
            buffer: Buffer containing received bytes

        Returns:
            tuple: (message_data, remaining_buffer)
            - message_data: Complete message if one was extracted, None otherwise
            - remaining_buffer: Remaining bytes in buffer after extraction
        """
        if len(buffer) < 5:
            protocol_logger.debug(
                f"Buffer too short to extract header: {len(buffer)} bytes."
            )
            return None, buffer
        else:
            protocol_logger.debug(f"Buffer length: {len(buffer)} bytes.")

        # Validate message type byte
        msg_type = buffer[0]
        if msg_type not in self.REVERSE_MESSAGE_TYPES:
            protocol_logger.debug(f"Invalid message type byte: {msg_type}")
            return None, buffer[1:]  # Skip the invalid byte

        # Extract and validate payload length
        payload_length = int.from_bytes(buffer[1:5], "big")
        if payload_length > 1_000_000:  # 1MB max message size
            protocol_logger.debug(f"Invalid payload length: {payload_length} bytes")
            return None, buffer[5:]  # Skip the header

        total_length = 1 + 4 + payload_length
        if len(buffer) < total_length:
            protocol_logger.debug(
                f"Buffer incomplete: expected {total_length} bytes, have {len(buffer)} bytes."
            )
            return None, buffer

        protocol_logger.debug(
            f"Extracted message of total length {total_length} bytes from buffer."
        )
        return buffer[:total_length], buffer[total_length:]


class ProtocolFactory:
    """Factory class for creating protocol instances.

    This class provides a single static method for creating protocol
    instances based on the requested protocol type.
    """

    @staticmethod
    def create(protocol_type: str) -> Protocol:
        """Create a protocol instance of the specified type.

        Args:
            protocol_type: Type of protocol to create ("json" or "custom")

        Returns:
            Protocol: The created protocol instance

        Raises:
            ValueError: If protocol_type is not recognized
        """
        if protocol_type == "json":
            return JSONProtocol()
        elif protocol_type == "custom":
            return CustomWireProtocol()
        else:
            raise ValueError(f"Unknown protocol type: {protocol_type}")
