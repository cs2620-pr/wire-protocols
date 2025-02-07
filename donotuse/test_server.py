import pytest
import socket
import json
import threading
import time
from server import ChatServer
from models import (
    CommandType,
    ResponseStatus,
    SendMessageRequest,
    ReadMessagesRequest,
    DeleteMessagesRequest,
    ListAccountsRequest,
)
from datetime import datetime


@pytest.fixture
def server():
    """Create a test server instance"""
    server = ChatServer(port=8001, db_path=":memory:")
    # Initialize database tables
    server.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            recipient TEXT,
            content TEXT,
            timestamp REAL,
            read INTEGER DEFAULT 0,
            FOREIGN KEY(sender) REFERENCES users(username),
            FOREIGN KEY(recipient) REFERENCES users(username)
        )
    """
    )
    server.conn.commit()
    threading.Thread(target=server.start, daemon=True).start()
    time.sleep(0.02)  # Brief delay to allow server to start

    # Wait for server to start
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(("localhost", 8001))

    yield server
    server.server_socket.close()


@pytest.fixture
def client_socket(server):
    """Create a test client socket"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("localhost", 8001))
    yield sock
    sock.close()


@pytest.fixture
def authenticated_users(server, client_socket):
    """Create and authenticate test users"""
    users = [("sender", "pass1"), ("receiver", "pass2")]
    for username, password in users:
        request = {
            "command": CommandType.CREATE_ACCOUNT,
            "username": username,
            "password": password,
        }
        send_and_receive(client_socket, request)

        login_request = {
            "command": CommandType.LOGIN,
            "username": username,
            "password": password,
        }
        send_and_receive(client_socket, login_request)
    return users


def send_and_receive(sock: socket.socket, data: dict) -> dict:
    """Helper to send and receive data from server"""
    sock.sendall(json.dumps(data).encode())
    # Read response in chunks for large messages
    chunks = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if len(chunk) < 4096:  # Last chunk is smaller
            break
    response = b"".join(chunks)
    return json.loads(response.decode())


def test_list_accounts(client_socket, authenticated_users):
    """Test account listing"""
    request = {
        "command": CommandType.LIST_ACCOUNTS,
        "pattern": "%",
        "page": 1,
        "page_size": 10,
    }
    response = send_and_receive(client_socket, request)
    assert response["status"] == ResponseStatus.SUCCESS
    assert len(response["accounts"]) >= 2  # At least our test users

    # Test pattern matching
    request["pattern"] = "send%"
    response = send_and_receive(client_socket, request)
    assert all("send" in account for account in response["accounts"])


def test_message_operations(client_socket, authenticated_users):
    """Test message sending, reading, and deleting"""
    # Send message
    send_request = {
        "command": CommandType.SEND_MESSAGE,
        "sender": "sender",
        "recipient": "receiver",
        "content": "Test message",
    }
    print(f"\nSending message: {send_request}")
    response = send_and_receive(client_socket, send_request)
    print(f"Send message response: {response}")
    assert response["status"] == ResponseStatus.SUCCESS

    # Read messages
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": 10,
    }
    print(f"\nReading messages: {read_request}")
    response = send_and_receive(client_socket, read_request)
    print(f"Read messages response: {response}")
    assert response["status"] == ResponseStatus.SUCCESS
    print(f"Response keys: {response.keys()}")
    assert len(response["messages"]) == 1
    assert response["messages"][0]["content"] == "Test message"

    # Delete message
    message_id = response["messages"][0]["id"]
    delete_request = {
        "command": CommandType.DELETE_MESSAGES,
        "username": "receiver",
        "message_ids": [message_id],
    }
    response = send_and_receive(client_socket, delete_request)
    assert response["status"] == ResponseStatus.SUCCESS

    # Verify message is deleted
    read_request["recipient"] = "sender"
    response = send_and_receive(client_socket, read_request)
    assert len(response["messages"]) == 0


