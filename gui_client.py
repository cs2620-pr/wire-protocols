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
    def __init__(self, parent=None):
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
        self.selected_action = "login"
        self.accept()

    def handle_register(self):
        self.selected_action = "register"
        self.accept()

    def get_credentials(self):
        return (
            self.username_input.text(),
            self.password_input.text(),
            self.selected_action,
        )

    def reject(self):
        QApplication.instance().quit()  # Exit the program when dialog is rejected (X button clicked)


class ReceiveThread(QThread):
    message_received = pyqtSignal(str, object)  # Signal now includes the message object
    connection_lost = pyqtSignal()

    def __init__(self, client):
        super().__init__()
        self.client = client

    def run(self):
        while self.client.connected:
            try:
                data = self.client.client_socket.recv(1024)
                if not data:
                    self.message_received.emit("Connection closed by server", None)
                    self.connection_lost.emit()
                    break

                self.client.receive_buffer += data
                while True:
                    message_data, self.client.receive_buffer = (
                        self.client.protocol.extract_message(self.client.receive_buffer)
                    )
                    if message_data is None:
                        break

                    response = self.client.protocol.deserialize_response(message_data)
                    if response.status == Status.ERROR:
                        self.message_received.emit(f"Error: {response.message}", None)
                        if "not logged in" in response.message.lower():
                            self.connection_lost.emit()
                            break
                        continue

                    if response.data is None:
                        self.message_received.emit(response.message, None)
                        continue

                    if isinstance(response.data, list):
                        for msg in response.data:
                            self.message_received.emit(
                                f"{msg.username}: {str(msg)}", msg
                            )
                    else:
                        self.message_received.emit(
                            f"{response.data.username}: {str(response.data)}",
                            response.data,
                        )

            except Exception as e:
                if self.client.connected:
                    self.message_received.emit(f"Error receiving message: {e}", None)
                break

        self.connection_lost.emit()


