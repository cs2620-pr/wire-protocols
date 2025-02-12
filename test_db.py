import pytest
import socket
import threading
import json
import sqlite3
from server import ChatServer
from database import Database
from schemas import ChatMessage, MessageType, SystemMessage, Status, ServerResponse
from protocol import ProtocolFactory
import time
from datetime import datetime, timedelta


@pytest.fixture
def in_memory_db():
    """Create an in-memory database for testing using a shared cache"""
    db = Database(":memory:")  # SQLite in-memory database
    yield db


@pytest.fixture
def shared_db():
    """Create a new Database instance that shares the same in-memory database"""
    return Database(":memory:")


@pytest.fixture
def test_users(in_memory_db):
    """Create test users for use in tests"""
    users = [("alice", "pass1"), ("bob", "pass2"), ("charlie", "pass3")]
    for username, password in users:
        in_memory_db.create_user(username, password)
    return users


def test_user_creation_and_verification(in_memory_db):
    """Test user creation and verification in the database"""
    # Test creating a new user
    username = "testuser"
    password = "testpass123"

    # Create user should succeed
    assert in_memory_db.create_user(username, password) == True

    # Verify the user exists
    assert in_memory_db.user_exists(username) == True

    # Verify correct password works
    assert in_memory_db.verify_user(username, password) == True

    # Verify incorrect password fails
    assert in_memory_db.verify_user(username, "wrongpass") == False

    # Attempt to create duplicate user should fail
    assert in_memory_db.create_user(username, "anotherpass") == False


def test_message_operations(in_memory_db):
    """Test message creation, retrieval, and status updates"""
    # Create test users
    in_memory_db.create_user("sender", "pass1")
    in_memory_db.create_user("recipient", "pass2")

    # Create a test message
    message = ChatMessage(
        username="sender",
        content="Hello, recipient!",
        message_type=MessageType.DM,
        recipients=["recipient"],
        timestamp=datetime.now(),
    )

    # Store message and verify ID is returned
    message_id = in_memory_db.store_message(message)
    assert message_id > 0

    # Test unread message retrieval
    unread = in_memory_db.get_unread_messages("recipient")
    assert len(unread) == 1
    assert unread[0].content == "Hello, recipient!"
    assert unread[0].username == "sender"

    # Test message delivery status
    in_memory_db.mark_delivered(message_id)

    # Test marking message as read
    in_memory_db.mark_read([message_id], "recipient")
    assert len(in_memory_db.get_unread_messages("recipient")) == 0


def test_multiple_messages_and_counts(in_memory_db):
    """Test handling multiple messages and count operations"""
    # Setup users
    in_memory_db.create_user("user1", "pass1")
    in_memory_db.create_user("user2", "pass2")

    # Send multiple messages
    messages = [
        ChatMessage(
            username="user1",
            content=f"Message {i}",
            message_type=MessageType.DM,
            recipients=["user2"],
            timestamp=datetime.now(),
        )
        for i in range(5)
    ]

    message_ids = []
    for msg in messages:
        message_ids.append(in_memory_db.store_message(msg))

    # Test unread count
    assert in_memory_db.get_unread_count("user2") == 5

    # Mark some messages as read
    in_memory_db.mark_read(message_ids[:2], "user2")
    assert in_memory_db.get_unread_count("user2") == 3

    # Test mark_read_from_user
    in_memory_db.mark_read_from_user("user2", "user1")
    assert in_memory_db.get_unread_count("user2") == 0


