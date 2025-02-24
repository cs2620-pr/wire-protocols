"""A PyQt5-based GUI client for the chat application.

This module provides a graphical user interface for the chat client, featuring:
- User authentication (login/registration)
- Real-time messaging
- Direct messaging support
- Message history and unread message tracking
- User presence indicators
- Message deletion and account management
- Theme support (light/dark mode)
"""

import sys
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QInputDialog,
    QMessageBox,
    QDialog,
    QSpinBox,
    QComboBox,
    QListWidget,
    QFrame,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import socket
import threading
from typing import Optional, List, Set
from queue import Queue
from schemas import ChatMessage, MessageType, ServerResponse, Status, SystemMessage
from protocol import Protocol, ProtocolFactory
from datetime import datetime
import argparse


class LoginDialog(QDialog):
    """Dialog for user login and registration.

    This dialog handles both login and registration operations, collecting
    username and password from the user and providing appropriate feedback.

    Attributes:
        username_input (QLineEdit): Input field for username
        password_input (QLineEdit): Input field for password
        login_button (QPushButton): Button to trigger login
        register_button (QPushButton): Button to trigger registration
        selected_action (str): Stores whether user chose login or register
    """

    def __init__(self, parent=None):
        """Initialize the login dialog with input fields and buttons.

        Args:
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self.setWindowTitle("Chat Login")
        self.setModal(True)

        layout = QVBoxLayout()

        # Username input
        self.username_input = QLineEdit()
        layout.addWidget(QLabel("Username:"))
        layout.addWidget(self.username_input)

        # Password input
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("Password:"))
        layout.addWidget(self.password_input)

        # Buttons
        button_layout = QHBoxLayout()
        self.login_button = QPushButton("Login")
        self.register_button = QPushButton("Register")
        button_layout.addWidget(self.login_button)
        button_layout.addWidget(self.register_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Connect button signals
        self.login_button.clicked.connect(self.handle_login)
        self.register_button.clicked.connect(self.handle_register)

        # Store the selected action
        self.selected_action = None

    def handle_login(self):
        """Handle login button click."""
        self.selected_action = "login"
        self.accept()

    def handle_register(self):
        """Handle register button click."""
        self.selected_action = "register"
        self.accept()

    def get_credentials(self):
        """Get the entered credentials and selected action.

        Returns:
            tuple: (username, password, action)
        """
        return (
            self.username_input.text(),
            self.password_input.text(),
            self.selected_action,
        )

    def reject(self):
        """Handle dialog rejection (X button click) by exiting the application."""
        QApplication.instance().quit()


class ReceiveThread(QThread):
    """Background thread for receiving messages from the server.

    This thread continuously listens for incoming messages and emits signals
    when messages are received or when the connection is lost.

    Attributes:
        message_received (pyqtSignal): Signal emitted when a message is received
        connection_lost (pyqtSignal): Signal emitted when connection is lost
        client (ChatClient): Reference to the chat client instance
    """

    message_received = pyqtSignal(str, object)  # Signal includes the message object
    connection_lost = pyqtSignal()

    def __init__(self, client):
        """Initialize the receive thread.

        Args:
            client: ChatClient instance to receive messages from
        """
        super().__init__()
        self.client = client
        self.running = True

    def run(self):
        """Main loop for receiving messages via gRPC streaming."""
        try:
            for msg in self.client.fetch_messages():
                if not self.running:
                    break
                formatted_message = f"{msg.sender}: {msg.content}"
                self.message_received.emit(formatted_message, msg)
        except grpc.RpcError as e:
            print(f"Error in message receiving: {e}")
            self.connection_lost.emit()

    def stop(self):
        """Stop the thread safely."""
        self.running = False


class ChatWindow(QMainWindow):
    """Main chat window interface.

    This class implements the main chat interface, handling:
    - Message display and sending
    - User list management
    - Chat history
    - Message deletion
    - Account management
    - Theme management

    Attributes:
        client (ChatClient): The chat client instance
        receive_thread (ReceiveThread): Thread for receiving messages
        current_chat_user (str): Currently selected chat user
        unread_counts (dict): Tracks unread message counts per user
        active_users (set): Set of currently active users
    """

    def __init__(
        self, host: str = "localhost", port: int = 8000, protocol: str = "json"
    ):
        """Initialize the chat window.

        Args:
            host: Server hostname
            port: Server port number
            protocol: Protocol type to use ("json" or "custom")
        """
        super().__init__()
        self.client: ChatClient | None = None
        self.receive_thread: ReceiveThread | None = None
        self.system_message_display: QTextEdit | None = None
        self.server_host = host
        self.server_port = port
        self.protocol_type = protocol
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface components and layout."""
        self.setWindowTitle("Chat Client")
        self.setGeometry(100, 100, 1000, 600)  # Made window wider for user list

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Chat area layout
        chat_layout = QVBoxLayout()

        # Chat display area
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        chat_layout.addWidget(self.chat_display)

        # Message input area
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.returnPressed.connect(self.send_message)
        self.message_input.setPlaceholderText("Select a user to start messaging")
        self.message_input.setEnabled(False)  # Initially disabled
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        self.send_button.setEnabled(False)  # Initially disabled
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        chat_layout.addLayout(input_layout)

        # Buttons layout
        button_layout = QHBoxLayout()

        # Other control buttons
        self.delete_button = QPushButton("Delete Messages")
        self.delete_button.clicked.connect(self.delete_messages)
        self.logout_button = QPushButton("Logout")
        self.logout_button.clicked.connect(self.logout)
        self.delete_account_button = QPushButton("Delete Account")
        self.delete_account_button.clicked.connect(self.delete_account)
        self.delete_account_button.setStyleSheet("QPushButton { color: red; }")

        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.logout_button)
        button_layout.addWidget(self.delete_account_button)

        chat_layout.addLayout(button_layout)
        main_layout.addLayout(chat_layout, stretch=7)  # Chat area takes 70% of width

        # User list area (right side)
        user_list_layout = QVBoxLayout()

        # Current user status
        self.current_user_label = QLabel()
        self.current_user_label.setStyleSheet("QLabel { font-weight: bold; }")
        user_list_layout.addWidget(self.current_user_label)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        user_list_layout.addWidget(separator)

        # Set consistent width for the right panel
        right_panel_width = 200

        user_list_layout.addWidget(QLabel("Other Users:"))
        self.user_list = QListWidget()
        self.user_list.setMaximumWidth(right_panel_width)  # Set consistent width
        self.user_list.itemClicked.connect(self.on_user_clicked)
        user_list_layout.addWidget(self.user_list)

        # Initialize system message display first
        self.system_message_display = QTextEdit()
        self.system_message_display.setReadOnly(True)
        self.system_message_display.setMaximumHeight(150)  # Limit height
        self.system_message_display.setMaximumWidth(
            right_panel_width
        )  # Set consistent width

        # Add system message area
        user_list_layout.addWidget(QLabel("System Messages:"))
        user_list_layout.addWidget(self.system_message_display)

        main_layout.addLayout(
            user_list_layout, stretch=3
        )  # User list takes 30% of width

        # Store current chat user
        self.current_chat_user = None
        # Store unread message counts per user
        self.unread_counts = {}
        # Store active users
        self.active_users = set()

        # Initially disable UI elements until connected
        self.set_ui_enabled(False)

        # Set theme after all widgets are initialized
        self.update_theme()

        # Show login dialog on startup
        self.show_login_dialog()

    def set_ui_enabled(self, enabled: bool):
        """Enable or disable UI elements based on connection status.

        Args:
            enabled: Whether to enable or disable the UI elements
        """
        self.message_input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.logout_button.setEnabled(enabled)
        self.delete_account_button.setEnabled(enabled)
        self.user_list.setEnabled(enabled)

    def show_login_dialog(self):
        """Show the login dialog and handle the result."""
        dialog = LoginDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            username, password, action = dialog.get_credentials()
            if username and password:
                if self.connect_to_server(username, password, action):
                    self.show()  # Only show main window on successful connection
                else:
                    self.show_login_dialog()  # Try login again on failure
            else:
                QMessageBox.warning(self, "Error", SystemMessage.EMPTY_CREDENTIALS)
                self.show_login_dialog()
        else:
            self.close()  # This will trigger closeEvent which exits the app

    def connect_to_server(self, username: str, password: str, action: str) -> bool:
        """Connect to the chat server and authenticate."""
        self.client = ChatClient(username)
        
        if action == "register":
            message = self.client.register(password)
        else:
            message, unread_count = self.client.login(password)

        if "success" in message.lower():
            self.receive_thread = ReceiveThread(self.client)
            self.receive_thread.message_received.connect(self.handle_message)
            self.receive_thread.connection_lost.connect(self.handle_disconnection)
            self.receive_thread.start()
            
            self.set_ui_enabled(True)
            self.setWindowTitle(f"Chat Client - {username}")
            return True
        else:
            return False


    def update_theme(self):
        """Update the chat display theme based on system colors."""
        palette = self.palette()
        is_dark = palette.color(palette.Window).lightness() < 128

        # Set background color based on system theme
        bg_color = "#2D2D2D" if is_dark else "#FFFFFF"
        text_color = "#FFFFFF" if is_dark else "#000000"
        system_bg_color = "#3D3D3D" if is_dark else "#F5F5F5"
        system_border_color = "#4D4D4D" if is_dark else "#CCCCCC"

        # Apply theme to chat display
        self.chat_display.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {bg_color};
                color: {text_color};
                border: none;
            }}
        """
        )

        # Apply theme to system message display
        self.system_message_display.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {system_bg_color};
                color: {text_color};
                border: 1px solid {system_border_color};
                border-radius: 4px;
                font-size: 12px;
            }}
        """
        )

    def display_message(self, sender: str, content: str, msg_id: Optional[str] = None):
        """Display a message in the chat window.

        Args:
            sender: Username of message sender
            content: Message content
            msg_id: Optional message ID for reference
        """
        if not self.client:
            return

        is_from_me = sender == self.client.username
        palette = self.palette()
        is_dark = palette.color(palette.Window).lightness() < 128

        # Set colors based on dark/light mode
        my_color = "#0B93F6"  # Blue for my messages
        other_color = "#E5E5EA" if not is_dark else "#808080"  # Grey for other messages
        id_color = "#888888"  # Gray for message ID

        # Create the name display
        name_text = "me" if is_from_me else sender
        name_color = my_color if is_from_me else other_color

        # Create HTML for the message
        html = f"""
            <div style="margin: 4px 20px; font-size: 14px; display: flex; align-items: center;">
                <span style="color: {id_color}; font-size: 10px; min-width: 40px; margin-right: 8px;">{msg_id if msg_id else ''}</span>
                <div>
                    <span style="color: {name_color}; font-weight: bold;">{name_text}:</span>
                    <span style="margin-left: 8px;">{content}</span>
                </div>
            </div>
        """

        # Append the HTML to the chat display
        self.chat_display.append(html)

    def send_message(self):
        """Send a message to the current chat user."""
        if not self.client or not self.current_chat_user:
            return

        message = self.message_input.text().strip()
        if not message:
            return

        self.client.send_message(self.current_chat_user, message)
        self.message_input.clear()


    def fetch_messages(self):
        """Fetch message history from the server."""
        if not self.client or not self.client.connected:
            return

        count = self.fetch_count.value()
        self.client.fetch_messages(count)

    def mark_messages_read(self):
        """Mark messages as read for the current chat."""
        if not self.client or not self.client.connected:
            return

        self.client.mark_messages_read()

    def delete_messages(self):
        """Delete selected messages."""
        if not self.client or not self.current_chat_user:
            QMessageBox.warning(self, "Error", "Please select a chat first")
            return

        message_ids_text, ok = QInputDialog.getText(self, "Delete Messages", "Enter message IDs to delete:")
        if ok and message_ids_text:
            try:
                message_ids = [int(id) for id in message_ids_text.split()]
                self.client.delete_messages(message_ids)
                QMessageBox.information(self, "Success", "Messages deleted")
            except ValueError:
                QMessageBox.warning(self, "Error", "Invalid message ID format")

    def logout(self):
        """Handle user logout and cleanup."""
        if not self.client or not self.client.connected:
            return

        # Set a flag to indicate this is a voluntary logout
        self.client.is_voluntary_disconnect = True

        # Disconnect from server
        self.client.disconnect()

        # Wait for receive thread to finish if it exists
        if self.receive_thread and self.receive_thread.isRunning():
            self.receive_thread.quit()
            self.receive_thread.wait()

        # Clear all state
        self.chat_display.clear()
        self.system_message_display.clear()  # Clear system messages
        self.current_chat_user = None
        self.unread_counts.clear()
        self.active_users.clear()
        self.message_input.setPlaceholderText("Select a user to start messaging")
        self.message_input.clear()

        # Reset window title
        self.setWindowTitle("Chat Client")

        # Disable UI elements
        self.set_ui_enabled(False)
        self.message_input.setEnabled(False)
        self.send_button.setEnabled(False)

        # Hide the main window
        self.hide()

        # Show login dialog
        self.show_login_dialog()

        # Show the main window again after login
        self.show()

    def handle_disconnection(self):
        """Handle server disconnection events."""
        # If this is a voluntary disconnect (logout), don't do anything
        if (
            hasattr(self.client, "is_voluntary_disconnect")
            and self.client.is_voluntary_disconnect
        ):
            return

        self.client.connected = False
        self.set_ui_enabled(False)
        QMessageBox.critical(
            self,
            "Connection Lost",
            SystemMessage.CONNECTION_LOST,
        )
        # Close all windows and quit gracefully
        QApplication.instance().quit()

    def closeEvent(self, event):
        """Handle window close event."""
        if self.client and self.client.connected:
            self.client.disconnect()
        event.accept()
        QApplication.instance().quit()

    def update_user_list(self):
        """Update the user list display."""
        all_users = self.client.list_accounts()
        self.user_list.clear()
        for user in all_users:
            self.user_list.addItem(user)


    def handle_server_message(self, message: ChatMessage):
        """Handle incoming server messages and update UI accordingly.

        Args:
            message: The received chat message
        """
        if (
            message.message_type == MessageType.LOGIN
            and message.recipients
            and message.active_users
        ):
            # Update user list when receiving login success message
            self.update_user_list(message.recipients, message.active_users)
        elif message.message_type == MessageType.JOIN:
            # For join messages, add the new user to the list if not present
            current_all_users = []
            for i in range(self.user_list.count()):
                item = self.user_list.item(i)
                username = (
                    item.text().split(" ", 1)[1].split(" (")[0]
                )  # Remove status emoji and unread count
                current_all_users.append(username)

            if message.username not in current_all_users:
                current_all_users.append(message.username)

            # Get current active users from the display
            current_active_users = []
            for i in range(self.user_list.count()):
                item = self.user_list.item(i)
                if item.text().startswith("🟢"):
                    username = (
                        item.text().split(" ", 1)[1].split(" (")[0]
                    )  # Remove status emoji and unread count
                    current_active_users.append(username)

            # Add the new user to active users
            if message.username not in current_active_users:
                current_active_users.append(message.username)

            # Use server's active_users list if provided, otherwise use our current list
            active_users = (
                message.active_users if message.active_users else current_active_users
            )
            self.update_user_list(current_all_users, active_users)

        elif message.message_type == MessageType.LOGOUT:
            # For logout messages, keep the user in the list but mark as inactive
            current_all_users = []
            for i in range(self.user_list.count()):
                item = self.user_list.item(i)
                username = (
                    item.text().split(" ", 1)[1].split(" (")[0]
                )  # Remove status emoji and unread count
                current_all_users.append(username)

            # Get current active users and remove the logging out user
            current_active_users = []
            for i in range(self.user_list.count()):
                item = self.user_list.item(i)
                if item.text().startswith("🟢"):
                    username = (
                        item.text().split(" ", 1)[1].split(" (")[0]
                    )  # Remove status emoji and unread count
                    if (
                        username != message.username
                    ):  # Don't include the logging out user
                        current_active_users.append(username)

            # Use server's active_users list if provided, otherwise use our current list
            active_users = (
                message.active_users if message.active_users else current_active_users
            )
            self.update_user_list(current_all_users, active_users)

    def on_user_clicked(self, item):
        """Handle user selection from the user list.

        Args:
            item: The selected user list item
        """
        # Extract username from the list item text (remove status emoji and unread count)
        username = item.text().split(" ", 1)[1].split(" (")[0]

        if username == self.current_chat_user:
            return  # Already chatting with this user

        self.current_chat_user = username
        self.message_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.message_input.setPlaceholderText(f"Message {username}")

        # Clear chat display and show relevant messages
        self.chat_display.clear()
        self.load_chat_history(username)

        # Update unread count
        if username in self.unread_counts:
            self.unread_counts[username] = 0
            self.update_user_list_item(username)

    def load_chat_history(self, username: str):
        """Load chat history for a specific user.

        Args:
            username: The user to load chat history for
        """
        if not self.client:
            return

        # Request all messages between the current user and the selected user
        history_message = ChatMessage(
            username=self.client.username,
            content="",
            message_type=MessageType.FETCH,
            recipients=[
                username,
                self.client.username,
            ],  # Get messages between both users
            fetch_count=50,  # Get last 50 messages
        )
        self.client.send_message(history_message)

        # Mark all messages from this user as read
        mark_read_message = ChatMessage(
            username=self.client.username,
            content="",
            message_type=MessageType.MARK_READ,
            recipients=[username],  # The user whose messages we're marking as read
        )
        self.client.send_message(mark_read_message)

    def update_user_list_item(self, username: str):
        """Update the display of a user in the list.

        Args:
            username: The username to update in the list
        """
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            if username in item.text():
                status = "🟢" if username in self.active_users else "⚪"
                unread = self.unread_counts.get(username, 0)
                text = f"{status} {username}"
                if unread > 0:
                    text = f"{text} ({unread})"
                item.setText(text)
                break

    def delete_account(self):
        """Delete the user's account."""
        password, ok = QInputDialog.getText(self, "Delete Account", "Enter your password:", QLineEdit.Password)
        if ok:
            response = self.client.delete_account(password)
            QMessageBox.information(self, "Account Deletion", response)
            self.logout()

    def handle_message(self, message: str, message_obj: Optional[ChatMessage] = None):
        """Handle incoming messages and update UI accordingly.

        Args:
            message: The message text
            message_obj: Optional ChatMessage object containing additional data
        """
        if not self.client:
            return

        if message_obj:
            self.handle_server_message(message_obj)

            # Handle system messages
            is_system_message = (
                message_obj.message_type
                in [MessageType.JOIN, MessageType.LOGOUT, MessageType.DELETE_ACCOUNT]
                or message_obj.username == "System"
            )

            if is_system_message:
                # Skip blank system messages
                if not message.strip() or message.strip() == "System:":
                    return

                # Add timestamp to system message
                timestamp = message_obj.timestamp.strftime("%H:%M:%S")
                html = f"""
                    <div style="margin: 4px 0;">
                        <span style="color: #888888;">[{timestamp}]</span> {message}
                    </div>
                """
                if self.system_message_display:
                    self.system_message_display.append(html)
                return

            # Handle account deletion notifications
            if message_obj.message_type == MessageType.DELETE_ACCOUNT:
                # Just display the notification, user list will be updated separately
                html = f"""
                    <div style="text-align: center; margin: 10px 0;">
                        <span style="color: #888888; font-style: italic;">
                            {message}
                        </span>
                    </div>
                """
                self.chat_display.append(html)
                return

            # Handle message deletion notifications
            if message_obj.message_type == MessageType.DELETE_NOTIFICATION:
                # Update unread count if needed
                if message_obj.unread_count and message_obj.unread_count > 0:
                    # If we're the recipient of the deleted messages, update our unread count
                    # for the conversation with the user who deleted them
                    if (
                        self.client.username != message_obj.username
                    ):  # We're not the deleter
                        current_unread = self.unread_counts.get(message_obj.username, 0)
                        self.unread_counts[message_obj.username] = max(
                            0, current_unread - message_obj.unread_count
                        )
                        self.update_user_list_item(message_obj.username)

                # Refresh chat if we're viewing a conversation with the user who deleted messages
                # or if we're viewing our own messages that were deleted
                if self.current_chat_user and (
                    message_obj.username == self.current_chat_user
                    or self.current_chat_user == self.client.username
                ):
                    self.chat_display.clear()
                    self.load_chat_history(self.current_chat_user)
                return

            # Handle unread messages and display
            if message_obj.message_type in [MessageType.CHAT, MessageType.DM]:
                sender = message_obj.username
                is_from_current_chat = sender == self.current_chat_user
                is_to_current_chat = (
                    message_obj.recipients
                    and self.current_chat_user in message_obj.recipients
                )
                is_from_me = sender == self.client.username
                is_to_me = (
                    message_obj.recipients
                    and self.client.username in message_obj.recipients
                )

                # Update unread count if message is not from current chat or me
                if not is_from_current_chat and not is_from_me and is_to_me:
                    self.unread_counts[sender] = self.unread_counts.get(sender, 0) + 1
                    self.update_user_list_item(sender)

                # Display message if it's relevant to current chat
                should_display = (
                    (is_from_current_chat and is_to_me)
                    or (is_from_me and is_to_current_chat)
                    or (is_from_current_chat and not message_obj.recipients)
                    or (
                        is_from_me
                        and not message_obj.recipients
                        and self.current_chat_user
                    )
                    or message_obj.message_type == MessageType.FETCH
                )

                if should_display:
                    msg_id = (
                        f"[{message_obj.message_id}]"
                        if message_obj.message_id is not None
                        else None
                    )
                    self.display_message(sender, message_obj.content, msg_id)

                # If this is a fetched message and it's unread, update the unread count
                if (
                    message_obj.message_type == MessageType.FETCH
                    and is_to_me
                    and not is_from_me
                    and not is_from_current_chat  # Don't count messages from current chat
                ):
                    self.unread_counts[sender] = self.unread_counts.get(sender, 0) + 1
                    self.update_user_list_item(sender)

                # If we received an unread count update from the server, use it
                if message_obj.unread_count is not None and is_to_me:
                    if sender in self.unread_counts:
                        self.unread_counts[sender] = message_obj.unread_count
                        self.update_user_list_item(sender)

            elif message_obj.message_type not in [MessageType.JOIN, MessageType.LOGOUT]:
                # Display system messages except JOIN/LOGOUT messages
                html = f"""
                    <div style="text-align: center; margin: 10px 0;">
                        <span style="color: #888888; font-style: italic;">
                            {message}
                        </span>
                    </div>
                """
                self.chat_display.append(html)

        elif message != "Connection closed by server":  # Skip connection closed message
            # Display other system messages
            html = f"""
                <div style="text-align: center; margin: 10px 0;">
                    <span style="color: #888888; font-style: italic;">
                        {message}
                    </span>
                </div>
            """
            self.chat_display.append(html)


