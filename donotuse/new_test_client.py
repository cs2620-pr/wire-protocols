import pytest
from unittest.mock import Mock, patch
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
import sys
import time
from new_client import ChatClient
from new_models import *


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance"""
    app = QApplication(sys.argv)
    yield app


@pytest.fixture
def mock_socket():
    """Mock socket for testing"""
    with patch("socket.socket") as mock:
        socket_instance = Mock()
        mock.return_value = socket_instance
        yield socket_instance


@pytest.fixture
def client(qapp, mock_socket, qtbot):
    """Create client instance with mocked socket"""
    with patch("threading.Thread"), patch.object(
        ChatClient, "connect_to_server"
    ), patch("PyQt5.QtWidgets.QMessageBox.critical"), patch(
        "PyQt5.QtWidgets.QMessageBox.information"
    ):  # Auto-dismiss message boxes
        client = ChatClient()
        client.show()  # Need to show for qtbot to work
        qtbot.addWidget(client)  # Register with qtbot

        # Setup mock responses
        mock_socket.recv.return_value = ProtocolHelper.encode(
            BaseResponse(status=ResponseStatus.SUCCESS, message="OK"), Protocol.JSON
        )
        yield client
        client.close()


def test_login_page(client):
    """Test login page elements"""
    assert client.stacked_widget.currentWidget() == client.login_page
    assert hasattr(client.login_page, "username_input")
    assert hasattr(client.login_page, "password_input")
    assert hasattr(client.login_page, "login_button")
    assert hasattr(client.login_page, "create_account_button")


def test_create_account(client, mock_socket, qtbot):
    """Test account creation"""
    login_page = client.login_page

    # Setup mock response
    mock_socket.recv.return_value = ProtocolHelper.encode(
        BaseResponse(status=ResponseStatus.SUCCESS, message="Account created"),
        Protocol.JSON,
    )

    # Fill in registration form
    qtbot.keyClicks(login_page.username_input, "testuser")
    qtbot.keyClicks(login_page.password_input, "testpass")

    # Click create account
    with patch.object(client, "send_data"), patch.object(
        client, "receive_data"
    ) as mock_receive:
        mock_receive.return_value = {
            "status": ResponseStatus.SUCCESS,
            "message": "Account created",
        }
        qtbot.mouseClick(login_page.create_account_button, Qt.LeftButton)
        qtbot.wait(100)

    # Fields should be cleared on success
    assert login_page.username_input.text() == ""
    assert login_page.password_input.text() == ""


def test_login(client, mock_socket, qtbot):
    """Test login functionality"""
    login_page = client.login_page

    # Setup mock response
    mock_socket.recv.return_value = ProtocolHelper.encode(
        AuthResponse(
            status=ResponseStatus.SUCCESS, message="Login successful", unread_count=0
        ),
        Protocol.JSON,
    )

    # Fill in login form
    qtbot.keyClicks(login_page.username_input, "testuser")
    qtbot.keyClicks(login_page.password_input, "testpass")

    # Click login
    with patch.object(client, "send_data"), patch.object(
        client, "receive_data"
    ) as mock_receive:
        # First response for login
        mock_receive.side_effect = [
            {
                "status": ResponseStatus.SUCCESS,
                "message": "Login successful",
                "unread_count": 0,
            },
            # Second response for fetch_online_users
            {
                "status": ResponseStatus.SUCCESS,
                "message": "Users retrieved",
                "data": {"users": ["user1", "user2"]},
            },
        ]
        qtbot.mouseClick(login_page.login_button, Qt.LeftButton)
        qtbot.wait(100)

    # Verify navigation to chat page
    assert client.stacked_widget.currentWidget() == client.chat_page
    assert client.current_user == "testuser"


def test_send_message(client, mock_socket, qtbot):
    """Test message sending"""
    # Login first
    client.current_user = "testuser"
    client.stacked_widget.setCurrentWidget(client.chat_page)

    # Setup mock response
    mock_socket.recv.return_value = ProtocolHelper.encode(
        BaseResponse(status=ResponseStatus.SUCCESS, message="Message sent"),
        Protocol.JSON,
    )

    # Send message
    qtbot.keyClicks(client.recipient_input, "otheruser")
    qtbot.keyClicks(client.message_input, "Test message")

    with patch.object(client, "send_data"), patch.object(
        client, "receive_data"
    ) as mock_receive:
        mock_receive.return_value = {
            "status": ResponseStatus.SUCCESS,
            "message": "Message sent",
        }
        qtbot.mouseClick(client.send_button, Qt.LeftButton)
        qtbot.wait(100)

    # Message should appear in chat history
    assert "Test message" in client.chat_history.toPlainText()
    assert client.message_input.text() == ""


def test_receive_message(client, qtbot):
    """Test message receiving"""
    # Login first
    client.current_user = "testuser"
    client.stacked_widget.setCurrentWidget(client.chat_page)

    # Simulate receiving message
    message = ChatMessage(
        sender="otheruser",
        recipient="testuser",
        content="Incoming message",
        timestamp=time.time(),
    )
    client.signals.message_received.emit(message)
    qtbot.wait(100)

    # Message should appear in chat history
    assert "Incoming message" in client.chat_history.toPlainText()


def test_user_status(client, qtbot):
    """Test user status updates"""
    # Login first
    client.current_user = "testuser"
    client.stacked_widget.setCurrentWidget(client.chat_page)

    # Simulate user coming online
    client.signals.user_status_changed.emit("otheruser", True)
    qtbot.wait(100)

    # Verify user appears in list
    online_users = client.online_users_list
    assert "otheruser" in [
        online_users.item(i).text() for i in range(online_users.count())
    ]

    # Simulate user going offline
    client.signals.user_status_changed.emit("otheruser", False)
    qtbot.wait(100)

    # Verify user removed from list
    assert "otheruser" not in [
        online_users.item(i).text() for i in range(online_users.count())
    ]


def test_login_validation(client, qtbot):
    """Test login input validation"""
    login_page = client.login_page

    # Test empty fields
    qtbot.mouseClick(login_page.login_button, Qt.LeftButton)
    qtbot.wait(100)

    # Test username only
    qtbot.keyClicks(login_page.username_input, "testuser")
    qtbot.mouseClick(login_page.login_button, Qt.LeftButton)
    qtbot.wait(100)

    # Test password only
    login_page.username_input.clear()
    qtbot.keyClicks(login_page.password_input, "testpass")
    qtbot.mouseClick(login_page.login_button, Qt.LeftButton)
    qtbot.wait(100)

    # Should still be on login page
    assert client.stacked_widget.currentWidget() == client.login_page


def test_failed_login(client, mock_socket, qtbot):
    """Test failed login attempt"""
    login_page = client.login_page

    # Fill in login form
    qtbot.keyClicks(login_page.username_input, "wronguser")
    qtbot.keyClicks(login_page.password_input, "wrongpass")

    # Click login
    with patch.object(client, "send_data"), patch.object(
        client, "receive_data"
    ) as mock_receive:
        mock_receive.return_value = {
            "status": ResponseStatus.ERROR,
            "message": "Invalid credentials",
        }
        qtbot.mouseClick(login_page.login_button, Qt.LeftButton)
        qtbot.wait(100)

    # Should stay on login page
    assert client.stacked_widget.currentWidget() == client.login_page
    assert client.current_user is None


def test_message_validation(client, qtbot):
    """Test message input validation"""
    client.current_user = "testuser"
    client.stacked_widget.setCurrentWidget(client.chat_page)

    # Test empty recipient
    qtbot.keyClicks(client.message_input, "Test message")
    qtbot.mouseClick(client.send_button, Qt.LeftButton)
    qtbot.wait(100)

    # Test empty message
    client.message_input.clear()
    qtbot.keyClicks(client.recipient_input, "recipient")
    qtbot.mouseClick(client.send_button, Qt.LeftButton)
    qtbot.wait(100)

    # Message should not appear in chat history
    assert "Test message" not in client.chat_history.toPlainText()


def test_failed_message_send(client, mock_socket, qtbot):
    """Test failed message sending"""
    client.current_user = "testuser"
    client.stacked_widget.setCurrentWidget(client.chat_page)

    # Fill message form
    qtbot.keyClicks(client.recipient_input, "nonexistent")
    qtbot.keyClicks(client.message_input, "Test message")

    # Send message
    with patch.object(client, "send_data"), patch.object(
        client, "receive_data"
    ) as mock_receive:
        mock_receive.return_value = {
            "status": ResponseStatus.ERROR,
            "message": "Recipient not found",
        }
        qtbot.mouseClick(client.send_button, Qt.LeftButton)
        qtbot.wait(100)

    # Message should not appear in chat history
    assert "Test message" not in client.chat_history.toPlainText()
    assert client.message_input.text() == "Test message"  # Text should remain


def test_multiple_messages(client, qtbot):
    """Test handling multiple messages"""
    client.current_user = "testuser"
    client.stacked_widget.setCurrentWidget(client.chat_page)

    # Send multiple messages
    messages = [
        ("sender1", "Hello"),
        ("sender2", "Hi there"),
        ("sender1", "How are you?"),
    ]

    for sender, content in messages:
        message = ChatMessage(
            sender=sender,
            recipient="testuser",
            content=content,
            timestamp=time.time(),
        )
        client.signals.message_received.emit(message)
        qtbot.wait(100)

    # Verify all messages appear in order
    chat_text = client.chat_history.toPlainText()
    last_pos = -1
    for sender, content in messages:
        pos = chat_text.find(content)
        assert pos > last_pos
        last_pos = pos


def test_user_status_updates(client, qtbot):
    """Test multiple user status updates"""
    client.current_user = "testuser"
    client.stacked_widget.setCurrentWidget(client.chat_page)

    # Test multiple users coming online
    users = ["user1", "user2", "user3"]
    for user in users:
        client.signals.user_status_changed.emit(user, True)
        qtbot.wait(100)

    # Verify all users are in list
    online_users = [
        client.online_users_list.item(i).text()
        for i in range(client.online_users_list.count())
    ]
    assert set(users) == set(online_users)

    # Test users going offline in different order
    for user in reversed(users):
        client.signals.user_status_changed.emit(user, False)
        qtbot.wait(100)

    # Verify all users are removed
    assert client.online_users_list.count() == 0