def test_message_deletion(in_memory_db):
    """Test message deletion functionality"""
    # Setup users and messages
    in_memory_db.create_user("user1", "pass1")
    in_memory_db.create_user("user2", "pass2")

    messages = []
    message_ids = []

    # Create some messages
    for i in range(3):
        msg = ChatMessage(
            username="user1",
            content=f"Message {i}",
            message_type=MessageType.DM,
            recipients=["user2"],
            timestamp=datetime.now(),
        )
        message_ids.append(in_memory_db.store_message(msg))
        messages.append(msg)

    # Test deleting specific messages
    count, info = in_memory_db.delete_messages(message_ids[:2], "user1", "user2")
    assert count == 2  # Should delete 2 messages

    # Verify remaining messages
    remaining = in_memory_db.get_messages_between_users("user1", "user2")
    assert len(remaining) == 1


def test_user_management(in_memory_db):
    """Test user management operations"""
    # Create multiple users
    users = ["user1", "user2", "user3"]
    for user in users:
        assert in_memory_db.create_user(user, "password")

    # Test get_all_users
    all_users = in_memory_db.get_all_users()
    assert len(all_users) == 3
    assert set(all_users) == set(users)

    # Test user deletion
    assert in_memory_db.delete_user("user1")

    # Verify user is deleted
    assert not in_memory_db.user_exists("user1")
    all_users = in_memory_db.get_all_users()
    assert len(all_users) == 2
    assert "user1" not in all_users


def test_conversation_retrieval(in_memory_db):
    """Test retrieving conversations between users"""
    # Setup users
    in_memory_db.create_user("alice", "pass1")
    in_memory_db.create_user("bob", "pass2")

    # Create a conversation
    messages = [
        ("alice", "bob", "Hi Bob!"),
        ("bob", "alice", "Hey Alice!"),
        ("alice", "bob", "How are you?"),
        ("bob", "alice", "I'm good, thanks!"),
    ]

    for sender, recipient, content in messages:
        msg = ChatMessage(
            username=sender,
            content=content,
            message_type=MessageType.DM,
            recipients=[recipient],
            timestamp=datetime.now(),
        )
        in_memory_db.store_message(msg)

    # Test conversation retrieval
    conversation = in_memory_db.get_messages_between_users("alice", "bob")
    assert len(conversation) == 4

    # Test conversation limit
    limited_conv = in_memory_db.get_messages_between_users("alice", "bob", limit=2)
    assert len(limited_conv) == 2


def test_edge_cases(in_memory_db):
    """Test edge cases and error handling"""
    # Test operations with non-existent users
    assert not in_memory_db.user_exists("nonexistent")
    assert not in_memory_db.verify_user("nonexistent", "password")
    assert in_memory_db.get_unread_count("nonexistent") == 0
    assert len(in_memory_db.get_unread_messages("nonexistent")) == 0

    # Test empty message lists
    assert len(in_memory_db.get_messages_between_users("user1", "user2")) == 0

    # Test deleting non-existent messages
    count, info = in_memory_db.delete_messages([999], "user1", "user2")
    assert count == 0

    # Test deleting non-existent user
    assert not in_memory_db.delete_user("nonexistent")


def test_datetime_handling(in_memory_db):
    """Test datetime storage and retrieval"""
    in_memory_db.create_user("sender", "pass")
    in_memory_db.create_user("receiver", "pass")

    # Test messages with different timestamps
    now = datetime.now()
    timestamps = [
        now - timedelta(days=7),  # Week ago
        now - timedelta(hours=24),  # Yesterday
        now,  # Now
        now + timedelta(minutes=30),  # Future
    ]

    message_ids = []
    for i, ts in enumerate(timestamps):
        msg = ChatMessage(
            username="sender",
            content=f"Message at {ts}",
            message_type=MessageType.DM,
            recipients=["receiver"],
            timestamp=ts,
        )
        message_ids.append(in_memory_db.store_message(msg))

    # Verify timestamps are stored and retrieved correctly
    messages = in_memory_db.get_messages_between_users("sender", "receiver")
    assert len(messages) == len(timestamps)

    for msg, expected_ts in zip(messages, timestamps):
        # Compare timestamps (ignoring microseconds for SQLite compatibility)
        assert msg.timestamp.replace(microsecond=0) == expected_ts.replace(
            microsecond=0
        )