# class ChatClient:
#     """Client for connecting to and communicating with the chat server.

#     This class handles:
#     - Server connection and authentication
#     - Message sending and receiving
#     - Protocol handling
#     - Connection state management

#     Attributes:
#         username (str): Client's username
#         host (str): Server hostname
#         port (int): Server port number
#         connected (bool): Connection state
#         protocol (Protocol): Protocol implementation
#         unread_messages (Set[int]): Set of unread message IDs
#         is_voluntary_disconnect (bool): Whether disconnect was user-initiated
#     """

#     def __init__(
#         self,
#         username: str,
#         protocol: Optional[Protocol] = None,
#         host: str = "localhost",
#         port: int = 8000,
#     ):
#         """Initialize the chat client.

#         Args:
#             username: Client's username
#             protocol: Protocol implementation to use
#             host: Server hostname
#             port: Server port number
#         """
#         self.username = username
#         self.host = host
#         self.port = port
#         self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         self.connected = False
#         self._lock = threading.Lock()
#         self.protocol = protocol or ProtocolFactory.create("json")
#         self.receive_buffer = b""
#         self.unread_messages: Set[int] = set()
#         self.is_voluntary_disconnect = False

#     def connect(self) -> bool:
#         """Connect to the chat server.

#         Returns:
#             bool: True if connection successful
#         """
#         try:
#             self.client_socket.connect((self.host, self.port))
#             self.connected = True
#             return True
#         except Exception as e:
#             print(f"Connection failed: {e}")
#             return False

