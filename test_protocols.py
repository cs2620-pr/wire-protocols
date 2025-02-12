import unittest
from datetime import datetime
from protocol import JSONProtocol, CustomWireProtocol, Protocol
from schemas import ChatMessage, ServerResponse, MessageType, Status
import random
import string
import io
import sys
from unittest.mock import patch, MagicMock
from typing import List
import threading
import time
import logging


class BaseProtocolTest:
    """Base test class defining the test interface that both protocol implementations must satisfy"""

    def setUp(self):
        """Each implementation should set self.protocol to the appropriate protocol instance"""
        raise NotImplementedError

    def test_message_serialization(self):
        """Test basic message serialization/deserialization"""
        original_msg = ChatMessage(
            username="test_user",
            content="Hello, World!",
            message_type=MessageType.CHAT,
            timestamp=datetime.now(),
        )

        # Serialize
        serialized = self.protocol.serialize_message(original_msg)
        self.assertIsInstance(serialized, bytes)

        # Deserialize
        deserialized = self.protocol.deserialize_message(serialized)
        self.assertEqual(deserialized.username, original_msg.username)
        self.assertEqual(deserialized.content, original_msg.content)
        self.assertEqual(deserialized.message_type, original_msg.message_type)

    def test_dm_message(self):
        """Test direct message serialization with recipients"""
        original_msg = ChatMessage(
            username="sender",
            content="Secret message",
            message_type=MessageType.DM,
            recipients=["recipient"],
            timestamp=datetime.now(),
        )

        serialized = self.protocol.serialize_message(original_msg)
        deserialized = self.protocol.deserialize_message(serialized)

        self.assertEqual(deserialized.recipients, original_msg.recipients)
        self.assertEqual(deserialized.message_type, MessageType.DM)

    def test_server_response(self):
        """Test server response serialization with embedded message"""
        chat_msg = ChatMessage(
            username="system",
            content="User joined",
            message_type=MessageType.JOIN,
            timestamp=datetime.now(),
        )

        original_response = ServerResponse(
            status=Status.SUCCESS, message="Operation successful", data=chat_msg
        )

        serialized = self.protocol.serialize_response(original_response)
        deserialized = self.protocol.deserialize_response(serialized)

        self.assertEqual(deserialized.status, original_response.status)
        self.assertEqual(deserialized.message, original_response.message)
        self.assertEqual(deserialized.data.content, original_response.data.content)

    def test_message_framing(self):
        """Test message framing and extraction"""
        msg1 = ChatMessage(
            username="user1",
            content="First message",
            message_type=MessageType.CHAT,
            timestamp=datetime.now(),
        )
        msg2 = ChatMessage(
            username="user2",
            content="Second message",
            message_type=MessageType.CHAT,
            timestamp=datetime.now(),
        )

        # Create a buffer with multiple messages
        frame1 = self.protocol.frame_message(self.protocol.serialize_message(msg1))
        frame2 = self.protocol.frame_message(self.protocol.serialize_message(msg2))
        buffer = frame1 + frame2

        # Extract first message
        extracted1, remaining = self.protocol.extract_message(buffer)
        self.assertIsNotNone(extracted1)
        decoded1 = self.protocol.deserialize_message(extracted1)
        self.assertEqual(decoded1.content, msg1.content)

        # Extract second message
        extracted2, remaining = self.protocol.extract_message(remaining)
        self.assertIsNotNone(extracted2)
        decoded2 = self.protocol.deserialize_message(extracted2)
        self.assertEqual(decoded2.content, msg2.content)

        # Buffer should be empty now
        self.assertEqual(len(remaining), 0)

    def test_login_message(self):
        """Test login message with password"""
        original_msg = ChatMessage(
            username="new_user",
            content="",
            message_type=MessageType.LOGIN,
            password="secret123",
            timestamp=datetime.now(),
        )

        serialized = self.protocol.serialize_message(original_msg)
        deserialized = self.protocol.deserialize_message(serialized)

        self.assertEqual(deserialized.username, original_msg.username)
        self.assertEqual(deserialized.password, original_msg.password)
        self.assertEqual(deserialized.message_type, MessageType.LOGIN)

    def test_fetch_message(self):
        """Test fetch message with count"""
        original_msg = ChatMessage(
            username="user",
            content="",
            message_type=MessageType.FETCH,
            fetch_count=10,
            timestamp=datetime.now(),
        )

        serialized = self.protocol.serialize_message(original_msg)
        deserialized = self.protocol.deserialize_message(serialized)

        self.assertEqual(deserialized.fetch_count, original_msg.fetch_count)
        self.assertEqual(deserialized.message_type, MessageType.FETCH)

    def test_error_response(self):
        """Test error response without embedded message"""
        original_response = ServerResponse(
            status=Status.ERROR, message="Invalid credentials", data=None
        )

        serialized = self.protocol.serialize_response(original_response)
        deserialized = self.protocol.deserialize_response(serialized)

        self.assertEqual(deserialized.status, Status.ERROR)
        self.assertEqual(deserialized.message, original_response.message)
        self.assertIsNone(deserialized.data)

    def test_active_users(self):
        """Test message with active users list"""
        original_msg = ChatMessage(
            username="system",
            content="User list update",
            message_type=MessageType.LOGIN,
            active_users=["user1", "user2", "user3"],
            timestamp=datetime.now(),
        )

        serialized = self.protocol.serialize_message(original_msg)
        deserialized = self.protocol.deserialize_message(serialized)

        self.assertEqual(deserialized.active_users, original_msg.active_users)

    def test_unread_count(self):
        """Test message with unread count"""
        original_msg = ChatMessage(
            username="system",
            content="You have new messages",
            message_type=MessageType.CHAT,
            unread_count=5,
            timestamp=datetime.now(),
        )

        serialized = self.protocol.serialize_message(original_msg)
        deserialized = self.protocol.deserialize_message(serialized)

        self.assertEqual(deserialized.unread_count, original_msg.unread_count)