class ChatWindow(QMainWindow):
    def __init__(
        self, host: str = "localhost", port: int = 8000, protocol: str = "json"
    ):
        super().__init__()
        self.client: ChatClient | None = None
        self.receive_thread: ReceiveThread | None = None
        self.system_message_display: QTextEdit | None = None  # Initialize the attribute
        self.server_host = host
        self.server_port = port
        self.protocol_type = protocol
        self.init_ui()

    def init_ui(self):
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
        """Enable or disable UI elements based on connection status"""
        self.message_input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.logout_button.setEnabled(enabled)
        self.delete_account_button.setEnabled(enabled)
        self.user_list.setEnabled(enabled)

    def show_login_dialog(self):
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
        self.client = ChatClient(
            username,
            protocol=ProtocolFactory.create(self.protocol_type),
            host=self.server_host,
            port=self.server_port,
        )

        if not self.client.connect():
            QMessageBox.critical(
                self,
                "Connection Error",
                SystemMessage.CONNECTION_ERROR,
            )
            self.client.disconnect()  # Ensure socket is closed
            return False

        if not self.client.authenticate(password, action):
            # Error message is already shown in authenticate method
            self.client.disconnect()  # Ensure socket is closed
            return False

        # Start receive thread
        self.receive_thread = ReceiveThread(self.client)
        self.receive_thread.message_received.connect(self.handle_message)
        self.receive_thread.connection_lost.connect(self.handle_disconnection)
        self.receive_thread.start()

        # Enable UI elements
        self.set_ui_enabled(True)

        # Clear previous system messages
        if self.system_message_display:
            self.system_message_display.clear()

        # Display system message
        timestamp = datetime.now().strftime("%H:%M:%S")
        html = f"""
            <div style="margin: 4px 0;">
                <span style="color: #888888;">[{timestamp}]</span> Connected to server!
            </div>
        """
        if self.system_message_display:
            self.system_message_display.append(html)

        # Update window title to include username
        self.setWindowTitle(f"Chat Client - {username}")

        # Fetch unread messages to update unread counts
        fetch_message = ChatMessage(
            username=self.client.username,
            content="",
            message_type=MessageType.FETCH,
            fetch_count=50,  # Fetch last 50 messages to get unread counts
        )
        self.client.send_message(fetch_message)

        return True

    def update_theme(self):
        """Update the chat display theme based on system colors"""
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
        """Display a message with colored sender name followed by content"""
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
        if not self.client or not self.client.connected or not self.current_chat_user:
            return

        message = self.message_input.text().strip()
        if not message:
            return

        # Always send as DM when in a chat
        dm_content = f"{self.current_chat_user};{message}"
        if self.client.send_chat_message(dm_content):
            # Message will be displayed when we receive it back from the server with the message ID
            pass
        else:
            self.handle_disconnection()

        self.message_input.clear()

    def fetch_messages(self):
        if not self.client or not self.client.connected:
            return

        count = self.fetch_count.value()
        self.client.fetch_messages(count)

    def mark_messages_read(self):
        if not self.client or not self.client.connected:
            return

        self.client.mark_messages_read()

    def delete_messages(self):
        if not self.client or not self.client.connected or not self.current_chat_user:
            QMessageBox.warning(self, "Error", "Please select a chat first")
            return

        message_ids_text, ok = QInputDialog.getText(
            self, "Delete Messages", "Enter message IDs to delete (space-separated):"
        )

        if ok and message_ids_text:
            try:
                message_ids = [int(id) for id in message_ids_text.split()]
                self.client.delete_messages(message_ids, self.current_chat_user)
                # Immediately refresh our own chat
                self.chat_display.clear()
                self.load_chat_history(self.current_chat_user)
            except ValueError:
                QMessageBox.warning(self, "Error", SystemMessage.INVALID_MESSAGE_IDS)

    def logout(self):
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
        if self.client and self.client.connected:
            self.client.disconnect()
        event.accept()
        QApplication.instance().quit()

    def update_user_list(self, all_users: List[str], active_users: List[str]):
        """Update the user list display"""
        if not self.client:
            return

        self.user_list.clear()
        self.active_users = set(active_users)  # Update active users set

        # Update current user status
        self.current_user_label.setText(f"🟢 You ({self.client.username})")

        # Filter out current user from the lists
        other_users = [
            user for user in sorted(set(all_users)) if user != self.client.username
        ]

        # Add other users to the list
        for user in other_users:
            status = "🟢" if user in active_users else "⚪"
            text = f"{status} {user}"
            if user in self.unread_counts and self.unread_counts[user] > 0:
                text = f"{text} ({self.unread_counts[user]})"
            self.user_list.addItem(text)

    def handle_server_message(self, message: ChatMessage):
        """Handle server messages including user list updates"""
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
        """Handle user selection from the list"""
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
        """Load chat history for a specific user"""
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
        """Update the display of a user in the list"""
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
        """Handle account deletion with confirmation"""
        reply = QMessageBox.question(
            self,
            "Delete Account",
            "Are you sure you want to delete your account?\nThis action cannot be undone!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            # Send delete account message
            delete_message = ChatMessage(
                username=self.client.username,
                content="",
                message_type=MessageType.DELETE_ACCOUNT,
            )
            if self.client.send_message(delete_message):
                # Set voluntary disconnect flag to prevent connection lost message
                self.client.is_voluntary_disconnect = True
                # Close the window and show login dialog
                self.close()
                QMessageBox.information(
                    self,
                    "Account Deleted",
                    "Your account has been deleted successfully.",
                )
                self.show_login_dialog()

    def handle_message(self, message: str, message_obj: Optional[ChatMessage] = None):
        """Handle incoming messages and update UI accordingly"""
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


class ChatClient:
    def __init__(
        self,
        username: str,
        protocol: Optional[Protocol] = None,
        host: str = "localhost",
        port: int = 8000,
    ):
        self.username = username
        self.host = host
        self.port = port
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected = False
        self._lock = threading.Lock()
        self.protocol = protocol or ProtocolFactory.create("json")
        self.receive_buffer = b""
        self.unread_messages: Set[int] = set()
        self.is_voluntary_disconnect = False  # Add flag for voluntary disconnects

    def connect(self) -> bool:
        try:
            self.client_socket.connect((self.host, self.port))
            self.connected = True
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def authenticate(self, password: str, action: str) -> bool:
        message = ChatMessage(
            username=self.username,
            content="",
            message_type=(
                MessageType.LOGIN if action == "login" else MessageType.REGISTER
            ),
            password=password,
        )

        if not self.send_message(message):
            return False

        try:
            data = self.client_socket.recv(1024)
            if not data:
                return False

            self.receive_buffer += data
            message_data, self.receive_buffer = self.protocol.extract_message(
                self.receive_buffer
            )
            if message_data is None:
                return False

            response = self.protocol.deserialize_response(message_data)

            if response.status == Status.SUCCESS:
                if action == "register":
                    # Show registration success message
                    QMessageBox.information(
                        None, "Success", "Registration successful! Logging in..."
                    )
                    # Try logging in with the same credentials
                    return self.authenticate(password, "login")
                return True
            else:
                # Show the specific error message from the server
                QMessageBox.critical(None, "Error", response.message)
                return False

        except Exception as e:
            print(f"Authentication error: {e}")
            return False

        return False

    def send_message(self, message: ChatMessage) -> bool:
        if not self.connected:
            return False

        try:
            with self._lock:
                data = self.protocol.serialize_message(message)
                framed_data = self.protocol.frame_message(data)
                self.client_socket.send(framed_data)
                return True
        except Exception as e:
            print(f"Error sending message: {e}")
            self.connected = False
            return False

    def send_chat_message(self, content: str) -> bool:
        if ";" in content:
            recipient, message_content = content.split(";", 1)
            recipient = recipient.strip()
            message_content = message_content.strip()

            if not recipient or not message_content:
                return False

            message = ChatMessage(
                username=self.username,
                content=message_content,
                message_type=MessageType.DM,
                recipients=[recipient],
            )
        else:
            message = ChatMessage(
                username=self.username, content=content, message_type=MessageType.CHAT
            )

        return self.send_message(message)

    def fetch_messages(self, count: int = 10):
        fetch_message = ChatMessage(
            username=self.username,
            content="",
            message_type=MessageType.FETCH,
            fetch_count=count,
        )
        self.send_message(fetch_message)

    def mark_messages_read(self):
        if not self.unread_messages:
            return

        mark_read_message = ChatMessage(
            username=self.username,
            content="",
            message_type=MessageType.MARK_READ,
            message_ids=list(self.unread_messages),
        )
        if self.send_message(mark_read_message):
            self.unread_messages.clear()

    def delete_messages(self, message_ids: List[int], recipient: str):
        delete_message = ChatMessage(
            username=self.username,
            content="",
            message_type=MessageType.DELETE,
            message_ids=message_ids,
            recipients=[recipient],
        )
        self.send_message(delete_message)

    def disconnect(self):
        if not self.connected:
            return

        self.connected = False
        try:
            logout_message = ChatMessage(
                username=self.username,
                content=f"{self.username} has left the chat",
                message_type=MessageType.LOGOUT,
            )
            data = self.protocol.serialize_message(logout_message)
            framed_data = self.protocol.frame_message(data)
            self.client_socket.send(framed_data)
        except Exception:
            pass
        finally:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.client_socket.close()


def main():
    parser = argparse.ArgumentParser(description="Start the chat client")
    parser.add_argument("--host", default="localhost", help="Server host address")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument(
        "--protocol",
        default="json",
        choices=["json", "custom"],
        help="Protocol type to use",
    )

    args = parser.parse_args()

    app = QApplication(sys.argv[1:])  # Skip the argparse arguments
    window = ChatWindow(host=args.host, port=args.port, protocol=args.protocol)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