#     def authenticate(self, password: str, action: str) -> bool:
#         """Authenticate with the server.

#         Args:
#             password: User's password
#             action: Either "login" or "register"

#         Returns:
#             bool: True if authentication successful
#         """
#         message = ChatMessage(
#             username=self.username,
#             content="",
#             message_type=(
#                 MessageType.LOGIN if action == "login" else MessageType.REGISTER
#             ),
#             password=password,
#         )

#         if not self.send_message(message):
#             return False

#         try:
#             data = self.client_socket.recv(1024)
#             if not data:
#                 return False

#             self.receive_buffer += data
#             message_data, self.receive_buffer = self.protocol.extract_message(
#                 self.receive_buffer
#             )
#             if message_data is None:
#                 return False

#             response = self.protocol.deserialize_response(message_data)

#             if response.status == Status.SUCCESS:
#                 if action == "register":
#                     # Show registration success message
#                     QMessageBox.information(
#                         None, "Success", "Registration successful! Logging in..."
#                     )
#                     # Try logging in with the same credentials
#                     return self.authenticate(password, "login")
#                 return True
#             else:
#                 # Show the specific error message from the server
#                 QMessageBox.critical(None, "Error", response.message)
#                 return False

#         except Exception as e:
#             print(f"Authentication error: {e}")
#             return False

