import pytest
import socket
import threading
import time
from datetime import datetime, timedelta
from server import ChatServer
from database import Database
from schemas import ChatMessage, MessageType, SystemMessage, Status, ServerResponse
from protocol import ProtocolFactory
import os
import random
import string


@pytest.fixture(autouse=True)
def clean_database():
    """Clean up the database before each test"""
    db = Database("file::memory:?cache=shared")
    db.conn.execute("DELETE FROM users")
    db.conn.execute("DELETE FROM messages")
    db.conn.commit()
    yield
    db.conn.execute("DELETE FROM users")
    db.conn.execute("DELETE FROM messages")
    db.conn.commit()
    try:
        os.remove("file::memory:?cache=shared")
    except OSError:
        pass


@pytest.fixture
def test_server(clean_database):
    """Create a test server instance"""
    # Use a shared in-memory database for all connections
    server = ChatServer(db_path="file::memory:?cache=shared")

    # Start server in a separate thread
    server_thread = threading.Thread(target=server.start)
    server_thread.daemon = True
    server_thread.start()
    # Give the server time to start
    time.sleep(0.1)
    yield server
    server.shutdown()

    # Clean up the test database file
    try:
        os.remove("test.db")
    except OSError:
        pass


@pytest.fixture
def test_client():
    """Create a test client socket"""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    yield client
    try:
        client.shutdown(socket.SHUT_RDWR)
    except:
        pass
    try:
        client.close()
    except:
        pass


@pytest.fixture
def protocol():
    """Create a protocol instance for message handling"""
    return ProtocolFactory.create("json")


def register_and_login_user(client, protocol, username, password):
    """Helper function to register and login a user"""
    # Register
    register_msg = ChatMessage(
        username=username,
        password=password,
        content="",
        message_type=MessageType.REGISTER,
        timestamp=datetime.now(),
    )
    data = protocol.serialize_message(register_msg)
    framed_data = protocol.frame_message(data)
    client.send(framed_data)

    # Wait for registration response
    response_data = client.recv(1024)
    message_data, _ = protocol.extract_message(response_data)
    response = protocol.deserialize_response(message_data)
    if response.status != Status.SUCCESS:
        print(f"Registration failed: {response.message}")
        return False

    # Login
    login_msg = ChatMessage(
        username=username,
        password=password,
        content="",
        message_type=MessageType.LOGIN,
        timestamp=datetime.now(),
    )
    data = protocol.serialize_message(login_msg)
    framed_data = protocol.frame_message(data)
    client.send(framed_data)

    # Process login responses with timeout
    buffer = b""
    login_success = False
    start_time = time.time()
    while not login_success and time.time() - start_time < 5:  # 5 second timeout
        try:
            response_data = client.recv(1024)
            if not response_data:
                print("Connection closed by server")
                break
            buffer += response_data
            while True:
                message_data, buffer = protocol.extract_message(buffer)
                if message_data is None:
                    break
                response = protocol.deserialize_response(message_data)
                if response.status == Status.ERROR:
                    print(f"Login failed: {response.message}")
                    return False
                if response.message == SystemMessage.LOGIN_SUCCESS:
                    login_success = True
                    break
        except socket.timeout:
            print("Socket timeout waiting for login response")
            break
        except Exception as e:
            print(f"Error during login: {str(e)}")
            break

    if not login_success:
        print("Login timed out or failed")
    return login_success


def test_server_initialization():
    """Test server initialization with default parameters"""
    server = ChatServer(db_path=":memory:")
    assert server.host == "localhost"
    assert server.port == 8000
    assert server.running == True
    assert isinstance(server.protocol, ProtocolFactory.create("json").__class__)


def test_server_custom_initialization():
    """Test server initialization with custom parameters"""
    server = ChatServer(
        db_path="test.db",
        host="127.0.0.1",
        port=8001,
        protocol=ProtocolFactory.create("json"),
    )
    assert server.host == "127.0.0.1"
    assert server.port == 8001
    assert server.running == True


def test_client_connection(test_server, test_client):
    """Test client connection to server"""
    test_client.connect(("localhost", 8000))
    assert test_client.getpeername() is not None


def test_client_connection_timeout():
    """Test client connection timeout"""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(1)
    with pytest.raises(socket.error):
        client.connect(("localhost", 9999))
    client.close()


def test_user_registration(test_server, test_client, protocol):
    """Test user registration process"""
    test_client.connect(("localhost", 8000))

    # Test registration with valid data
    register_msg = ChatMessage(
        username="testuser",
        password="testpass",
        content="",
        message_type=MessageType.REGISTER,
        timestamp=datetime.now(),
    )
    data = protocol.serialize_message(register_msg)
    framed_data = protocol.frame_message(data)
    test_client.send(framed_data)

    response_data = test_client.recv(1024)
    message_data, _ = protocol.extract_message(response_data)
    response = protocol.deserialize_response(message_data)

    assert response.status == Status.SUCCESS
    assert response.message == SystemMessage.REGISTRATION_SUCCESS