def test_message_ordering(in_memory_db, test_users):
    """Test message ordering and retrieval"""
    alice, bob = test_users[:2]

    # Create messages with specific timestamps
    base_time = datetime.now()
    messages = []
    for i in range(5):
        msg_time = base_time + timedelta(minutes=i)
        msg = ChatMessage(
            username=alice[0],
            content=f"Message {i}",
            message_type=MessageType.DM,
            recipients=[bob[0]],
            timestamp=msg_time,
        )
        messages.append(msg)
        in_memory_db.store_message(msg)

    # Test ordering in retrieval
    retrieved = in_memory_db.get_messages_between_users(alice[0], bob[0])
    for i in range(len(retrieved) - 1):
        assert retrieved[i].timestamp <= retrieved[i + 1].timestamp


def test_message_status_transitions(in_memory_db, test_users):
    """Test message status transitions and constraints"""
    alice, bob = test_users[:2]

    # Create test message
    msg = ChatMessage(
        username=alice[0],
        content="Test message",
        message_type=MessageType.DM,
        recipients=[bob[0]],
        timestamp=datetime.now(),
    )
    msg_id = in_memory_db.store_message(msg)

    # Test initial state
    messages = in_memory_db.get_unread_messages(bob[0])
    assert len(messages) == 1
    assert messages[0].message_id == msg_id

    # Test delivery
    in_memory_db.mark_delivered(msg_id)

    # Test read status
    in_memory_db.mark_read([msg_id], bob[0])
    assert len(in_memory_db.get_unread_messages(bob[0])) == 0


def test_user_deletion_cascade(in_memory_db, test_users):
    """Test cascading effects of user deletion"""
    alice, bob, charlie = test_users

    # Create messages between users
    for sender, recipient in [
        (alice[0], bob[0]),
        (bob[0], alice[0]),
        (charlie[0], alice[0]),
    ]:
        msg = ChatMessage(
            username=sender,
            content=f"Message from {sender} to {recipient}",
            message_type=MessageType.DM,
            recipients=[recipient],
            timestamp=datetime.now(),
        )
        in_memory_db.store_message(msg)

    # Delete a user
    assert in_memory_db.delete_user(alice[0])

    # Verify cascade effects
    assert not in_memory_db.user_exists(alice[0])
    assert len(in_memory_db.get_messages_between_users(alice[0], bob[0])) == 0
    assert len(in_memory_db.get_messages_between_users(charlie[0], alice[0])) == 0


def test_performance(in_memory_db, test_users):
    """Test database performance with larger datasets"""
    alice, bob = test_users[:2]
    message_count = 1000

    # Test batch message insertion
    messages = []
    for i in range(message_count):
        msg = ChatMessage(
            username=alice[0],
            content=f"Message {i}",
            message_type=MessageType.DM,
            recipients=[bob[0]],
            timestamp=datetime.now(),
        )
        messages.append(msg)

    # Measure insertion time
    start_time = time.time()
    for msg in messages:
        in_memory_db.store_message(msg)
    insert_time = time.time() - start_time

    # Test retrieval performance with explicit limit
    start_time = time.time()
    retrieved_messages = in_memory_db.get_messages_between_users(
        alice[0], bob[0], limit=message_count
    )
    retrieval_time = time.time() - start_time

    # Verify message count
    assert (
        len(retrieved_messages) == message_count
    ), f"Expected {message_count} messages, got {len(retrieved_messages)}"

    # Performance assertions
    assert insert_time < 5.0, f"Insertion took {insert_time:.2f}s, should be under 5s"
    assert (
        retrieval_time < 1.0
    ), f"Retrieval took {retrieval_time:.2f}s, should be under 1s"

    # Test message ordering
    timestamps = [msg.timestamp for msg in retrieved_messages]
    assert timestamps == sorted(timestamps), "Messages should be in chronological order"