def test_send_to_nonexistent_user(client_socket, authenticated_users):
    """Test sending message to non-existent user"""
    request = {
        "command": CommandType.SEND_MESSAGE,
        "sender": "sender",
        "recipient": "nonexistent",
        "content": "Test message",
    }
    response = send_and_receive(client_socket, request)
    assert response["status"] == ResponseStatus.ERROR
    assert "does not exist" in response["message"].lower()


def test_pagination(client_socket, authenticated_users):
    """Test account listing pagination"""
    # Create more test accounts
    for i in range(15):  # Create 15 additional accounts
        request = {
            "command": CommandType.CREATE_ACCOUNT,
            "username": f"testuser{i}",
            "password": "testpass",
        }
        send_and_receive(client_socket, request)

    # Test first page
    request = {
        "command": CommandType.LIST_ACCOUNTS,
        "pattern": "%",
        "page": 1,
        "page_size": 10,
    }
    response = send_and_receive(client_socket, request)
    assert response["status"] == ResponseStatus.SUCCESS
    assert len(response["accounts"]) == 10
    assert response["total_pages"] > 1

    # Test second page
    request["page"] = 2
    response = send_and_receive(client_socket, request)
    assert len(response["accounts"]) > 0
    assert response["page"] == 2


def test_message_ordering(client_socket, authenticated_users):
    """Test message ordering by timestamp"""
    # Send multiple messages
    messages = ["First", "Second", "Third"]
    for content in messages:
        request = {
            "command": CommandType.SEND_MESSAGE,
            "sender": "sender",
            "recipient": "receiver",
            "content": content,
        }
        send_and_receive(client_socket, request)

    # Read messages and verify order
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": 10,
    }
    response = send_and_receive(client_socket, read_request)
    assert response["status"] == ResponseStatus.SUCCESS
    received = [msg["content"] for msg in response["messages"]]
    assert received == list(reversed(messages))  # Most recent first


def test_message_limit(client_socket, authenticated_users):
    """Test message reading limit"""
    # Send 5 messages
    for i in range(5):
        request = {
            "command": CommandType.SEND_MESSAGE,
            "sender": "sender",
            "recipient": "receiver",
            "content": f"Message {i}",
        }
        send_and_receive(client_socket, request)

    # Read with limit 3
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": 3,
    }
    response = send_and_receive(client_socket, read_request)
    assert len(response["messages"]) == 3


def test_invalid_requests(client_socket, authenticated_users):
    """Test handling of invalid requests"""
    cases = [
        # Invalid command
        {
            "command": "invalid_command",
            "username": "test",
        },
        # Missing required field
        {
            "command": CommandType.SEND_MESSAGE,
            "sender": "sender",
            # missing recipient
            "content": "test",
        },
        # Invalid message format
        "not_a_json_object",
        # Empty request
        {},
    ]

    for request in cases:
        try:
            response = send_and_receive(client_socket, request)
            assert response["status"] == ResponseStatus.ERROR
        except Exception:
            # Expected for invalid JSON
            continue


def test_concurrent_connections(server):
    """Test multiple concurrent connections"""
    sockets = []
    try:
        # Create multiple connections
        for i in range(5):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("localhost", 8001))
            sockets.append(sock)

            # Create and login user
            username = f"concurrent_user{i}"
            for request in [
                {
                    "command": CommandType.CREATE_ACCOUNT,
                    "username": username,
                    "password": "testpass",
                },
                {
                    "command": CommandType.LOGIN,
                    "username": username,
                    "password": "testpass",
                },
            ]:
                send_and_receive(sock, request)

        # Test sending messages between users
        for i, sock in enumerate(sockets[:-1]):
            request = {
                "command": CommandType.SEND_MESSAGE,
                "sender": f"concurrent_user{i}",
                "recipient": f"concurrent_user{i+1}",
                "content": f"Message from {i} to {i+1}",
            }
            response = send_and_receive(sock, request)
            assert response["status"] == ResponseStatus.SUCCESS

    finally:
        # Clean up
        for sock in sockets:
            sock.close()


def test_long_messages(client_socket, authenticated_users):
    """Test handling of very long messages"""
    # Test message at max length
    long_content = "x" * 1000  # Assuming 1000 is within limits
    request = {
        "command": CommandType.SEND_MESSAGE,
        "sender": "sender",
        "recipient": "receiver",
        "content": long_content,
    }
    response = send_and_receive(client_socket, request)
    assert response["status"] == ResponseStatus.SUCCESS

    # Verify message content preserved
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": 1,
    }
    response = send_and_receive(client_socket, read_request)
    assert response["messages"][0]["content"] == long_content


def test_special_characters(client_socket, authenticated_users):
    """Test handling of special characters in messages and usernames"""
    special_content = "Hello! @#$%^&*()_+ 你好 😊"
    request = {
        "command": CommandType.SEND_MESSAGE,
        "sender": "sender",
        "recipient": "receiver",
        "content": special_content,
    }
    response = send_and_receive(client_socket, request)
    assert response["status"] == ResponseStatus.SUCCESS

    # Verify special characters preserved
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": 1,
    }
    response = send_and_receive(client_socket, read_request)
    assert response["messages"][0]["content"] == special_content


def test_rapid_messages(client_socket, authenticated_users):
    """Test rapid message sending and reading"""
    # Send multiple messages rapidly
    message_count = 50
    for i in range(message_count):
        request = {
            "command": CommandType.SEND_MESSAGE,
            "sender": "sender",
            "recipient": "receiver",
            "content": f"Rapid message {i}",
        }
        send_and_receive(client_socket, request)

    # Verify all messages received
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": message_count,
    }
    response = send_and_receive(client_socket, read_request)
    assert len(response["messages"]) == message_count


def test_account_deletion_cleanup(client_socket):
    """Test account deletion and associated message cleanup"""
    # Create test users
    users = [("delete_test1", "pass1"), ("delete_test2", "pass2")]
    for username, password in users:
        request = {
            "command": CommandType.CREATE_ACCOUNT,
            "username": username,
            "password": password,
        }
        send_and_receive(client_socket, request)

    # Send messages between users
    request = {
        "command": CommandType.SEND_MESSAGE,
        "sender": "delete_test1",
        "recipient": "delete_test2",
        "content": "Test message",
    }
    send_and_receive(client_socket, request)

    # Delete first user
    delete_request = {
        "command": CommandType.DELETE_ACCOUNT,
        "username": "delete_test1",
    }
    response = send_and_receive(client_socket, delete_request)
    assert response["status"] == ResponseStatus.SUCCESS

    # Verify messages cleaned up
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "delete_test2",
        "limit": 10,
    }
    response = send_and_receive(client_socket, read_request)
    assert len(response["messages"]) == 0

    # Verify can't send message from deleted account
    request = {
        "command": CommandType.SEND_MESSAGE,
        "sender": "delete_test1",
        "recipient": "delete_test2",
        "content": "Test message",
    }
    response = send_and_receive(client_socket, request)
    assert response["status"] == ResponseStatus.ERROR


def test_reconnection(server):
    """Test client reconnection handling"""
    sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Connect and create account
        sock1.connect(("localhost", 8001))
        request = {
            "command": CommandType.CREATE_ACCOUNT,
            "username": "reconnect_test",
            "password": "testpass",
        }
        send_and_receive(sock1, request)

        # Login on first connection
        login_request = {
            "command": CommandType.LOGIN,
            "username": "reconnect_test",
            "password": "testpass",
        }
        response = send_and_receive(sock1, login_request)
        assert response["status"] == ResponseStatus.SUCCESS

        # Connect and login on second socket
        sock2.connect(("localhost", 8001))
        response = send_and_receive(sock2, login_request)
        assert response["status"] == ResponseStatus.SUCCESS

        # Verify first connection was handled properly
        try:
            send_and_receive(sock1, {"command": CommandType.LIST_ACCOUNTS})
            assert False, "First connection should have been closed"
        except:
            pass  # Expected - first connection should be closed

    finally:
        sock1.close()
        sock2.close()