class TestJSONProtocol(unittest.TestCase, BaseProtocolTest):
    def setUp(self):
        self.protocol = JSONProtocol()


class TestCustomWireProtocol(unittest.TestCase, BaseProtocolTest):
    def setUp(self):
        self.protocol = CustomWireProtocol()


class TestProtocolEquivalence(unittest.TestCase):
    """Test that both protocols produce equivalent results"""

    def setUp(self):
        self.json_protocol = JSONProtocol()
        self.wire_protocol = CustomWireProtocol()

    def test_functional_equivalence(self):
        """Test that both protocols handle the same message identically"""
        # Create a complex message with all fields
        original_msg = ChatMessage(
            username="test_user",
            content="Test message",
            message_type=MessageType.DM,
            recipients=["recipient1"],
            message_id=123,
            fetch_count=10,
            password="secret",
            active_users=["user1", "user2"],
            unread_count=5,
            timestamp=datetime.now(),
        )

        # Process through both protocols
        json_result = self.json_protocol.deserialize_message(
            self.json_protocol.serialize_message(original_msg)
        )
        wire_result = self.wire_protocol.deserialize_message(
            self.wire_protocol.serialize_message(original_msg)
        )

        # Compare all fields
        self.assertEqual(json_result.username, wire_result.username)
        self.assertEqual(json_result.content, wire_result.content)
        self.assertEqual(json_result.message_type, wire_result.message_type)
        self.assertEqual(json_result.recipients, wire_result.recipients)
        self.assertEqual(json_result.message_id, wire_result.message_id)
        self.assertEqual(json_result.fetch_count, wire_result.fetch_count)
        self.assertEqual(json_result.password, wire_result.password)
        self.assertEqual(json_result.active_users, wire_result.active_users)
        self.assertEqual(json_result.unread_count, wire_result.unread_count)


