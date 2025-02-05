import pytest
import threading
import socket
from server import ChatServer, ResponseStatus
from client import ChatClient
import time
import os


@pytest.fixture(scope="session")
def server_port():
    return 8001


@pytest.fixture(scope="session")
def test_db():
    """Fixture to manage test database"""
    db_path = "test_chat.db"  # Use a different database for tests
    if os.path.exists(db_path):
        os.remove(db_path)
    return db_path


@pytest.fixture(scope="session")
def server(server_port, test_db):
    # Start server with test database
    server = ChatServer(port=server_port, db_path=test_db)
    server_thread = threading.Thread(target=server.start)
    server_thread.daemon = True
    server_thread.start()

    # Wait for server to start and be ready
    max_attempts = 5
    for _ in range(max_attempts):
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.connect(("localhost", server_port))
            test_socket.close()
            break
        except ConnectionRefusedError:
            time.sleep(0.5)
    else:
        pytest.fail("Server failed to start")

    yield server

    # Cleanup after all tests
    if os.path.exists(test_db):
        os.remove(test_db)


@pytest.fixture
def client(server, server_port):
    client = ChatClient(port=server_port)
    test_accounts = []  # Track accounts created during test

    # Monkey patch create_account to track test accounts
    original_create = client.create_account

    def create_account_wrapper(username, password):
        response = original_create(username, password)
        if response.status == ResponseStatus.SUCCESS:
            test_accounts.append(username)
        return response

    client.create_account = create_account_wrapper

    yield client

    # Cleanup: delete all accounts created during test
    for username in test_accounts:
        try:
            client.delete_account(username)
        except:
            pass
    client.disconnect()


# Add a fixture to clean database before each test
@pytest.fixture(autouse=True)
def clean_test_database(server):
    """Clean database before each test"""
    cursor = server.conn.cursor()
    cursor.execute("DELETE FROM messages")
    cursor.execute("DELETE FROM users")
    server.conn.commit()


# Connection Tests
def test_client_connect(server, server_port):
    """Test basic client connection"""
    client = ChatClient(port=server_port)
    client.connect()
    assert client.connected
    client.disconnect()
    assert not client.connected


def test_client_context_manager(server, server_port):
    """Test client context manager"""
    with ChatClient(port=server_port) as client:
        assert client.connected
    assert not client.connected


def test_client_connection_refused():
    """Test connection to non-existent server"""
    client = ChatClient(port=9999)  # Use unused port
    with pytest.raises(ConnectionError):
        client.connect()


def test_client_reconnect(server, server_port):
    """Test client reconnection after disconnect"""
    client = ChatClient(port=server_port)
    client.connect()
    assert client.connected
    client.disconnect()
    assert not client.connected
    client.connect()
    assert client.connected
    client.disconnect()


def test_multiple_clients(server, server_port):
    """Test multiple client connections"""
    clients = [ChatClient(port=server_port) for _ in range(3)]
    for client in clients:
        client.connect()
        assert client.connected

    for client in clients:
        client.disconnect()
        assert not client.connected


def test_server_disconnect_detection(server, server_port):
    """Test if client detects server disconnection"""
    with ChatClient(port=server_port) as client:
        # First create an account and log in
        client.create_account("disconnect_test", "password123")
        client.login("disconnect_test", "password123")

        # Verify we're connected and logged in
        client.list_accounts()

        # Find and close the client's socket in server's active connections
        found = False
        for sock in list(server.active_connections.values()):
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
                found = True
                break
            except:
                continue

        assert found, "Could not find client connection to close"

        # Try to send a request, should raise ConnectionError
        with pytest.raises(ConnectionError):
            client.list_accounts()


# Existing Functional Tests
@pytest.fixture
def test_user(client):
    """Create a test user for tests that need one"""
    client.create_account("testuser", "password123")
    return "testuser"


@pytest.fixture
def two_users(client):
    """Create two test users for messaging tests"""
    client.create_account("user1", "password123")
    client.create_account("user2", "password123")
    return "user1", "user2"


def test_create_duplicate_account(client, test_user):
    # testuser already created by fixture
    response = client.create_account("testuser", "password123")
    assert response.status == ResponseStatus.ERROR
    assert "already exists" in response.message


def test_login_success(client, test_user):
    response = client.login("testuser", "password123")
    assert response.status == ResponseStatus.SUCCESS
    assert response.unread_messages == 0


def test_list_accounts(client, test_user):
    response = client.list_accounts()
    assert response.status == ResponseStatus.SUCCESS
    assert "testuser" in response.accounts
    assert response.total_count >= 1


def test_send_and_read_message(client, two_users):
    user1, user2 = two_users
    client.login(user1, "password123")

    # Test sending multiple messages
    messages = ["Hello!", "How are you?", "Testing..."]
    for msg in messages:
        send_response = client.send_message(user1, user2, msg)
        assert send_response.status == ResponseStatus.SUCCESS

    # Read messages and verify
    read_response = client.read_messages(user2)
    assert read_response.status == ResponseStatus.SUCCESS
    assert len(read_response.messages) == len(messages)


def test_delete_messages(client, two_users):
    user1, user2 = two_users
    # Send a test message first
    client.login(user1, "password123")
    client.send_message(user1, user2, "Test message")

    # Read and delete message
    read_response = client.read_messages(user2)
    assert len(read_response.messages) > 0

    message_ids = [msg.id for msg in read_response.messages]
    delete_response = client.delete_messages(user2, message_ids)
    assert delete_response.status == ResponseStatus.SUCCESS