#         return False

#     def send_message(self, message: ChatMessage) -> bool:
#         """Send a message to the server.

#         Args:
#             message: The message to send

#         Returns:
#             bool: True if message sent successfully
#         """
#         if not self.connected:
#             return False

#         try:
#             with self._lock:
#                 data = self.protocol.serialize_message(message)
#                 framed_data = self.protocol.frame_message(data)
#                 self.client_socket.send(framed_data)
#                 return True
#         except Exception as e:
#             print(f"Error sending message: {e}")
#             self.connected = False
#             return False

#     def send_chat_message(self, content: str) -> bool:
#         """Send a chat message or direct message.

#         Args:
#             content: Message content (may include recipient prefix)

#         Returns:
#             bool: True if message sent successfully
#         """
#         if ";" in content:
#             recipient, message_content = content.split(";", 1)
#             recipient = recipient.strip()
#             message_content = message_content.strip()

#             if not recipient or not message_content:
#                 return False

#             message = ChatMessage(
#                 username=self.username,
#                 content=message_content,
#                 message_type=MessageType.DM,
#                 recipients=[recipient],
#             )
#         else:
#             message = ChatMessage(
#                 username=self.username, content=content, message_type=MessageType.CHAT
#             )

#         return self.send_message(message)

#     def fetch_messages(self, count: int = 10):
#         """Request message history from the server.