class StressTest(unittest.TestCase):
    """Stress tests for both protocols"""

    def setUp(self):
        self.json_protocol = JSONProtocol()
        self.wire_protocol = CustomWireProtocol()
        self.protocols = [self.json_protocol, self.wire_protocol]

    def generate_random_string(self, length: int) -> str:
        """Generate a random string of given length"""
        return "".join(
            random.choices(
                string.ascii_letters + string.digits + string.punctuation, k=length
            )
        )

    def test_large_message_handling(self):
        """Test handling of messages at and around size limits"""
        for protocol in self.protocols:
            # Test message just under 1MB
            content = self.generate_random_string(999_000)
            msg = ChatMessage(
                username="test_user",
                content=content,
                message_type=MessageType.CHAT,
                timestamp=datetime.now(),
            )
            serialized = protocol.serialize_message(msg)
            deserialized = protocol.deserialize_message(serialized)
            self.assertEqual(deserialized.content, content)

            # Test message exactly at 1MB
            content = self.generate_random_string(1_000_000)
            msg.content = content
            serialized = protocol.serialize_message(msg)
            deserialized = protocol.deserialize_message(serialized)
            self.assertEqual(deserialized.content, content)

            # Test message exceeding 1MB should raise an error
            content = self.generate_random_string(1_000_001)
            msg.content = content
            with self.assertRaises(Exception):
                protocol.serialize_message(msg)

    def test_unicode_handling(self):
        """Test handling of various Unicode characters"""
        test_strings = [
            "Hello, 世界!",  # Mixed ASCII and CJK
            "🌟 Star",  # Emoji
            "α, β, γ",  # Greek letters
            "∮ E⋅da = Q",  # Mathematical symbols
            "﷽",  # Longest single Unicode character
            "Hello\u200bWorld",  # Zero-width space
            "\u0000Test\u0000",  # Null bytes
            "\r\n\t\b",  # Control characters
        ]

        for protocol in self.protocols:
            for content in test_strings:
                msg = ChatMessage(
                    username=content,  # Test in username too
                    content=content,
                    message_type=MessageType.CHAT,
                    timestamp=datetime.now(),
                )
                serialized = protocol.serialize_message(msg)
                deserialized = protocol.deserialize_message(serialized)
                self.assertEqual(deserialized.content, content)
                self.assertEqual(deserialized.username, content)

    def test_concurrent_message_handling(self):
        """Test concurrent message processing"""
        message_count = 1000
        messages: List[bytes] = []
        results = []
        lock = threading.Lock()

        def worker(protocol: Protocol, start: int, count: int):
            for i in range(start, start + count):
                msg = ChatMessage(
                    username=f"user{i}",
                    content=f"message{i}",
                    message_type=MessageType.CHAT,
                    timestamp=datetime.now(),
                )
                serialized = protocol.serialize_message(msg)
                with lock:
                    messages.append(serialized)
                    results.append((i, msg))

        for protocol in self.protocols:
            messages.clear()
            results.clear()
            threads = []
            chunk_size = message_count // 4

            # Create multiple threads to generate messages
            for i in range(0, message_count, chunk_size):
                t = threading.Thread(target=worker, args=(protocol, i, chunk_size))
                threads.append(t)
                t.start()

            # Wait for all threads to complete
            for t in threads:
                t.join()

            # Verify all messages can be correctly deserialized
            for i, serialized in enumerate(messages):
                deserialized = protocol.deserialize_message(serialized)
                original = next(
                    r[1] for r in results if r[0] == int(deserialized.username[4:])
                )
                self.assertEqual(deserialized.content, original.content)

    def test_malformed_data_handling(self):
        """Test handling of malformed/corrupted data"""
        for protocol in self.protocols:
            # Test empty buffer
            result, remaining = protocol.extract_message(b"")
            self.assertIsNone(result)
            self.assertEqual(remaining, b"")

            # Test partial message
            msg = ChatMessage(
                username="test",
                content="test",
                message_type=MessageType.CHAT,
                timestamp=datetime.now(),
            )
            serialized = protocol.serialize_message(msg)
            for i in range(1, len(serialized)):
                partial = serialized[:i]
                result, remaining = protocol.extract_message(partial)
                self.assertIsNone(result)

            # Test corrupted data
            corrupted = bytearray(serialized)
            for i in range(0, len(corrupted), 10):
                corrupted[i] = random.randint(0, 255)
            with self.assertRaises(Exception):
                protocol.deserialize_message(bytes(corrupted))

    def test_message_chaining(self):
        """Test chaining multiple protocol operations"""
        for protocol in self.protocols:
            # Create a complex chain of operations
            chat_msg = ChatMessage(
                username="user1",
                content="Original message",
                message_type=MessageType.CHAT,
                timestamp=datetime.now(),
            )

            # Chain: message -> server response -> embedded in another response
            serialized_msg = protocol.serialize_message(chat_msg)
            deserialized_msg = protocol.deserialize_message(serialized_msg)

            response1 = ServerResponse(
                status=Status.SUCCESS, message="First response", data=deserialized_msg
            )
            serialized_resp1 = protocol.serialize_response(response1)
            deserialized_resp1 = protocol.deserialize_response(serialized_resp1)

            response2 = ServerResponse(
                status=Status.SUCCESS,
                message="Second response",
                data=deserialized_resp1.data,
            )
            serialized_resp2 = protocol.serialize_response(response2)
            deserialized_resp2 = protocol.deserialize_response(serialized_resp2)

            # Verify the original message is preserved through the chain
            self.assertEqual(deserialized_resp2.data.content, chat_msg.content)

    def test_buffer_overflow_prevention(self):
        """Test prevention of buffer overflow attacks"""
        for protocol in self.protocols:
            # Try to create a message with malicious length prefix
            malicious_data = b"\x00" + (1_000_000_000).to_bytes(4, "big") + b"malicious"
            result, remaining = protocol.extract_message(malicious_data)
            self.assertIsNone(result)  # Should reject the message

            # Try to create a message with inconsistent length
            inconsistent_data = b"\x00" + (100).to_bytes(4, "big") + b"short"
            result, remaining = protocol.extract_message(inconsistent_data)
            self.assertIsNone(result)  # Should reject the message

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_debug_logging(self, mock_stdout):
        """Test debug logging functionality"""
        # Configure logging to use StringIO
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        logger = logging.getLogger()
        logger.addHandler(handler)
        old_level = logger.level
        logger.setLevel(logging.DEBUG)

        try:
            for protocol in self.protocols:
                msg = ChatMessage(
                    username="test",
                    content="test message",
                    message_type=MessageType.CHAT,
                    timestamp=datetime.now(),
                )
                protocol.serialize_message(msg)
                log_output = log_stream.getvalue()

                # Verify debug information is logged
                if isinstance(protocol, JSONProtocol):
                    self.assertIn(
                        "JSONProtocol - Outgoing - ChatMessage (chat)", log_output
                    )
                else:
                    self.assertIn("Serializing message", log_output)
        finally:
            # Clean up logging
            logger.removeHandler(handler)
            logger.setLevel(old_level)

    def test_rapid_message_sequence(self):
        """Test rapid sequence of different message types"""
        for protocol in self.protocols:
            buffer = b""
            messages = []

            # Generate a rapid sequence of different message types
            for i in range(100):
                msg_type = random.choice(list(MessageType))
                msg = ChatMessage(
                    username=f"user{i}",
                    content=f"message{i}",
                    message_type=msg_type,
                    timestamp=datetime.now(),
                    recipients=["recipient"] if msg_type == MessageType.DM else None,
                    password=(
                        "secret"
                        if msg_type in [MessageType.LOGIN, MessageType.REGISTER]
                        else None
                    ),
                    fetch_count=10 if msg_type == MessageType.FETCH else None,
                    active_users=(
                        ["user1", "user2"] if msg_type == MessageType.LOGIN else None
                    ),
                    unread_count=5 if random.random() < 0.5 else None,
                )
                serialized = protocol.frame_message(protocol.serialize_message(msg))
                buffer += serialized
                messages.append(msg)

            # Extract and verify all messages
            extracted_messages = []
            while buffer:
                extracted, buffer = protocol.extract_message(buffer)
                if extracted is None:
                    break
                deserialized = protocol.deserialize_message(extracted)
                extracted_messages.append(deserialized)

            self.assertEqual(len(extracted_messages), len(messages))
            for original, extracted in zip(messages, extracted_messages):
                self.assertEqual(extracted.content, original.content)
                self.assertEqual(extracted.message_type, original.message_type)

    def test_memory_usage(self):
        """Test memory usage with large message sequences"""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        for protocol in self.protocols:
            large_messages = []
            # Create 100 large messages
            for i in range(100):
                msg = ChatMessage(
                    username="test_user",
                    content=self.generate_random_string(100_000),  # 100KB content
                    message_type=MessageType.CHAT,
                    timestamp=datetime.now(),
                )
                serialized = protocol.serialize_message(msg)
                large_messages.append(serialized)

            # Process all messages
            for serialized in large_messages:
                protocol.deserialize_message(serialized)

            # Check memory usage
            current_memory = process.memory_info().rss
            memory_increase = current_memory - initial_memory
            # Ensure memory usage hasn't grown exponentially
            self.assertLess(memory_increase, 500_000_000)  # Less than 500MB increase

    def test_protocol_reuse(self):
        """Test protocol instance reuse with different message types"""
        for protocol in self.protocols:
            # Reuse the same protocol instance for different operations
            for _ in range(100):
                # Randomly choose between message and response
                if random.random() < 0.5:
                    msg = ChatMessage(
                        username="test",
                        content="test",
                        message_type=random.choice(list(MessageType)),
                        timestamp=datetime.now(),
                    )
                    serialized = protocol.serialize_message(msg)
                    deserialized = protocol.deserialize_message(serialized)
                    self.assertEqual(deserialized.content, msg.content)
                else:
                    response = ServerResponse(
                        status=random.choice(list(Status)),
                        message="test response",
                        data=None,
                    )
                    serialized = protocol.serialize_response(response)
                    deserialized = protocol.deserialize_response(serialized)
                    self.assertEqual(deserialized.message, response.message)


if __name__ == "__main__":
    # Disable protocol logging during tests
    from protocol import configure_protocol_logging

    configure_protocol_logging(enabled=False)

    unittest.main()