def test_registration_validation(test_server, test_client, protocol):
    """Test registration input validation"""
    test_client.connect(("localhost", 8000))

    # Test cases for invalid registration
    test_cases = [
        ("", "testpass", SystemMessage.USERNAME_REQUIRED),  # Empty username
        ("testuser", "", SystemMessage.PASSWORD_REQUIRED),  # Empty password
        ("a", "testpass", SystemMessage.USERNAME_TOO_SHORT),  # Username too short
        (
            "test user",
            "testpass",
            SystemMessage.INVALID_USERNAME,
        ),  # Username with space
        (
            "test@user",
            "testpass",
            SystemMessage.INVALID_USERNAME,
        ),  # Username with special chars
    ]

    for username, password, expected_message in test_cases:
        # Close and reconnect for each test case
        test_client.close()
        test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_client.connect(("localhost", 8000))

        register_msg = ChatMessage(
            username=username,
            password=password,
            content="",
            message_type=MessageType.REGISTER,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(register_msg)
        framed_data = protocol.frame_message(data)
        test_client.send(framed_data)

        response_data = test_client.recv(1024)
        message_data, _ = protocol.extract_message(response_data)
        response = protocol.deserialize_response(message_data)

        assert (
            response.status == Status.ERROR
        ), f"Expected error for {username=}, {password=}"
        assert (
            response.message == expected_message
        ), f"Wrong error message for {username=}, {password=}"

    # Test successful registration
    test_client.close()
    test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_client.connect(("localhost", 8000))

    register_msg = ChatMessage(
        username="validuser",
        password="validpass",
        content="",
        message_type=MessageType.REGISTER,
        timestamp=datetime.now(),
    )
    data = protocol.serialize_message(register_msg)
    framed_data = protocol.frame_message(data)
    test_client.send(framed_data)

    response_data = test_client.recv(1024)
    message_data, _ = protocol.extract_message(response_data)
    response = protocol.deserialize_response(message_data)
    assert response.status == Status.SUCCESS
    assert response.message == SystemMessage.REGISTRATION_SUCCESS


def test_user_login(test_server, test_client, protocol):
    """Test user login process"""
    test_client.connect(("localhost", 8000))

    # First register a user
    username = "testuser"
    password = "testpass"
    register_msg = ChatMessage(
        username=username,
        password=password,
        content="",
        message_type=MessageType.REGISTER,
        timestamp=datetime.now(),
    )
    data = protocol.serialize_message(register_msg)
    framed_data = protocol.frame_message(data)
    test_client.send(framed_data)

    # Verify registration success
    response_data = test_client.recv(1024)
    message_data, _ = protocol.extract_message(response_data)
    response = protocol.deserialize_response(message_data)
    assert response.status == Status.SUCCESS, "Registration failed"
    assert response.message == SystemMessage.REGISTRATION_SUCCESS

    # Close and reconnect for login
    test_client.close()
    test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_client.connect(("localhost", 8000))

    # Attempt login
    login_msg = ChatMessage(
        username=username,
        password=password,
        content="",
        message_type=MessageType.LOGIN,
        timestamp=datetime.now(),
    )
    data = protocol.serialize_message(login_msg)
    framed_data = protocol.frame_message(data)
    test_client.send(framed_data)

    # Process login responses
    buffer = b""
    login_success = False
    active_users_received = False
    start_time = time.time()

    while (
        not login_success or not active_users_received
    ) and time.time() - start_time < 5:
        try:
            response_data = test_client.recv(1024)
            if not response_data:
                break
            buffer += response_data
            while True:
                message_data, buffer = protocol.extract_message(buffer)
                if message_data is None:
                    break
                response = protocol.deserialize_response(message_data)

                if response.status == Status.ERROR:
                    pytest.fail(f"Login failed with error: {response.message}")

                if response.message == SystemMessage.LOGIN_SUCCESS:
                    login_success = True
                    assert (
                        response.data is not None
                    ), "Login success response missing data"
                    assert hasattr(
                        response.data, "active_users"
                    ), "Active users list missing"
                    active_users_received = True
                    break

        except socket.timeout:
            pytest.fail("Socket timeout waiting for login response")
        except Exception as e:
            pytest.fail(f"Error during login: {str(e)}")

    assert login_success, "Did not receive login success message"
    assert active_users_received, "Did not receive active users list"


def test_concurrent_logins(test_server, protocol):
    """Test multiple users logging in concurrently"""
    num_clients = 5
    clients = []
    try:
        # Create and connect multiple clients
        for i in range(num_clients):
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(("localhost", 8000))
            clients.append(client)
            username = f"user{i}"
            password = f"pass{i}"
            assert register_and_login_user(client, protocol, username, password)

        # Verify all clients are connected
        for client in clients:
            assert client.getpeername() is not None

    finally:
        # Clean up
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass


def test_invalid_login(test_server, test_client, protocol):
    """Test login with invalid credentials"""
    test_client.connect(("localhost", 8000))

    # First register the user
    register_msg = ChatMessage(
        username="testuser",
        password="testpass",
        content="",
        message_type=MessageType.REGISTER,
        timestamp=datetime.now(),
    )
    data = protocol.serialize_message(register_msg)
    framed_data = protocol.frame_message(data)
    test_client.send(framed_data)

    # Wait for registration response
    response_data = test_client.recv(1024)
    message_data, _ = protocol.extract_message(response_data)
    protocol.deserialize_response(message_data)

    # Test various invalid login scenarios
    test_cases = [
        ("testuser", "wrongpass", SystemMessage.INVALID_CREDENTIALS),
        ("nonexistent", "testpass", SystemMessage.INVALID_CREDENTIALS),
        ("testuser", "", SystemMessage.PASSWORD_REQUIRED),
    ]

    for username, password, expected_message in test_cases:
        # Close and reconnect for each test case
        test_client.close()
        test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_client.connect(("localhost", 8000))

        login_msg = ChatMessage(
            username=username,
            password=password,
            content="",
            message_type=MessageType.LOGIN,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(login_msg)
        framed_data = protocol.frame_message(data)
        test_client.send(framed_data)

        response_data = test_client.recv(1024)
        message_data, _ = protocol.extract_message(response_data)
        response = protocol.deserialize_response(message_data)

        assert response.status == Status.ERROR
        assert response.message == expected_message


def test_duplicate_registration(test_server, test_client, protocol):
    """Test registration with existing username"""
    test_client.connect(("localhost", 8000))

    # First registration
    register_msg = ChatMessage(
        username="testuser",
        password="testpass",
        content="",
        message_type=MessageType.REGISTER,
        timestamp=datetime.now(),
    )

    data = protocol.serialize_message(register_msg)
    framed_data = protocol.frame_message(data)
    test_client.send(framed_data)

    # Receive first response
    response_data = test_client.recv(1024)
    message_data, _ = protocol.extract_message(response_data)
    first_response = protocol.deserialize_response(message_data)
    assert first_response.status == Status.SUCCESS

    # Close and reconnect before second registration attempt
    test_client.close()
    test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_client.connect(("localhost", 8000))

    # Try registering again with same username
    test_client.send(framed_data)

    # Receive second response
    response_data = test_client.recv(1024)
    message_data, _ = protocol.extract_message(response_data)
    response = protocol.deserialize_response(message_data)

    assert response.status == Status.ERROR
    assert response.message == SystemMessage.USER_EXISTS


def test_message_sending(test_server, protocol):
    """Test sending messages between users"""
    # Create and connect two clients
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client1.connect(("localhost", 8000))
        client2.connect(("localhost", 8000))

        # Register and login both users
        assert register_and_login_user(client1, protocol, "user1", "pass1")
        assert register_and_login_user(client2, protocol, "user2", "pass2")

        # Send message from user1 to user2
        message = ChatMessage(
            username="user1",
            content="Hello user2!",
            message_type=MessageType.DM,
            recipients=["user2"],
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(message)
        framed_data = protocol.frame_message(data)
        client1.send(framed_data)

        # Verify user2 receives the message
        buffer = b""
        message_received = False
        while not message_received:
            response_data = client2.recv(1024)
            if not response_data:
                break
            buffer += response_data
            while True:
                message_data, buffer = protocol.extract_message(buffer)
                if message_data is None:
                    break
                response = protocol.deserialize_response(message_data)
                if response.data and response.data.content == "Hello user2!":
                    message_received = True
                    break

        assert message_received

    finally:
        for client in [client1, client2]:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass


def test_message_delivery_order(test_server, protocol):
    """Test message delivery order is preserved"""
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client1.connect(("localhost", 8000))
        client2.connect(("localhost", 8000))

        # Register and login both users
        assert register_and_login_user(client1, protocol, "user1", "pass1")
        assert register_and_login_user(client2, protocol, "user2", "pass2")

        # Send multiple messages
        messages = ["Message 1", "Message 2", "Message 3"]
        for content in messages:
            message = ChatMessage(
                username="user1",
                content=content,
                message_type=MessageType.DM,
                recipients=["user2"],
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(message)
            framed_data = protocol.frame_message(data)
            client1.send(framed_data)
            time.sleep(0.1)  # Small delay to ensure order

        # Verify messages are received in order
        received_messages = []
        buffer = b""
        start_time = time.time()
        while len(received_messages) < len(messages) and time.time() - start_time < 5:
            response_data = client2.recv(1024)
            if not response_data:
                break
            buffer += response_data
            while True:
                message_data, buffer = protocol.extract_message(buffer)
                if message_data is None:
                    break
                response = protocol.deserialize_response(message_data)
                if response.data and response.data.content.startswith("Message "):
                    received_messages.append(response.data.content)

        assert received_messages == messages

    finally:
        for client in [client1, client2]:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass


def test_large_message_handling(test_server, protocol):
    """Test handling of large messages"""
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client1.connect(("localhost", 8000))
        client2.connect(("localhost", 8000))

        # Register and login both users
        assert register_and_login_user(client1, protocol, "user1", "pass1")
        assert register_and_login_user(client2, protocol, "user2", "pass2")

        # Generate a large message
        large_content = "".join(
            random.choices(string.ascii_letters + string.digits, k=50000)
        )
        message = ChatMessage(
            username="user1",
            content=large_content,
            message_type=MessageType.DM,
            recipients=["user2"],
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(message)
        framed_data = protocol.frame_message(data)
        client1.send(framed_data)

        # Verify large message is received correctly
        buffer = b""
        message_received = False
        while not message_received:
            response_data = client2.recv(1024)
            if not response_data:
                break
            buffer += response_data
            while True:
                message_data, buffer = protocol.extract_message(buffer)
                if message_data is None:
                    break
                response = protocol.deserialize_response(message_data)
                if response.data and response.data.content == large_content:
                    message_received = True
                    break

        assert message_received

    finally:
        for client in [client1, client2]:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass


def test_server_shutdown_handling(test_server, test_client, protocol):
    """Test client handling of server shutdown"""
    test_client.connect(("localhost", 8000))
    assert register_and_login_user(test_client, protocol, "testuser", "testpass")

    # Shutdown server
    test_server.shutdown()

    # Give time for shutdown to complete
    max_attempts = 5
    for _ in range(max_attempts):
        time.sleep(0.2)  # Total up to 1 second wait
        if test_client._closed:  # Check internal closed flag
            break
        try:
            # Try to send data - this should fail if socket is closed
            test_client.send(b"test")
        except (OSError, socket.error):
            # This is expected - socket is closed
            break
    else:
        pytest.fail("Socket was not closed after server shutdown")


def test_connection_limit(test_server, protocol):
    """Test server behavior when connection limit is reached"""
    max_connections = 50  # Reduced from 100 to stay within system limits
    clients = []

    def cleanup_socket(sock):
        """Helper to clean up a socket"""
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                sock.close()
            except:
                pass

    def cleanup_all_clients():
        """Helper to clean up all client sockets"""
        for client in clients[
            :
        ]:  # Create a copy to avoid modification during iteration
            cleanup_socket(client)
            if client in clients:
                clients.remove(client)

    try:
        # Try to create more connections than the server can handle
        connection_limit_reached = False
        for i in range(max_connections):
            try:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(0.5)  # Short timeout to fail fast
                client.connect(("127.0.0.1", 8000))
                clients.append(client)
            except OSError as e:
                if e.errno == 24:  # Too many open files
                    print(
                        f"System file descriptor limit reached after {len(clients)} connections"
                    )
                    connection_limit_reached = True
                    cleanup_socket(client)
                    break
                elif isinstance(e, (socket.timeout, ConnectionRefusedError)):
                    print(
                        f"Connection limit reached after {len(clients)} connections: {str(e)}"
                    )
                    cleanup_socket(client)
                    connection_limit_reached = True
                    break
                else:
                    print(f"Unexpected error creating connection: {str(e)}")
                    cleanup_socket(client)
                    break
            except Exception as e:
                print(f"Unexpected error creating connection: {str(e)}")
                cleanup_socket(client)
                break

        # Verify we got a reasonable number of connections
        assert len(clients) > 0, "Failed to create any connections"
        print(f"Successfully created {len(clients)} connections")

        # If we hit a limit (either system or server), test cleanup and reconnection
        if connection_limit_reached:
            # Close half of the connections
            clients_to_close = len(clients) // 2
            for client in clients[:clients_to_close]:
                cleanup_socket(client)
                clients.remove(client)

            # Give server time to clean up
            time.sleep(0.5)

            # Try to connect again
            try:
                new_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                new_client.settimeout(1)
                new_client.connect(("127.0.0.1", 8000))
                clients.append(new_client)

                # Verify the new connection works
                assert (
                    new_client.getpeername() is not None
                ), "Failed to establish new connection after cleanup"
            except Exception as e:
                pytest.fail(f"Failed to create new connection after cleanup: {str(e)}")

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")
    finally:
        cleanup_all_clients()


def test_malformed_messages(test_server, test_client, protocol):
    """Test server handling of malformed messages"""
    start_time = time.time()
    max_test_duration = 10  # Maximum 10 seconds for the entire test

    def cleanup_socket(sock):
        """Helper to clean up a socket"""
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                sock.close()
            except:
                pass

    try:
        test_client.connect(("127.0.0.1", 8000))
        test_client.settimeout(1.0)

        # Test cases for malformed messages
        test_cases = [
            b"invalid json{",  # Invalid JSON
            b"",  # Empty message
            b"0" * 1024,  # Smaller large message
            b"\x00\x01\x02\x03",  # Binary data
        ]

        for malformed_msg in test_cases:
            if time.time() - start_time > max_test_duration:
                pytest.fail("Test exceeded maximum duration")

            try:
                cleanup_socket(test_client)
                test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_client.settimeout(1.0)
                test_client.connect(("127.0.0.1", 8000))

                test_client.send(malformed_msg)
                time.sleep(0.1)  # Brief pause between messages

                try:
                    test_client.recv(1024)
                except socket.timeout:
                    pass  # Expected for malformed messages
                except socket.error:
                    pass  # Expected if server closes connection

            except Exception as e:
                print(f"Expected error during malformed message test: {e}")

        # Final verification with longer timeout
        cleanup_socket(test_client)
        test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_client.settimeout(5.0)
        test_client.connect(("127.0.0.1", 8000))

        # Try registration multiple times if needed
        max_retries = 3
        success = False
        last_error = None

        for _ in range(max_retries):
            try:
                success = register_and_login_user(
                    test_client, protocol, "testuser", "testpass"
                )
                if success:
                    break
            except Exception as e:
                last_error = e
                cleanup_socket(test_client)
                test_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_client.settimeout(5.0)
                test_client.connect(("127.0.0.1", 8000))
                time.sleep(0.5)  # Wait before retry

        if not success:
            pytest.fail(
                f"Final verification failed after {max_retries} attempts: {last_error}"
            )

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")
    finally:
        cleanup_socket(test_client)


def test_network_interruption(test_server, protocol):
    """Test server handling of network interruptions during operations"""
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client1.settimeout(5.0)  # Longer timeout for operations
    client2.settimeout(5.0)

    try:
        # Connect and register both clients
        client1.connect(("127.0.0.1", 8000))
        client2.connect(("127.0.0.1", 8000))

        # Register and login both users
        assert register_and_login_user(
            client1, protocol, "user1", "pass1"
        ), "Failed to register/login user1"
        assert register_and_login_user(
            client2, protocol, "user2", "pass2"
        ), "Failed to register/login user2"

        # Simulate network interruption by closing socket during message send
        message = ChatMessage(
            username="user1",
            content="This message will be interrupted",
            message_type=MessageType.DM,
            recipients=["user2"],
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(message)
        framed_data = protocol.frame_message(data)

        # Send only part of the message and close connection
        try:
            client1.send(framed_data[: len(framed_data) // 2])
        except socket.error:
            pass  # Expected if server closes connection first

        try:
            client1.shutdown(socket.SHUT_RDWR)
            client1.close()
        except:
            pass

        time.sleep(0.1)  # Give server time to process disconnection

        # Reconnect client1 and login
        client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client1.settimeout(5.0)
        client1.connect(("127.0.0.1", 8000))

        # Login with existing credentials
        login_msg = ChatMessage(
            username="user1",
            password="pass1",
            content="",
            message_type=MessageType.LOGIN,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(login_msg)
        framed_data = protocol.frame_message(data)
        client1.send(framed_data)

        # Wait for login success with timeout
        buffer = b""
        login_success = False
        start_time = time.time()

        while not login_success and time.time() - start_time < 5:
            try:
                response_data = client1.recv(1024)
                if not response_data:
                    break
                buffer += response_data
                while True:
                    message_data, buffer = protocol.extract_message(buffer)
                    if message_data is None:
                        break
                    response = protocol.deserialize_response(message_data)
                    if response.message == SystemMessage.LOGIN_SUCCESS:
                        login_success = True
                        break
            except socket.timeout:
                break

        assert login_success, "Failed to login after reconnection"

        # Send a new message after reconnection
        new_message = ChatMessage(
            username="user1",
            content="New message after interruption",
            message_type=MessageType.DM,
            recipients=["user2"],
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(new_message)
        framed_data = protocol.frame_message(data)
        client1.send(framed_data)

        # Verify message is received with timeout
        buffer = b""
        message_received = False
        start_time = time.time()

        while not message_received and time.time() - start_time < 5:
            try:
                response_data = client2.recv(1024)
                if not response_data:
                    break
                buffer += response_data
                while True:
                    message_data, buffer = protocol.extract_message(buffer)
                    if message_data is None:
                        break
                    response = protocol.deserialize_response(message_data)
                    if (
                        response.data
                        and response.data.content == "New message after interruption"
                    ):
                        message_received = True
                        break
            except socket.timeout:
                continue

        assert message_received, "Failed to receive message after reconnection"

    finally:
        # Clean up all sockets
        for client in [client1, client2]:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                client.close()
            except:
                pass


def test_resource_cleanup(test_server, protocol):
    """Test server resource cleanup after client disconnections"""
    num_clients = 10
    clients = []
    registered_users = []

    def cleanup_socket(sock):
        """Helper to clean up a socket"""
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                sock.close()
            except:
                pass

    try:
        # Create and connect multiple clients
        for i in range(num_clients):
            try:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(5.0)  # Longer timeout for operations
                client.connect(("127.0.0.1", 8000))
                username = f"user{i}"
                password = f"pass{i}"

                # Try registration with retries
                max_retries = 3
                success = False
                for _ in range(max_retries):
                    try:
                        if register_and_login_user(
                            client, protocol, username, password
                        ):
                            success = True
                            clients.append(client)
                            registered_users.append(username)
                            break
                    except Exception as e:
                        print(f"Retry registration for {username}: {e}")
                        time.sleep(0.5)

                if not success:
                    print(
                        f"Failed to register/login {username} after {max_retries} attempts"
                    )
                    cleanup_socket(client)

            except Exception as e:
                print(f"Error setting up client {i}: {e}")
                cleanup_socket(client)
                continue

        # Verify initial server state
        assert len(clients) > 0, "Failed to create any clients"

        # Give server time to clean up any disconnected clients
        time.sleep(0.5)

        # Verify server state matches our tracked state
        with test_server.lock:  # Use server's lock to ensure consistent state
            assert len(test_server.clients) == len(
                clients
            ), f"Mismatch in connected clients: server={len(test_server.clients)}, local={len(clients)}"
            assert len(test_server.usernames) == len(
                registered_users
            ), f"Mismatch in registered users: server={len(test_server.usernames)}, local={len(registered_users)}"
            assert len(test_server.client_buffers) == len(
                clients
            ), f"Mismatch in client buffers: server={len(test_server.client_buffers)}, local={len(clients)}"

        # Store initial counts
        initial_client_count = len(test_server.clients)
        initial_username_count = len(test_server.usernames)
        initial_buffer_count = len(test_server.client_buffers)

        # Abruptly close half the clients
        clients_to_close = clients[: len(clients) // 2]
        for client in clients_to_close:
            cleanup_socket(client)
            if client in clients:
                clients.remove(client)

        # Give server time to clean up
        time.sleep(1.0)  # Increased cleanup time

        # Verify server cleaned up resources
        with test_server.lock:  # Use server's lock to ensure consistent state
            current_clients = len(test_server.clients)
            current_usernames = len(test_server.usernames)
            current_buffers = len(test_server.client_buffers)

            assert current_clients == len(
                clients
            ), f"Server has {current_clients} clients, expected {len(clients)}"
            assert current_usernames == len(
                clients
            ), f"Server has {current_usernames} usernames, expected {len(clients)}"
            assert current_buffers == len(
                clients
            ), f"Server has {current_buffers} buffers, expected {len(clients)}"

        # Verify remaining clients can still communicate
        if clients:
            test_client = clients[0]
            test_username = registered_users[
                len(clients_to_close)
            ]  # First remaining user
            message = ChatMessage(
                username=test_username,
                content="Test message after cleanup",
                message_type=MessageType.CHAT,
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(message)
            framed_data = protocol.frame_message(data)
            try:
                test_client.send(framed_data)
                # Wait and verify no errors
                time.sleep(0.5)
                # Try to receive any response
                test_client.settimeout(1.0)
                try:
                    test_client.recv(1024)
                except socket.timeout:
                    pass  # Timeout is okay here
            except Exception as e:
                pytest.fail(f"Failed to send message after cleanup: {e}")

    finally:
        # Clean up remaining clients
        for client in clients[
            :
        ]:  # Create a copy of the list to avoid modification during iteration
            cleanup_socket(client)
            if client in clients:
                clients.remove(client)


def test_race_conditions(test_server, protocol):
    """Test concurrent operations for race conditions"""
    num_threads = 5
    success_count = 0
    lock = threading.Lock()

    def concurrent_operation():
        nonlocal success_count
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client.connect(("localhost", 8000))
            # Try to register and login with same username from multiple threads
            if register_and_login_user(client, protocol, "shared_user", "pass"):
                with lock:
                    success_count += 1
        finally:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass

    # Start concurrent threads
    threads = []
    for _ in range(num_threads):
        thread = threading.Thread(target=concurrent_operation)
        thread.start()
        threads.append(thread)

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Verify only one registration succeeded
    assert success_count == 1


def test_message_delivery_confirmation(test_server, protocol):
    """Test message delivery confirmation and status updates"""
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client1.connect(("127.0.0.1", 8000))
        client2.connect(("127.0.0.1", 8000))
        client1.settimeout(5.0)
        client2.settimeout(5.0)

        # Register and login both users
        assert register_and_login_user(client1, protocol, "sender", "pass1")
        assert register_and_login_user(client2, protocol, "receiver", "pass2")

        # Send a message
        message = ChatMessage(
            username="sender",
            content="Test delivery confirmation",
            message_type=MessageType.DM,
            recipients=["receiver"],
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(message)
        framed_data = protocol.frame_message(data)
        client1.send(framed_data)

        # Verify both sender and receiver get the message
        received_by_sender = False
        received_by_receiver = False
        start_time = time.time()

        while (
            not received_by_sender or not received_by_receiver
        ) and time.time() - start_time < 5:
            for client, flag in [(client1, "sender"), (client2, "receiver")]:
                try:
                    response_data = client.recv(1024)
                    if response_data:
                        buffer = response_data
                        while True:
                            message_data, buffer = protocol.extract_message(buffer)
                            if message_data is None:
                                break
                            response = protocol.deserialize_response(message_data)
                            if (
                                response.data
                                and response.data.content
                                == "Test delivery confirmation"
                            ):
                                if flag == "sender":
                                    received_by_sender = True
                                else:
                                    received_by_receiver = True
                except socket.timeout:
                    continue

        assert received_by_sender, "Sender did not receive message confirmation"
        assert received_by_receiver, "Receiver did not receive the message"

    finally:
        for client in [client1, client2]:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass


def test_message_persistence(test_server, protocol):
    """Test message persistence across disconnections and reconnections"""
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client1.connect(("127.0.0.1", 8000))
        client2.connect(("127.0.0.1", 8000))
        client1.settimeout(5.0)
        client2.settimeout(5.0)

        # Register and login both users
        assert register_and_login_user(client1, protocol, "user1", "pass1")
        assert register_and_login_user(client2, protocol, "user2", "pass2")

        # Send messages from user1 to user2
        messages = ["Message 1", "Message 2", "Message 3"]
        for content in messages:
            message = ChatMessage(
                username="user1",
                content=content,
                message_type=MessageType.DM,
                recipients=["user2"],
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(message)
            framed_data = protocol.frame_message(data)
            client1.send(framed_data)
            time.sleep(0.1)

        # Disconnect user2
        client2.close()
        time.sleep(0.5)

        # Reconnect user2 with a new socket and login (not register)
        client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client2.connect(("127.0.0.1", 8000))
        client2.settimeout(5.0)

        # Login directly instead of trying to register
        login_msg = ChatMessage(
            username="user2",
            password="pass2",
            content="",
            message_type=MessageType.LOGIN,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(login_msg)
        framed_data = protocol.frame_message(data)
        client2.send(framed_data)

        # Process login responses
        buffer = b""
        login_success = False
        start_time = time.time()

        while not login_success and time.time() - start_time < 5:
            try:
                response_data = client2.recv(1024)
                if not response_data:
                    break
                buffer += response_data
                while True:
                    message_data, buffer = protocol.extract_message(buffer)
                    if message_data is None:
                        break
                    response = protocol.deserialize_response(message_data)
                    if response.message == SystemMessage.LOGIN_SUCCESS:
                        login_success = True
                        break
            except socket.timeout:
                continue

        assert login_success, "Failed to login after reconnection"

        # Verify unread messages notification
        buffer = b""
        unread_notification_received = False
        start_time = time.time()

        while not unread_notification_received and time.time() - start_time < 5:
            try:
                response_data = client2.recv(1024)
                if response_data:
                    buffer += response_data
                    while True:
                        message_data, buffer = protocol.extract_message(buffer)
                        if message_data is None:
                            break
                        response = protocol.deserialize_response(message_data)
                        if (
                            response.data
                            and "unread messages" in response.data.content.lower()
                        ):
                            unread_notification_received = True
                            break
            except socket.timeout:
                continue

        assert (
            unread_notification_received
        ), "Did not receive unread messages notification"

    finally:
        for client in [client1, client2]:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass


def test_concurrent_message_handling(test_server, protocol):
    """Test handling of concurrent message sending and receiving"""
    num_senders = 3
    messages_per_sender = 5
    receiver = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    senders = []

    try:
        # Connect and register receiver
        receiver.connect(("127.0.0.1", 8000))
        receiver.settimeout(5.0)
        assert register_and_login_user(receiver, protocol, "receiver", "pass")

        # Connect and register senders
        for i in range(num_senders):
            sender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sender.connect(("127.0.0.1", 8000))
            sender.settimeout(5.0)
            assert register_and_login_user(sender, protocol, f"sender{i}", f"pass{i}")
            senders.append(sender)

        # Create threads for concurrent message sending
        def send_messages(sender_socket, sender_id):
            for j in range(messages_per_sender):
                message = ChatMessage(
                    username=f"sender{sender_id}",
                    content=f"Message {j} from sender{sender_id}",
                    message_type=MessageType.DM,
                    recipients=["receiver"],
                    timestamp=datetime.now(),
                )
                data = protocol.serialize_message(message)
                framed_data = protocol.frame_message(data)
                try:
                    sender_socket.send(framed_data)
                    time.sleep(0.1)  # Small delay to avoid overwhelming the server
                except socket.error:
                    break

        # Start sender threads
        sender_threads = []
        for i, sender in enumerate(senders):
            thread = threading.Thread(target=send_messages, args=(sender, i))
            thread.start()
            sender_threads.append(thread)

        # Wait for all senders to complete
        for thread in sender_threads:
            thread.join()

        # Give some time for messages to be processed
        time.sleep(0.5)

        # Verify message reception
        received_messages = set()
        buffer = b""
        start_time = time.time()
        total_expected = num_senders * messages_per_sender

        while len(received_messages) < total_expected and time.time() - start_time < 10:
            try:
                response_data = receiver.recv(1024)
                if not response_data:
                    break
                buffer += response_data

                # Process all complete messages in the buffer
                while True:
                    message_data, new_buffer = protocol.extract_message(buffer)
                    if message_data is None:
                        break
                    buffer = new_buffer
                    try:
                        response = protocol.deserialize_response(message_data)
                        if response.data and isinstance(response.data.content, str):
                            if (
                                "Message" in response.data.content
                                and "from sender" in response.data.content
                            ):
                                received_messages.add(response.data.content)
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        continue

            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving data: {e}")
                break

        # Verify we received the expected number of messages
        assert (
            len(received_messages) == total_expected
        ), f"Expected {total_expected} messages, got {len(received_messages)}"

        # Verify the content of messages
        expected_messages = set()
        for i in range(num_senders):
            for j in range(messages_per_sender):
                expected_messages.add(f"Message {j} from sender{i}")

        received_contents = {msg.split(" from ")[1] for msg in received_messages}
        expected_contents = {msg.split(" from ")[1] for msg in expected_messages}
        assert (
            received_contents == expected_contents
        ), "Message contents do not match expected values"

    finally:
        for client in [receiver] + senders:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass


def test_error_recovery(test_server, protocol):
    """Test server's ability to recover from various error conditions"""

    def connect_and_login():
        """Helper function to create connection and login"""
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", 8000))
        client.settimeout(5.0)
        assert register_and_login_user(client, protocol, "testuser", "testpass")
        return client

    def reconnect_and_login():
        """Helper function to reconnect and login existing user"""
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", 8000))
        client.settimeout(5.0)

        login_msg = ChatMessage(
            username="testuser",
            password="testpass",
            content="",
            message_type=MessageType.LOGIN,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(login_msg)
        framed_data = protocol.frame_message(data)
        client.send(framed_data)

        # Wait for login success
        buffer = b""
        login_success = False
        start_time = time.time()
        while not login_success and time.time() - start_time < 5:
            try:
                response_data = client.recv(1024)
                if not response_data:
                    break
                buffer += response_data
                while True:
                    message_data, new_buffer = protocol.extract_message(buffer)
                    if message_data is None:
                        break
                    buffer = new_buffer
                    response = protocol.deserialize_response(message_data)
                    if response.message == SystemMessage.LOGIN_SUCCESS:
                        login_success = True
                        break
            except socket.timeout:
                continue

        assert login_success, "Failed to login after reconnection"
        return client

    try:
        # Initial connection and registration
        client = connect_and_login()

        # Test invalid message format
        client.send(b"invalid data format")
        time.sleep(0.5)
        client.close()

        # Reconnect and test large message
        client = reconnect_and_login()
        large_content = "A" * (100 * 1024)  # 100KB message
        message = ChatMessage(
            username="testuser",
            content=large_content,
            message_type=MessageType.CHAT,
            timestamp=datetime.now(),
        )

        try:
            data = protocol.serialize_message(message)
            framed_data = protocol.frame_message(data)
            client.send(framed_data)
        except ValueError as e:
            print(f"Expected error for large message: {e}")
        except socket.error as e:
            print(f"Socket error sending large message: {e}")

        time.sleep(0.5)
        client.close()

        # Reconnect and test normal message
        client = reconnect_and_login()
        test_message = ChatMessage(
            username="testuser",
            content="Test after large message",
            message_type=MessageType.CHAT,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(test_message)
        framed_data = protocol.frame_message(data)
        client.send(framed_data)

        # Verify message reception
        buffer = b""
        message_received = False
        start_time = time.time()

        while not message_received and time.time() - start_time < 5:
            try:
                response_data = client.recv(1024)
                if not response_data:
                    break
                buffer += response_data
                while True:
                    message_data, new_buffer = protocol.extract_message(buffer)
                    if message_data is None:
                        break
                    buffer = new_buffer
                    try:
                        response = protocol.deserialize_response(message_data)
                        if (
                            response.data
                            and response.data.content == "Test after large message"
                        ):
                            message_received = True
                            break
                    except Exception as e:
                        print(f"Error processing response: {e}")
                        continue
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving data: {e}")
                break

        assert message_received, "Failed to recover after sending large message"
        client.close()

        # Test malformed protocol message
        client = reconnect_and_login()
        malformed_msg = b'{"type": "invalid", "content": "malformed"}'
        client.send(malformed_msg)
        time.sleep(0.5)
        client.close()

        # Test partial message
        client = reconnect_and_login()
        partial_msg = protocol.frame_message(b'{"type": "chat", "content":')
        client.send(partial_msg[: len(partial_msg) // 2])
        time.sleep(0.5)
        client.close()

        # Final test with normal message
        client = reconnect_and_login()
        normal_message = ChatMessage(
            username="testuser",
            content="Test after malformed message",
            message_type=MessageType.CHAT,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(normal_message)
        framed_data = protocol.frame_message(data)
        client.send(framed_data)

        # Verify message reception
        buffer = b""
        message_received = False
        start_time = time.time()

        while not message_received and time.time() - start_time < 5:
            try:
                response_data = client.recv(1024)
                if not response_data:
                    break
                buffer += response_data
                while True:
                    message_data, new_buffer = protocol.extract_message(buffer)
                    if message_data is None:
                        break
                    buffer = new_buffer
                    try:
                        response = protocol.deserialize_response(message_data)
                        if (
                            response.data
                            and response.data.content == "Test after malformed message"
                        ):
                            message_received = True
                            break
                    except Exception as e:
                        print(f"Error processing response: {e}")
                        continue
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving data: {e}")
                break

        assert message_received, "Failed to recover after sending malformed message"

    finally:
        try:
            client.shutdown(socket.SHUT_RDWR)
            client.close()
        except:
            pass


def test_user_list_updates(test_server, protocol):
    """Test user list updates when users join and leave"""
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client1.connect(("127.0.0.1", 8000))
        client1.settimeout(5.0)

        # Register and login first user
        assert register_and_login_user(client1, protocol, "user1", "pass1")

        # Connect and register second user
        client2.connect(("127.0.0.1", 8000))
        client2.settimeout(5.0)
        assert register_and_login_user(client2, protocol, "user2", "pass2")

        # Verify first user receives notification about second user
        buffer = b""
        user_joined = False
        start_time = time.time()

        while not user_joined and time.time() - start_time < 5:
            try:
                response_data = client1.recv(1024)
                if response_data:
                    buffer += response_data
                    while True:
                        message_data, buffer = protocol.extract_message(buffer)
                        if message_data is None:
                            break
                        response = protocol.deserialize_response(message_data)
                        if (
                            response.data
                            and "user2 has joined" in response.data.content.lower()
                        ):
                            user_joined = True
                            break
            except socket.timeout:
                continue

        assert user_joined, "Did not receive user join notification"

        # Disconnect second user
        client2.close()
        time.sleep(0.5)

        # Verify first user receives notification about second user leaving
        buffer = b""
        user_left = False
        start_time = time.time()

        while not user_left and time.time() - start_time < 5:
            try:
                response_data = client1.recv(1024)
                if response_data:
                    buffer += response_data
                    while True:
                        message_data, buffer = protocol.extract_message(buffer)
                        if message_data is None:
                            break
                        response = protocol.deserialize_response(message_data)
                        if (
                            response.data
                            and "user2 has logged out" in response.data.content.lower()
                        ):
                            user_left = True
                            break
            except socket.timeout:
                continue

        assert user_left, "Did not receive user leave notification"

    finally:
        for client in [client1, client2]:
            try:
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass
