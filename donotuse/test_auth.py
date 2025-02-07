import pytest
import sqlite3
import socket
from auth import AuthManager
from models import AuthRequest, CommandType, ResponseStatus


@pytest.fixture
def auth_manager():
    """Create AuthManager with in-memory database"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT
        )
    """
    )
    conn.execute(
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
    conn.commit()
    return AuthManager(conn)


def test_hash_password(auth_manager):
    """Test password hashing"""
    password = "testpass"
    hashed = auth_manager.hash_password(password)

    # Test hash is consistent
    assert auth_manager.hash_password(password) == hashed

    # Test different passwords have different hashes
    assert auth_manager.hash_password("different") != hashed

    # Test empty password
    assert auth_manager.hash_password("") != hashed


def test_create_account(auth_manager):
    """Test account creation"""
    request = AuthRequest(
        command=CommandType.CREATE_ACCOUNT,
        username="testuser",
        password="testpass",
    )

    # Test successful creation
    response = auth_manager.create_account(request)
    assert response.status == ResponseStatus.SUCCESS

    # Test duplicate username
    response = auth_manager.create_account(request)
    assert response.status == ResponseStatus.ERROR
    assert "exists" in response.message.lower()

    # Test empty username
    empty_request = AuthRequest(
        command=CommandType.CREATE_ACCOUNT,
        username="",
        password="testpass",
    )
    response = auth_manager.create_account(empty_request)
    assert response.status == ResponseStatus.ERROR


def test_verify_login(auth_manager):
    """Test login verification"""
    username = "verifytest"
    password = "testpass"

    # Create test account
    request = AuthRequest(
        command=CommandType.CREATE_ACCOUNT,
        username=username,
        password=password,
    )
    auth_manager.create_account(request)

    # Test successful verification
    success, _ = auth_manager.verify_login(username, password)
    assert success is True

    # Test wrong password
    success, _ = auth_manager.verify_login(username, "wrongpass")
    assert success is False

    # Test nonexistent user
    success, _ = auth_manager.verify_login("nonexistent", password)
    assert success is False


def test_login(auth_manager):
    """Test login functionality"""
    # Create test account
    create_request = AuthRequest(
        command=CommandType.CREATE_ACCOUNT,
        username="logintest",
        password="testpass",
    )
    response = auth_manager.create_account(create_request)
    print(f"Create account response: {response}")  # Debug print

    # Create mock socket for testing
    test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Test successful login
    login_request = AuthRequest(
        command=CommandType.LOGIN,
        username="logintest",
        password="testpass",
    )
    # Verify user exists
    cursor = auth_manager.conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (login_request.username,))
    user = cursor.fetchone()
    print(f"User in database: {user}")  # Debug print

    response = auth_manager.login(login_request, test_socket)
    print(f"Login response: {response}")  # Debug print
    assert response.status == ResponseStatus.SUCCESS
    assert response.unread_messages == 0

    # Verify connection was stored
    assert "logintest" in auth_manager.get_active_connections()

    # Test invalid password
    login_request.password = "wrongpass"
    response = auth_manager.login(login_request, test_socket)
    assert response.status == ResponseStatus.ERROR

    # Cleanup
    test_socket.close()


def test_delete_account(auth_manager):
    """Test account deletion"""
    # Create test account
    request = AuthRequest(
        command=CommandType.CREATE_ACCOUNT,
        username="deletetest",
        password="testpass",
    )
    auth_manager.create_account(request)

    # Create active connection
    test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    login_request = AuthRequest(
        command=CommandType.LOGIN,
        username="deletetest",
        password="testpass",
    )
    auth_manager.login(login_request, test_socket)

    # Test successful deletion
    response = auth_manager.delete_account("deletetest")
    assert response.status == ResponseStatus.SUCCESS
    assert "deletetest" not in auth_manager.get_active_connections()

    # Test deleting non-existent account
    response = auth_manager.delete_account("nonexistent")
    assert response.status == ResponseStatus.ERROR

    # Cleanup
    test_socket.close()


def test_connection_management(auth_manager):
    """Test active connection management"""
    # Setup test connections
    socket1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Create and login users
    users = [("user1", socket1), ("user2", socket2)]
    for username, sock in users:
        request = AuthRequest(
            command=CommandType.CREATE_ACCOUNT,
            username=username,
            password="testpass",
        )
        auth_manager.create_account(request)
        auth_manager.login(
            AuthRequest(
                command=CommandType.LOGIN,
                username=username,
                password="testpass",
            ),
            sock,
        )

    # Test get_active_connections
    connections = auth_manager.get_active_connections()
    assert len(connections) == 2
    assert "user1" in connections
    assert "user2" in connections

    # Test remove_connection
    auth_manager.remove_connection(socket1)
    connections = auth_manager.get_active_connections()
    assert len(connections) == 1
    assert "user1" not in connections
    assert "user2" in connections

    # Cleanup
    socket1.close()
    socket2.close()