def test_message_read_status(client, two_users):
    user1, user2 = two_users
    # Send test message
    client.login(user1, "password123")
    client.send_message(user1, user2, "Test message")

    # Check unread count
    response = client.login(user2, "password123")
    initial_unread = response.unread_messages
    assert initial_unread > 0


def test_delete_account(client, two_users):
    """Test account deletion"""
    user1, user2 = two_users
    response = client.delete_account(user2)
    assert response.status == ResponseStatus.SUCCESS

    # Verify account is deleted
    list_response = client.list_accounts()
    assert user2 not in list_response.accounts
    assert user1 in list_response.accounts


# Database Tests
def test_database_persistence(server, server_port):
    """Test that database changes persist between client connections"""
    # Create first client and account
    with ChatClient(port=server_port) as client1:
        response = client1.create_account("persist_test", "password123")
        assert response.status == ResponseStatus.SUCCESS

    # Connect with new client and verify account exists
    with ChatClient(port=server_port) as client2:
        response = client2.login("persist_test", "password123")
        assert response.status == ResponseStatus.SUCCESS


def test_message_persistence(server, server_port, test_user):
    """Test that messages persist between sessions"""
    # First create persist_test user
    with ChatClient(port=server_port) as client1:
        client1.create_account("persist_test", "password123")
        client1.login("persist_test", "password123")
        response = client1.send_message("persist_test", "testuser", "Test message")
        assert response.status == ResponseStatus.SUCCESS

    # Check message with second client
    with ChatClient(port=server_port) as client2:
        client2.login("testuser", "password123")
        response = client2.read_messages("testuser")
        assert response.status == ResponseStatus.SUCCESS
        assert len(response.messages) > 0
        assert "Test message" in [msg.content for msg in response.messages]


def test_account_deletion_cascade(server, server_port):
    """Test that deleting an account removes associated messages"""
    # First client for creating account and sending messages
    with ChatClient(port=server_port) as client1:
        client1.create_account("delete_test", "password123")
        client1.login("delete_test", "password123")

        # Send messages both ways
        client1.send_message("delete_test", "testuser", "Message 1")
        client1.send_message("testuser", "delete_test", "Message 2")

        # Delete account
        response = client1.delete_account("delete_test")
        assert response.status == ResponseStatus.SUCCESS

    # Create new client connection for reading messages
    with ChatClient(port=server_port) as client2:
        client2.login("testuser", "password123")
        response = client2.read_messages("testuser")
        # Messages from deleted user should be gone
        assert not any(msg.sender == "delete_test" for msg in response.messages)


def test_list_accounts_pagination(client):
    """Test account listing with pagination and patterns"""
    # Create several test accounts
    test_users = ["test_a", "test_b", "test_c", "other_1", "other_2"]
    for user in test_users:
        client.create_account(user, "password123")

    # Test pattern matching
    response = client.list_accounts(pattern="test_%")
    assert response.status == ResponseStatus.SUCCESS
    assert all(user in response.accounts for user in ["test_a", "test_b", "test_c"])
    assert not any(user in response.accounts for user in ["other_1", "other_2"])

    # Test pagination
    response = client.list_accounts(page_size=2)
    assert len(response.accounts) == 2
    assert response.total_pages > 1


def test_database_separation(test_db):
    """Verify test database is separate from production database"""
    assert test_db != "chat.db"
    assert os.path.exists(test_db)
    assert not os.path.exists("chat.db")  # Production DB shouldn't exist during tests


@pytest.fixture(scope="session", autouse=True)
def clean_databases():
    """Remove test database before and after tests"""
    # Remove only test database before tests
    if os.path.exists("test_chat.db"):
        os.remove("test_chat.db")
    yield
    # Clean up test database after tests
    if os.path.exists("test_chat.db"):
        os.remove("test_chat.db")


def test_connection_after_account_deletion(server, server_port):
    """Test that connection remains usable after account deletion"""
    with ChatClient(port=server_port) as client:
        # Create and login with test account
        client.create_account("temp_user", "password123")
        login_response = client.login("temp_user", "password123")
        assert login_response.status == ResponseStatus.SUCCESS

        # Delete the account
        delete_response = client.delete_account("temp_user")
        assert delete_response.status == ResponseStatus.SUCCESS

        # Connection should still be usable
        # Try listing accounts (doesn't require login)
        list_response = client.list_accounts()
        assert list_response.status == ResponseStatus.SUCCESS
        assert "temp_user" not in list_response.accounts

        # Try creating another account
        create_response = client.create_account("another_user", "password123")
        assert create_response.status == ResponseStatus.SUCCESS

        # Should be able to login with new account
        login_response = client.login("another_user", "password123")
        assert login_response.status == ResponseStatus.SUCCESS


def test_account_switching_and_deletion(server, server_port):
    """Test switching between accounts and maintaining connection after deletion"""
    with ChatClient(port=server_port) as client:
        # Create first account
        client.create_account("user1", "password123")

        # Create second account
        client.create_account("user2", "password123")

        # Login to second account
        login_response = client.login("user2", "password123")
        assert login_response.status == ResponseStatus.SUCCESS

        # Delete second account while logged in
        delete_response = client.delete_account("user2")
        assert delete_response.status == ResponseStatus.SUCCESS

        # Should be able to login to first account
        login_response = client.login("user1", "password123")
        assert login_response.status == ResponseStatus.SUCCESS

        # Verify second account is gone
        list_response = client.list_accounts()
        assert "user2" not in list_response.accounts
        assert "user1" in list_response.accounts