#         Args:
#             count: Number of messages to fetch
#         """
#         fetch_message = ChatMessage(
#             username=self.username,
#             content="",
#             message_type=MessageType.FETCH,
#             fetch_count=count,
#         )
#         self.send_message(fetch_message)

#     def mark_messages_read(self):
#         """Mark unread messages as read."""
#         if not self.unread_messages:
#             return

#         mark_read_message = ChatMessage(
#             username=self.username,
#             content="",
#             message_type=MessageType.MARK_READ,
#             message_ids=list(self.unread_messages),
#         )
#         if self.send_message(mark_read_message):
#             self.unread_messages.clear()

#     def delete_messages(self, message_ids: List[int], recipient: str):
#         """Delete specific messages.

#         Args:
#             message_ids: List of message IDs to delete
#             recipient: Username of the message recipient
#         """
#         delete_message = ChatMessage(
#             username=self.username,
#             content="",
#             message_type=MessageType.DELETE,
#             message_ids=message_ids,
#             recipients=[recipient],
#         )
#         self.send_message(delete_message)

#     def disconnect(self):
#         """Disconnect from the server and cleanup."""
#         if not self.connected:
#             return

#         self.connected = False
#         try:
#             logout_message = ChatMessage(
#                 username=self.username,
#                 content=f"{self.username} has left the chat",
#                 message_type=MessageType.LOGOUT,
#             )
#             data = self.protocol.serialize_message(logout_message)
#             framed_data = self.protocol.frame_message(data)
#             self.client_socket.send(framed_data)
#         except Exception:
#             pass
#         finally:
#             try:
#                 self.client_socket.shutdown(socket.SHUT_RDWR)
#             except OSError:
#                 pass
#             self.client_socket.close()

