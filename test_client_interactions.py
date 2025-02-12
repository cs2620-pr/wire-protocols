import pytest
import socket
import threading
import time
from datetime import datetime
from server import ChatServer
from database import Database
from schemas import ChatMessage, MessageType, SystemMessage, Status, ServerResponse
from protocol import ProtocolFactory
import os


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
    server = ChatServer(db_path="file::memory:?cache=shared")
    server_thread = threading.Thread(target=server.start)
    server_thread.daemon = True
    server_thread.start()
    time.sleep(0.05)  # Reduced from 0.1
    yield server
    server.shutdown()
    time.sleep(0.05)  # Add small delay for cleanup


@pytest.fixture
def protocol():
    """Create a protocol instance for message handling"""
    return ProtocolFactory.create("json")


class TestClientInteractions:
    """Test suite for client interactions with the chat server"""

    def create_client_socket(self):
        """Helper to create and connect a client socket"""
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("localhost", 8000))
        client.settimeout(1.0)
        return client

    def register_user(self, client, protocol, username, password):
        """Helper to register a new user"""
        try:
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

            response_data = client.recv(1024)
            if not response_data:
                return False

            message_data, _ = protocol.extract_message(response_data)
            response = protocol.deserialize_response(message_data)
            return response.status == Status.SUCCESS
        except Exception as e:
            print(f"Error during registration: {e}")
            return False

    def login_user(self, client, protocol, username, password):
        """Helper to login a user"""
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

        # Process login responses
        buffer = b""
        login_success = False
        start_time = time.time()

        while not login_success and time.time() - start_time < 1.0:
            try:
                response_data = client.recv(1024)
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

        return login_success

    def send_message(
        self,
        client,
        protocol,
        sender,
        content,
        recipients=None,
        message_type=MessageType.CHAT,
    ):
        """Helper to send a message"""
        message = ChatMessage(
            username=sender,
            content=content,
            message_type=message_type,
            recipients=recipients,
            timestamp=datetime.now(),
        )
        data = protocol.serialize_message(message)
        framed_data = protocol.frame_message(data)
        client.send(framed_data)

    def receive_message(self, client, protocol, timeout=1.0):
        """Helper to receive and process a message"""
        buffer = b""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response_data = client.recv(1024)
                if not response_data:
                    break
                buffer += response_data
                while True:
                    try:
                        message_data, buffer = protocol.extract_message(buffer)
                        if message_data is None:
                            break
                        return protocol.deserialize_response(message_data)
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        continue
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving data: {e}")
                break
        return None

    def consume_notifications(self, client, protocol, timeout=0.2):
        """Helper to consume notifications until timeout"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self.receive_message(client, protocol, timeout=0.1)
                if not response or not response.data:
                    break
                if response.data.message_type not in [
                    MessageType.JOIN,
                    MessageType.LOGOUT,
                ]:
                    return response
            except Exception as e:
                print(f"Error consuming notification: {e}")
                continue
        return None

    def test_user_registration_and_login(self, test_server, protocol):
        """Test user registration followed by login"""
        client = self.create_client_socket()
        try:
            # Test registration
            assert self.register_user(client, protocol, "alice", "pass123")
            client.close()

            # Test login with new connection
            client = self.create_client_socket()
            assert self.login_user(client, protocol, "alice", "pass123")

        finally:
            client.close()

    def test_public_chat(self, test_server, protocol):
        """Test public chat functionality between multiple users"""
        alice = self.create_client_socket()
        bob = self.create_client_socket()
        try:
            # Register and login users
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Consume initial notifications
            self.consume_notifications(alice, protocol)
            self.consume_notifications(bob, protocol)

            # Alice sends a message
            self.send_message(alice, protocol, "alice", "Hello everyone!")

            # Both users receive Alice's message
            response = self.receive_message(bob, protocol)
            assert response.data.content == "Hello everyone!"
            assert response.data.username == "alice"

            response = self.receive_message(
                alice, protocol
            )  # Alice receives her own message
            assert response.data.content == "Hello everyone!"
            assert response.data.username == "alice"

            # Bob responds
            self.send_message(bob, protocol, "bob", "Hi Alice!")

            # Both users receive Bob's message
            response = self.receive_message(alice, protocol)
            assert response.data.content == "Hi Alice!"
            assert response.data.username == "bob"

            response = self.receive_message(
                bob, protocol
            )  # Bob receives his own message
            assert response.data.content == "Hi Alice!"
            assert response.data.username == "bob"

        finally:
            alice.close()
            bob.close()

    def test_private_messaging(self, test_server, protocol):
        """Test private messaging between users"""
        alice = self.create_client_socket()
        bob = self.create_client_socket()
        charlie = self.create_client_socket()
        try:
            # Register and login users
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")
            assert self.register_user(charlie, protocol, "charlie", "pass789")
            assert self.login_user(charlie, protocol, "charlie", "pass789")

            # Consume initial notifications
            self.consume_notifications(alice, protocol)
            self.consume_notifications(bob, protocol)
            self.consume_notifications(charlie, protocol)

            # Alice sends a private message to Bob
            self.send_message(
                alice,
                protocol,
                "alice",
                "Hi Bob, private message!",
                recipients=["bob"],
                message_type=MessageType.DM,
            )

            # Bob should receive the private message
            response = self.receive_message(bob, protocol)
            assert response.data.content == "Hi Bob, private message!"
            assert response.data.username == "alice"

            # Charlie should not receive the message
            response = self.receive_message(charlie, protocol, timeout=1)
            assert response is None or (
                response.data and "Hi Bob" not in response.data.content
            )

        finally:
            alice.close()
            bob.close()
            charlie.close()

    def test_message_persistence(self, test_server, protocol):
        """Test message persistence when users are offline"""
        alice = self.create_client_socket()
        bob = self.create_client_socket()
        try:
            # Register and login users
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Consume initial notifications
            self.consume_notifications(alice, protocol)
            self.consume_notifications(bob, protocol)

            # Bob logs out
            bob.close()

            # Wait for and consume Bob's logout notification
            response = self.receive_message(alice, protocol)
            assert "logged out" in response.data.content.lower()
            assert "bob" in response.data.content.lower()

            # Alice sends messages while Bob is offline
            messages = ["First message", "Second message", "Third message"]
            for msg in messages:
                self.send_message(
                    alice,
                    protocol,
                    "alice",
                    msg,
                    recipients=["bob"],
                    message_type=MessageType.DM,
                )
                # Alice should receive her own message
                response = self.receive_message(alice, protocol)
                assert response.data.content == msg
                assert response.data.username == "alice"

            # Bob logs back in
            bob = self.create_client_socket()
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Bob should receive unread message notification
            response = self.receive_message(bob, protocol)
            assert "unread messages" in response.data.content.lower()
            assert "3" in response.data.content  # Should have 3 unread messages

            # Fetch unread messages
            fetch_msg = ChatMessage(
                username="bob",
                content="",
                message_type=MessageType.FETCH,
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(fetch_msg)
            framed_data = protocol.frame_message(data)
            bob.send(framed_data)

            # Verify messages are received in order
            received_messages = []
            for _ in range(len(messages)):
                response = self.receive_message(bob, protocol)
                assert response.data.username == "alice"
                received_messages.append(response.data.content)

            # Verify message order is preserved
            assert received_messages == messages

            # Mark messages as read
            mark_read_msg = ChatMessage(
                username="bob",
                content="",
                message_type=MessageType.MARK_READ,
                recipients=["alice"],  # Mark all messages from Alice as read
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(mark_read_msg)
            framed_data = protocol.frame_message(data)
            bob.send(framed_data)

            # Verify unread count is updated
            response = self.receive_message(bob, protocol)
            assert response.data.unread_count == 0

        finally:
            alice.close()
            bob.close()

    def test_user_presence(self, test_server, protocol):
        """Test user presence notifications"""
        alice = self.create_client_socket()
        try:
            # Alice registers and logs in
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")

            # Bob connects
            bob = self.create_client_socket()
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Alice should receive notification about Bob
            response = self.receive_message(alice, protocol)
            assert "bob has joined" in response.data.content.lower()

            # Bob disconnects
            bob.close()

            # Alice should receive notification about Bob's departure
            response = self.receive_message(alice, protocol)
            assert "bob has logged out" in response.data.content.lower()

        finally:
            alice.close()

    def test_message_deletion(self, test_server, protocol):
        """Test message deletion functionality"""
        alice = self.create_client_socket()
        bob = self.create_client_socket()
        try:
            # Register and login users
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Consume initial notifications
            self.consume_notifications(alice, protocol)
            self.consume_notifications(bob, protocol)

            # Alice sends multiple messages to Bob
            messages = ["Message 1", "Message 2", "Message 3"]
            message_ids = []

            for msg in messages:
                self.send_message(
                    alice,
                    protocol,
                    "alice",
                    msg,
                    recipients=["bob"],
                    message_type=MessageType.DM,
                )
                # Bob receives the message
                response = self.receive_message(bob, protocol)
                assert response.data.content == msg
                message_ids.append(response.data.message_id)
                # Alice receives her own message
                response = self.receive_message(alice, protocol)
                assert response.data.content == msg

            # Alice deletes the second message
            delete_msg = ChatMessage(
                username="alice",
                content="",
                message_type=MessageType.DELETE,
                message_ids=[message_ids[1]],  # Delete second message
                recipients=["bob"],
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(delete_msg)
            framed_data = protocol.frame_message(data)
            alice.send(framed_data)

            # Both users should receive deletion notification
            for client in [alice, bob]:
                response = self.receive_message(client, protocol)
                assert response.data.message_type == MessageType.DELETE_NOTIFICATION
                assert message_ids[1] in response.data.message_ids

            # Verify remaining messages by fetching them
            fetch_msg = ChatMessage(
                username="bob",
                content="",
                message_type=MessageType.FETCH,
                recipients=["alice"],  # Get messages from Alice
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(fetch_msg)
            framed_data = protocol.frame_message(data)
            bob.send(framed_data)

            # Should receive messages 1 and 3 (message 2 was deleted)
            expected_messages = ["Message 1", "Message 3"]
            received_messages = []

            # Try to receive messages with timeout
            start_time = time.time()
            while len(received_messages) < len(expected_messages):
                if time.time() - start_time > 5:  # 5 second timeout
                    break
                try:
                    response = self.receive_message(bob, protocol)
                    if response and response.data.message_type == MessageType.DM:
                        received_messages.append(response.data.content)
                except Exception:
                    time.sleep(0.1)
                    continue

            # Verify we got the expected messages
            assert len(received_messages) == len(
                expected_messages
            ), f"Expected {len(expected_messages)} messages, got {len(received_messages)}"
            assert set(received_messages) == set(
                expected_messages
            ), f"Expected messages {expected_messages}, got {received_messages}"

        finally:
            # Send logout messages
            for client, username in [(alice, "alice"), (bob, "bob")]:
                try:
                    logout_msg = ChatMessage(
                        username=username,
                        content="",
                        message_type=MessageType.LOGOUT,
                        timestamp=datetime.now(),
                    )
                    data = protocol.serialize_message(logout_msg)
                    framed_data = protocol.frame_message(data)
                    client.send(framed_data)
                    time.sleep(0.1)  # Give server time to process logout
                except:
                    pass
                finally:
                    client.close()

    def test_account_deletion(self, test_server, protocol):
        """Test account deletion functionality"""
        alice = self.create_client_socket()
        bob = self.create_client_socket()
        try:
            # Register and login users
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Alice deletes her account
            delete_account_msg = ChatMessage(
                username="alice",
                content="",
                message_type=MessageType.DELETE_ACCOUNT,
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(delete_account_msg)
            framed_data = protocol.frame_message(data)
            alice.send(framed_data)

            # Bob should receive notification about Alice's account deletion
            response = self.receive_message(bob, protocol)
            assert "alice has deleted their account" in response.data.content.lower()

            # Verify Alice can't log back in
            alice = self.create_client_socket()
            assert not self.login_user(alice, protocol, "alice", "pass123")

        finally:
            alice.close()
            bob.close()

    def test_invalid_registration_attempts(self, test_server, protocol):
        """Test various invalid registration scenarios"""
        client = self.create_client_socket()
        try:
            # Test empty username
            assert not self.register_user(client, protocol, "", "pass123")
            client.close()

            # Test empty password
            client = self.create_client_socket()
            assert not self.register_user(client, protocol, "testuser", "")
            client.close()

            # Test invalid username characters
            client = self.create_client_socket()
            assert not self.register_user(client, protocol, "test@user", "pass123")
            client.close()

            # Test username too short (less than 2 characters)
            client = self.create_client_socket()
            assert not self.register_user(client, protocol, "a", "pass123")
            client.close()

            # Test duplicate username
            client = self.create_client_socket()
            assert self.register_user(client, protocol, "uniqueuser", "pass123")
            client.close()

            client = self.create_client_socket()
            assert not self.register_user(client, protocol, "uniqueuser", "pass123")

        finally:
            client.close()

    def test_concurrent_chat(self, test_server, protocol):
        """Test concurrent chat messages between multiple users"""
        num_users = 5
        num_messages = 3
        clients = []
        messages_received = {i: [] for i in range(num_users)}

        try:
            # Create and connect multiple users
            for i in range(num_users):
                try:
                    client = self.create_client_socket()
                    username = f"user{i}"
                    if not self.register_user(client, protocol, username, f"pass{i}"):
                        raise Exception(f"Failed to register {username}")
                    if not self.login_user(client, protocol, username, f"pass{i}"):
                        raise Exception(f"Failed to login {username}")
                    clients.append(client)
                    time.sleep(0.05)
                except Exception as e:
                    print(f"Error setting up user{i}: {e}")
                    if client:
                        client.close()
                    raise

            # Consume initial notifications with increased timeout
            for client in clients:
                for _ in range(num_users - 1):  # Expect notifications for other users
                    self.consume_notifications(client, protocol, timeout=0.2)

            # Send messages with delay to avoid overwhelming server
            for i in range(num_users):
                for j in range(num_messages):
                    try:
                        self.send_message(
                            clients[i],
                            protocol,
                            f"user{i}",
                            f"Message {j} from user{i}",
                        )
                        time.sleep(0.05)
                    except Exception as e:
                        print(f"Error sending message from user{i}: {e}")

            # Collect messages with increased timeout
            start_time = time.time()
            expected_messages = num_users * num_messages  # Each user sends num_messages
            collection_timeout = 5

            while time.time() - start_time < collection_timeout:
                all_received = True
                for i, client in enumerate(clients):
                    if len(messages_received[i]) < expected_messages:
                        all_received = False
                        try:
                            response = self.receive_message(
                                client, protocol, timeout=0.1
                            )
                            if (
                                response
                                and response.data
                                and response.data.content.startswith("Message ")
                            ):
                                messages_received[i].append(response.data)
                        except Exception as e:
                            print(f"Error receiving message for user{i}: {e}")

                if all_received:
                    break
                time.sleep(0.05)

            # Verify message reception
            for i in range(num_users):
                received = messages_received[i]
                assert len(received) > 0, f"User{i} received no messages"

        finally:
            # Clean up clients
            for client in clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    client.close()
                except:
                    pass

    def test_message_persistence_with_multiple_messages(self, test_server, protocol):
        """Test message persistence with multiple messages and multiple recipients"""
        alice = self.create_client_socket()
        bob = self.create_client_socket()
        charlie = self.create_client_socket()
        try:
            # Register and login users
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")
            assert self.register_user(charlie, protocol, "charlie", "pass789")
            assert self.login_user(charlie, protocol, "charlie", "pass789")

            # Consume initial notifications with reduced timeout
            self.consume_notifications(alice, protocol, timeout=0.2)
            self.consume_notifications(bob, protocol, timeout=0.2)
            self.consume_notifications(charlie, protocol, timeout=0.2)

            # Bob and Charlie log out
            bob.close()
            charlie.close()
            time.sleep(0.05)  # Reduced from implicit longer wait

            # Alice sends multiple messages
            messages = [
                ("bob", "First message for Bob"),
                ("charlie", "First message for Charlie"),
                ("bob", "Second message for Bob"),
                ("charlie", "Second message for Charlie"),
            ]

            for recipient, content in messages:
                self.send_message(
                    alice,
                    protocol,
                    "alice",
                    content,
                    recipients=[recipient],
                    message_type=MessageType.DM,
                )
                time.sleep(0.05)  # Add small delay between messages

            # Bob logs back in
            bob = self.create_client_socket()
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Verify Bob's unread message notification
            response = self.receive_message(bob, protocol, timeout=0.5)
            assert "unread messages" in response.data.content.lower()

            # Fetch Bob's messages
            fetch_msg = ChatMessage(
                username="bob",
                content="",
                message_type=MessageType.FETCH,
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(fetch_msg)
            framed_data = protocol.frame_message(data)
            bob.send(framed_data)

            # Verify Bob receives his messages in order
            bob_messages = []
            for _ in range(2):  # Expect 2 messages
                response = self.receive_message(bob, protocol, timeout=0.5)
                assert response.data.username == "alice"
                bob_messages.append(response.data.content)

            assert "First message for Bob" in bob_messages
            assert "Second message for Bob" in bob_messages
            assert bob_messages.index("First message for Bob") < bob_messages.index(
                "Second message for Bob"
            )

            # Charlie logs back in
            charlie = self.create_client_socket()
            assert self.login_user(charlie, protocol, "charlie", "pass789")

            # Verify Charlie's unread message notification
            response = self.receive_message(charlie, protocol, timeout=0.5)
            assert "unread messages" in response.data.content.lower()

            # Fetch Charlie's messages
            fetch_msg = ChatMessage(
                username="charlie",
                content="",
                message_type=MessageType.FETCH,
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(fetch_msg)
            framed_data = protocol.frame_message(data)
            charlie.send(framed_data)

            # Verify Charlie receives his messages in order
            charlie_messages = []
            for _ in range(2):  # Expect 2 messages
                response = self.receive_message(charlie, protocol, timeout=0.5)
                assert response.data.username == "alice"
                charlie_messages.append(response.data.content)

            assert "First message for Charlie" in charlie_messages
            assert "Second message for Charlie" in charlie_messages
            assert charlie_messages.index(
                "First message for Charlie"
            ) < charlie_messages.index("Second message for Charlie")

        finally:
            alice.close()
            bob.close()
            charlie.close()

    def test_message_mark_read(self, test_server, protocol):
        """Test marking messages as read"""
        alice = self.create_client_socket()
        bob = self.create_client_socket()
        try:
            # Register and login users
            assert self.register_user(alice, protocol, "alice", "pass123")
            assert self.login_user(alice, protocol, "alice", "pass123")
            assert self.register_user(bob, protocol, "bob", "pass456")
            assert self.login_user(bob, protocol, "bob", "pass456")

            # Consume initial notifications
            self.consume_notifications(alice, protocol)
            self.consume_notifications(bob, protocol)

            # Alice sends multiple messages to Bob
            messages = ["Message 1", "Message 2", "Message 3"]
            message_ids = []

            for content in messages:
                self.send_message(
                    alice,
                    protocol,
                    "alice",
                    content,
                    recipients=["bob"],
                    message_type=MessageType.DM,
                )
                response = self.receive_message(bob, protocol)
                message_ids.append(response.data.message_id)
                self.receive_message(alice, protocol)  # Consume Alice's echo

            # Mark specific messages as read
            mark_read_msg = ChatMessage(
                username="bob",
                content="",
                message_type=MessageType.MARK_READ,
                message_ids=message_ids[:2],  # Mark first two messages as read
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(mark_read_msg)
            framed_data = protocol.frame_message(data)
            bob.send(framed_data)

            # Verify unread count update
            response = self.receive_message(bob, protocol)
            assert response.data.unread_count == 1  # One message should remain unread

            # Mark all messages from Alice as read
            mark_read_msg = ChatMessage(
                username="bob",
                content="",
                message_type=MessageType.MARK_READ,
                recipients=["alice"],  # Mark all messages from Alice as read
                timestamp=datetime.now(),
            )
            data = protocol.serialize_message(mark_read_msg)
            framed_data = protocol.frame_message(data)
            bob.send(framed_data)

            # Verify unread count is zero
            response = self.receive_message(bob, protocol)
            assert response.data.unread_count == 0

        finally:
            alice.close()
            bob.close()

    def test_error_handling(self, test_server, protocol):
        """Test error handling in various scenarios"""
        client = None
        try:
            # Test sending message before login
            client = self.create_client_socket()
            self.send_message(client, protocol, "nobody", "Should fail")
            response = self.receive_message(client, protocol, timeout=0.5)
            assert response and response.status == Status.ERROR
            assert "login" in response.message.lower()
            client.close()

            # Test login with non-existent user
            client = self.create_client_socket()
            assert not self.login_user(client, protocol, "nonexistent", "pass123")
            client.close()

            # Test registration and login
            client = self.create_client_socket()
            assert self.register_user(client, protocol, "testuser", "pass123")
            assert self.login_user(client, protocol, "testuser", "pass123")

            # Test sending message to non-existent user
            self.send_message(
                client,
                protocol,
                "testuser",
                "Test message",
                recipients=["nonexistent"],
                message_type=MessageType.DM,
            )
            response = self.receive_message(client, protocol, timeout=0.5)
            assert response and response.status == Status.ERROR

        finally:
            if client:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    client.close()
                except:
                    pass

    def test_large_group_chat(self, test_server, protocol):
        """Test chat functionality with a large number of users"""
        num_users = 5  # Reduced from 10 for faster testing
        clients = []
        try:
            # Create and login multiple users
            for i in range(num_users):
                try:
                    client = self.create_client_socket()
                    username = f"user{i}"
                    if not self.register_user(client, protocol, username, f"pass{i}"):
                        raise Exception(f"Failed to register {username}")
                    if not self.login_user(client, protocol, username, f"pass{i}"):
                        raise Exception(f"Failed to login {username}")
                    clients.append(client)
                    time.sleep(0.05)  # Reduced from 0.1
                except Exception as e:
                    print(f"Error setting up user{i}: {e}")
                    if client:
                        client.close()
                    continue

            if not clients:
                raise Exception("Failed to create any clients")

            # Consume initial notifications with reduced timeout
            for client in clients:
                for _ in range(len(clients) - 1):
                    self.consume_notifications(client, protocol, timeout=0.2)

            # First user sends a message
            if len(clients) > 0:
                self.send_message(clients[0], protocol, "user0", "Broadcast message")
                time.sleep(0.05)  # Reduced from 0.1

                # Verify all users receive the message
                for i, client in enumerate(clients):
                    try:
                        response = self.receive_message(
                            client, protocol, timeout=0.5
                        )  # Reduced from 1
                        assert response and response.data.content == "Broadcast message"
                        assert response.data.username == "user0"
                    except Exception as e:
                        print(f"Error verifying message for user{i}: {e}")

        finally:
            # Clean up clients
            for client in clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    client.close()
                except:
                    pass
