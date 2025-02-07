import pytest
import socket
import threading
import time
from typing import Optional
from new_server import ChatServer
from new_models import *


@pytest.fixture
def server():
    """Fixture to create and manage server instance"""
    server = ChatServer(db_path=":memory:")

    # Bind and listen before starting thread
    server.server_socket.bind((server.host, server.port))
    server.server_socket.listen(5)

    # Create event to signal server shutdown
    stop_event = threading.Event()

    def run_server():
        while not stop_event.is_set():
            try:
                server.server_socket.settimeout(0.1)
                client_socket, address = server.server_socket.accept()
                client_thread = threading.Thread(
                    target=server.handle_client, args=(client_socket,), daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if not stop_event.is_set():
                    server.logger.error(f"Server error: {e}")

    # Start server thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(0.1)  # Give server time to start

    yield server

    # Cleanup
    stop_event.set()
    server.cleanup()
    server_thread.join(timeout=1)


@pytest.fixture
def client(server):
    """Fixture to create and manage client connection"""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("localhost", 8000))
    yield client
    client.close()


def send_receive(client: socket.socket, data: BaseModel) -> Dict:
    """Helper to send and receive data"""
    encoded = ProtocolHelper.encode(data, Protocol.JSON)
    client.sendall(encoded)
    response = client.recv(4096)
    return ProtocolHelper.decode(response, Protocol.JSON)


def test_create_account(client):
    """Test account creation"""
    request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.CREATE_ACCOUNT,
        username="testuser",
        password="testpass",
    )

    response = send_receive(client, request)
    assert response["status"] == ResponseStatus.SUCCESS


def test_login(client):
    """Test login functionality"""
    # Create account first
    create_request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.CREATE_ACCOUNT,
        username="testuser",
        password="testpass",
    )
    send_receive(client, create_request)

    # Try login
    login_request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.LOGIN,
        username="testuser",
        password="testpass",
    )
    response = send_receive(client, login_request)

    assert response["status"] == ResponseStatus.SUCCESS
    assert "unread_count" in response


def test_send_receive_message(server):
    """Test message sending and receiving"""
    # Create two clients
    sender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    recipient = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sender.connect(("localhost", 8000))
    recipient.connect(("localhost", 8000))

    try:
        # Create and login both users
        for client, username in [(sender, "sender"), (recipient, "recipient")]:
            create_request = AuthRequest(
                type=MessageType.AUTH,
                command=CommandType.CREATE_ACCOUNT,
                username=username,
                password="testpass",
            )
            send_receive(client, create_request)

            login_request = AuthRequest(
                type=MessageType.AUTH,
                command=CommandType.LOGIN,
                username=username,
                password="testpass",
            )
            send_receive(client, login_request)

        # Send message
        message_request = SendMessageRequest(
            type=MessageType.CHAT,
            command=CommandType.SEND_MESSAGE,
            sender="sender",
            recipient="recipient",
            content="Test message",
            timestamp=time.time(),
        )
        response = send_receive(sender, message_request)
        assert response["status"] == ResponseStatus.SUCCESS

        # Check if recipient received the message
        data = recipient.recv(4096)
        message = ProtocolHelper.decode(data, Protocol.JSON)
        assert message["content"] == "Test message"

    finally:
        sender.close()
        recipient.close()


def test_duplicate_account(client):
    """Test creating account with existing username"""
    # Create first account
    request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.CREATE_ACCOUNT,
        username="testuser",
        password="testpass",
    )
    send_receive(client, request)

    # Try creating duplicate account
    response = send_receive(client, request)
    assert response["status"] == ResponseStatus.ERROR
    assert "exists" in response["message"].lower()


def test_invalid_login(client):
    """Test login with invalid credentials"""
    # Create account
    create_request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.CREATE_ACCOUNT,
        username="testuser",
        password="testpass",
    )
    send_receive(client, create_request)

    # Try wrong password
    login_request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.LOGIN,
        username="testuser",
        password="wrongpass",
    )
    response = send_receive(client, login_request)
    assert response["status"] == ResponseStatus.ERROR


def test_list_users(client):
    """Test user listing functionality"""
    # Create some test users
    usernames = ["alice", "bob", "charlie"]
    for username in usernames:
        request = AuthRequest(
            type=MessageType.AUTH,
            command=CommandType.CREATE_ACCOUNT,
            username=username,
            password="testpass",
        )
        send_receive(client, request)

    # List all users
    list_request = ListUsersRequest(
        type=MessageType.SYSTEM,
        command=CommandType.LIST_USERS,
        pattern="%",
    )
    response = send_receive(client, list_request)
    assert response["status"] == ResponseStatus.SUCCESS
    assert "data" in response, "Response missing data field"
    assert "users" in response["data"], "Response data missing users field"
    assert all(user in response["data"]["users"] for user in usernames)


def test_delete_account(client):
    """Test account deletion"""
    # Create and login
    username = "deleteuser"
    create_request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.CREATE_ACCOUNT,
        username=username,
        password="testpass",
    )
    send_receive(client, create_request)

    # Login first
    login_request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.LOGIN,
        username=username,
        password="testpass",
    )
    send_receive(client, login_request)

    # Delete account
    delete_request = DeleteAccountRequest(
        type=MessageType.AUTH,
        command=CommandType.DELETE_ACCOUNT,
        username=username,
    )
    response = send_receive(client, delete_request)
    assert response["status"] == ResponseStatus.SUCCESS

    # Try logging in to deleted account
    login_request = AuthRequest(
        type=MessageType.AUTH,
        command=CommandType.LOGIN,
        username=username,
        password="testpass",
    )
    response = send_receive(client, login_request)
    assert response["status"] == ResponseStatus.ERROR


def test_message_persistence(server):
    """Test that messages persist for offline users"""
    sender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    recipient = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sender.connect(("localhost", 8000))
    recipient.connect(("localhost", 8000))

    try:
        # Create accounts
        for client, username in [(sender, "sender"), (recipient, "recipient")]:
            request = AuthRequest(
                type=MessageType.AUTH,
                command=CommandType.CREATE_ACCOUNT,
                username=username,
                password="testpass",
            )
            send_receive(client, request)

        # Login sender only
        login_request = AuthRequest(
            type=MessageType.AUTH,
            command=CommandType.LOGIN,
            username="sender",
            password="testpass",
        )
        send_receive(sender, login_request)

        # Send message while recipient is offline
        message_request = SendMessageRequest(
            type=MessageType.CHAT,
            command=CommandType.SEND_MESSAGE,
            sender="sender",
            recipient="recipient",
            content="Offline message",
        )
        response = send_receive(sender, message_request)
        assert response["status"] == ResponseStatus.SUCCESS

        # Login recipient and check unread count
        login_request = AuthRequest(
            type=MessageType.AUTH,
            command=CommandType.LOGIN,
            username="recipient",
            password="testpass",
        )
        response = send_receive(recipient, login_request)
        assert response["status"] == ResponseStatus.SUCCESS
        assert response["unread_count"] > 0

        # Read messages
        read_request = ReadMessagesRequest(
            type=MessageType.CHAT,
            command=CommandType.READ_MESSAGES,
            username="recipient",
            limit=50,
            offset=0,
        )
        response = send_receive(recipient, read_request)
        assert response["status"] == ResponseStatus.SUCCESS
        messages = response["data"]["messages"]
        assert len(messages) > 0
        assert any(msg["content"] == "Offline message" for msg in messages)

    finally:
        sender.close()
        recipient.close()