import grpc
import protocol_pb2
import protocol_pb2_grpc
from PyQt5.QtCore import QThread, pyqtSignal

class ChatClient:
    def __init__(self, username, server_address="localhost:50051"):
        self.username = username
        self.channel = grpc.insecure_channel(server_address)
        self.stub = protocol_pb2_grpc.ChatServiceStub(self.channel)

    def register(self, password):
        response = self.stub.Register(protocol_pb2.UserCredentials(username=self.username, password=password))
        return response.message

    def login(self, password):
        response = self.stub.Login(protocol_pb2.UserCredentials(username=self.username, password=password))
        return response.message, response.unread_messages

    def list_accounts(self, pattern=""):
        response = self.stub.ListAccounts(protocol_pb2.ListRequest(pattern=pattern))
        return response.usernames

    def send_message(self, recipient, content):
        self.stub.SendMessage(protocol_pb2.ChatRequest(
            sender=self.username,
            recipient=recipient,
            content=content,
            timestamp=0  # Server will handle the actual timestamp
        ))

    def fetch_messages(self, limit=10):
        return self.stub.FetchMessages(protocol_pb2.FetchRequest(username=self.username, limit=limit))

    def delete_messages(self, message_ids):
        self.stub.DeleteMessages(protocol_pb2.DeleteRequest(username=self.username, message_ids=message_ids))

    def delete_account(self, password):
        response = self.stub.DeleteAccount(protocol_pb2.UserCredentials(username=self.username, password=password))
        return response.message


def main():
    """Main entry point for the GUI client application."""
    parser = argparse.ArgumentParser(description="Start the chat client")
    parser.add_argument("--host", default="localhost", help="Server host address")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument(
        "--protocol",
        default="json",
        choices=["json", "custom"],
        help="Protocol type to use",
    )
    parser.add_argument(
        "--enable-logging",
        action="store_true",
        help="Enable protocol metrics logging",
    )

    args = parser.parse_args()

    # Configure protocol logging based on argument
    from protocol import configure_protocol_logging

    configure_protocol_logging(enabled=args.enable_logging)

    app = QApplication(sys.argv[1:])  # Skip the argparse arguments
    window = ChatWindow(host=args.host, port=args.port, protocol=args.protocol)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
