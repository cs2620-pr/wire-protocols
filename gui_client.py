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
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import socket
import threading
from typing import Optional, List, Set
from queue import Queue
from schemas import ChatMessage, MessageType, ServerResponse, Status, SystemMessage
from protocol import Protocol, ProtocolFactory


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
    def __init__(self):
        super().__init__()
        self.client = None
        self.receive_thread = None
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
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        chat_layout.addLayout(input_layout)

        # Buttons layout
        button_layout = QHBoxLayout()

        # Fetch messages button with count spinner
        fetch_layout = QHBoxLayout()
        self.fetch_count = QSpinBox()
        self.fetch_count.setRange(1, 100)
        self.fetch_count.setValue(10)
        self.fetch_button = QPushButton("Fetch Messages")
        self.fetch_button.clicked.connect(self.fetch_messages)
        fetch_layout.addWidget(self.fetch_count)
        fetch_layout.addWidget(self.fetch_button)
        button_layout.addLayout(fetch_layout)

        # Other control buttons
        self.mark_read_button = QPushButton("Mark as Read")
        self.mark_read_button.clicked.connect(self.mark_messages_read)
        self.delete_button = QPushButton("Delete Messages")
        self.delete_button.clicked.connect(self.delete_messages)
        self.logout_button = QPushButton("Logout")
        self.logout_button.clicked.connect(self.logout)

        button_layout.addWidget(self.mark_read_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.logout_button)

        chat_layout.addLayout(button_layout)
        main_layout.addLayout(chat_layout, stretch=7)  # Chat area takes 70% of width

        # User list area (right side)
        user_list_layout = QVBoxLayout()
        user_list_layout.addWidget(QLabel("Users:"))
        self.user_list = QTextEdit()
        self.user_list.setReadOnly(True)
        self.user_list.setMaximumWidth(200)  # Limit width of user list
        user_list_layout.addWidget(self.user_list)
        main_layout.addLayout(
            user_list_layout, stretch=3
        )  # User list takes 30% of width

        # Initially disable UI elements until connected
        self.set_ui_enabled(False)

        # Show login dialog on startup
        self.show_login_dialog()

    def set_ui_enabled(self, enabled: bool):
        """Enable or disable UI elements based on connection status"""
        self.message_input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self.fetch_button.setEnabled(enabled)
        self.mark_read_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.logout_button.setEnabled(enabled)
        self.fetch_count.setEnabled(enabled)
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
        self.client = ChatClient(username, protocol=ProtocolFactory.create("json"))

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
        self.display_message("Connected to server!")

        # Update window title to include username
        self.setWindowTitle(f"Chat Client - {username}")
        return True

    def send_message(self):
        if not self.client or not self.client.connected:
            return

        message = self.message_input.text().strip()
        if not message:
            return

        if not self.client.send_chat_message(message):
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
        if not self.client or not self.client.connected:
            return

        message_ids_text, ok = QInputDialog.getText(
            self, "Delete Messages", "Enter message IDs to delete (space-separated):"
        )

        if ok and message_ids_text:
            try:
                message_ids = [int(id) for id in message_ids_text.split()]
                self.client.delete_messages(message_ids)
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

        # Clear the chat display
        self.chat_display.clear()

        # Reset window title
        self.setWindowTitle("Chat Client")

        # Disable UI elements
        self.set_ui_enabled(False)

        # Hide the main window
        self.hide()

        # Show login dialog
        self.show_login_dialog()

        # Show the main window again after login
        self.show()

    def display_message(self, message: str):
        self.chat_display.append(message)

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
        self.user_list.clear()
        for user in sorted(set(all_users)):  # Use set to remove duplicates
            status = "🟢" if user in active_users else "⚪"
            self.user_list.append(f"{status} {user}")

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
            current_all_users = [
                text.split(" ", 1)[1]
                for text in self.user_list.toPlainText().split("\n")
                if text
            ]
            if message.username not in current_all_users:
                current_all_users.append(message.username)

            # Get current active users from the display
            current_active_users = [
                text.split(" ", 1)[1]
                for text in self.user_list.toPlainText().split("\n")
                if text and text.startswith("🟢")
            ]

            # Add the new user to active users
            if message.username not in current_active_users:
                current_active_users.append(message.username)

            # Use server's active_users list if provided, otherwise use our current list
            active_users = (
                message.active_users if message.active_users else current_active_users
            )
            self.update_user_list(current_all_users, active_users)

        elif message.message_type == MessageType.LEAVE:
            # For leave messages, keep the user in the list but mark as inactive
            current_all_users = [
                text.split(" ", 1)[1]
                for text in self.user_list.toPlainText().split("\n")
                if text
            ]
            # Get current active users and remove the leaving user
            current_active_users = [
                text.split(" ", 1)[1]
                for text in self.user_list.toPlainText().split("\n")
                if text and text.startswith("🟢")
            ]
            if message.username in current_active_users:
                current_active_users.remove(message.username)

            # Use server's active_users list if provided, otherwise use our current list
            active_users = (
                message.active_users if message.active_users else current_active_users
            )
            self.update_user_list(current_all_users, active_users)

    def handle_message(self, message: str, message_obj: Optional[ChatMessage] = None):
        """Handle incoming messages and update UI accordingly"""
        if message_obj:
            self.handle_server_message(message_obj)
            # Only display the message after handling server updates
            self.chat_display.append(message)
        else:
            self.chat_display.append(message)


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

    def delete_messages(self, message_ids: List[int]):
        delete_message = ChatMessage(
            username=self.username,
            content="",
            message_type=MessageType.DELETE,
            message_ids=message_ids,
        )
        self.send_message(delete_message)

    def disconnect(self):
        if not self.connected:
            return

        self.connected = False
        try:
            leave_message = ChatMessage(
                username=self.username,
                content=f"{self.username} has left the chat",
                message_type=MessageType.LEAVE,
            )
            data = self.protocol.serialize_message(leave_message)
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
    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