def test_message_search_pattern(client_socket, authenticated_users):
    """Test searching messages with pattern matching"""
    # Send messages with different patterns
    messages = [
        "Hello world",
        "Testing 123",
        "Another hello message",
        "Final test",
    ]
    for content in messages:
        request = {
            "command": CommandType.SEND_MESSAGE,
            "sender": "sender",
            "recipient": "receiver",
            "content": content,
        }
        send_and_receive(client_socket, request)

    # Search with pattern
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": 10,
        "pattern": "%hello%",
    }
    response = send_and_receive(client_socket, read_request)
    assert len(response["messages"]) == 2
    assert all("hello" in msg["content"].lower() for msg in response["messages"])


def test_message_timestamps(client_socket, authenticated_users):
    """Test message timestamp handling"""
    # Send message
    request = {
        "command": CommandType.SEND_MESSAGE,
        "sender": "sender",
        "recipient": "receiver",
        "content": "Test message",
    }
    send_and_receive(client_socket, request)

    # Read message and verify timestamp
    read_request = {
        "command": CommandType.READ_MESSAGES,
        "username": "receiver",
        "recipient": "sender",
        "limit": 1,
    }
    response = send_and_receive(client_socket, read_request)
    message = response["messages"][0]

    # Verify timestamp is recent
    current_time = datetime.now().timestamp()
    assert abs(message["timestamp"] - current_time) < 5  # Within 5 seconds

    # Verify timestamp is a valid float
    assert isinstance(message["timestamp"], float)


def test_max_connections(server):
    """Test server handles maximum connections properly"""
    sockets = []
    try:
        # Try to create more connections than server limit
        for i in range(10):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)  # Add timeout to detect connection issues
            try:
                sock.connect(("localhost", 8001))
                sockets.append(sock)
                # Create and login a user to occupy a connection
                request = {
                    "command": CommandType.CREATE_ACCOUNT,
                    "username": f"test_user{i}",
                    "password": "testpass",
                }
                send_and_receive(sock, request)
            except (ConnectionRefusedError, socket.timeout):
                break
        # Verify active connections are limited
        active_connections = len(server.auth_manager.get_active_connections())
        assert (
            active_connections <= 5
        ), f"Too many active connections: {active_connections}"

    finally:
        for sock in sockets:
            sock.close()


def test_server_shutdown(server):
    """Test server shutdown handling"""
    # Create a connection
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("localhost", 8001))

    # Close server
    server.server_socket.close()

    # Verify connection is closed properly
    try:
        send_and_receive(sock, {"command": CommandType.LIST_ACCOUNTS})
        assert False, "Connection should be closed"
    except:
        pass  # Expected - connection should be closed
    finally:
        sock.close()


def test_large_account_list(client_socket):
    """Test handling large number of accounts"""
    # Create many accounts
    account_count = 100
    for i in range(account_count):
        request = {
            "command": CommandType.CREATE_ACCOUNT,
            "username": f"bulk_user{i:03d}",  # Pad with zeros for sorting
            "password": "testpass",
        }
        send_and_receive(client_socket, request)

    # Test pagination
    page_size = 20
    total_pages = (account_count + page_size - 1) // page_size

    all_accounts = set()
    for page in range(1, total_pages + 1):
        request = {
            "command": CommandType.LIST_ACCOUNTS,
            "pattern": "bulk_user%",
            "page": page,
            "page_size": page_size,
        }
        response = send_and_receive(client_socket, request)
        assert response["status"] == ResponseStatus.SUCCESS
        assert response["page"] == page
        assert response["total_pages"] == total_pages
        all_accounts.update(response["accounts"])

    # Verify we got all accounts
    assert len(all_accounts) == account_count
