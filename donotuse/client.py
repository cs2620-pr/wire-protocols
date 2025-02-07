from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QTextEdit,
    QMessageBox,
    QStackedWidget,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette
import socket
import json
import sys
from typing import Optional, Dict, Any
from models import CommandType, ResponseStatus, Message
import logging


class ChatClient(QMainWindow):
    def __init__(self, host: str = "localhost", port: int = 8000):
        super().__init__()
        # Get system dark mode setting
        self.dark_mode = self.palette().window().color().lightness() < 128
        # Setup logging
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(__name__)

        self.host = host
        self.port = port
        self.socket: socket.socket | None = None
        self.current_user: str | None = None

        # Initialize UI
        self.setWindowTitle("Chat Client")
        self.setGeometry(100, 100, 800, 600)

        # Create stacked widget for different pages
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Create pages
        self.login_page = self.create_login_page()
        self.chat_page = self.create_chat_page()

        # Add pages to stacked widget
        self.stacked_widget.addWidget(self.login_page)
        self.stacked_widget.addWidget(self.chat_page)

        # Initialize connection
        self.connect_to_server()

    def connect_to_server(self):
        """Establish connection to server"""
        try:
            self.logger.info(f"Connecting to server at {self.host}:{self.port}")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.logger.info("Successfully connected to server")
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            QMessageBox.critical(self, "Connection Error", f"Failed to connect: {e}")
            sys.exit(1)

    def create_login_page(self) -> QWidget:
        """Create login/registration page"""
        page = QWidget()
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Username field
        username_layout = QHBoxLayout()
        username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.username_input)
        layout.addLayout(username_layout)

        # Password field
        password_layout = QHBoxLayout()
        password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.password_input)
        layout.addLayout(password_layout)

        # Buttons
        button_layout = QHBoxLayout()
        login_button = QPushButton("Login")
        login_button.clicked.connect(self.handle_login)
        create_account_button = QPushButton("Create Account")
        create_account_button.clicked.connect(self.handle_create_account)
        button_layout.addWidget(login_button)
        button_layout.addWidget(create_account_button)
        layout.addLayout(button_layout)

        page.setLayout(layout)
        return page

    def create_chat_page(self) -> QWidget:
        """Create main chat interface page"""
        page = QWidget()
        layout = QHBoxLayout()

        # Left panel - User list
        left_panel = QWidget()
        left_layout = QVBoxLayout()

        # Current user display
        self.current_user_label = QLabel()
        self.current_user_label.setStyleSheet("font-weight: bold; color: #2196F3;")
        left_layout.addWidget(self.current_user_label)

        self.user_list = QListWidget()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search users...")
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.search_users)

        left_layout.addWidget(QLabel("Other Users:"))
        left_layout.addWidget(self.search_input)
        left_layout.addWidget(search_button)
        left_layout.addWidget(self.user_list)
        left_panel.setLayout(left_layout)

        # Right panel - Messages
        right_panel = QWidget()
        right_layout = QVBoxLayout()

        self.message_display = QTextEdit()
        self.message_display.setReadOnly(True)
        self.update_chat_style()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type a message...")
        self.message_input.returnPressed.connect(self.send_message)

        # Control buttons
        control_layout = QHBoxLayout()
        read_button = QPushButton("Read Messages")
        read_button.clicked.connect(self.read_messages)
        delete_button = QPushButton("Delete Messages")
        delete_button.clicked.connect(self.delete_messages)
        delete_account_button = QPushButton("Delete Account")
        delete_account_button.clicked.connect(self.delete_account)
        dark_mode_button = QPushButton("Toggle Dark Mode")
        dark_mode_button.clicked.connect(self.toggle_dark_mode)

        control_layout.addWidget(read_button)
        control_layout.addWidget(delete_button)
        control_layout.addWidget(delete_account_button)
        control_layout.addWidget(dark_mode_button)

        right_layout.addWidget(self.message_display)
        right_layout.addWidget(self.message_input)
        right_layout.addLayout(control_layout)
        right_panel.setLayout(right_layout)

        # Add panels to main layout
        layout.addWidget(left_panel, 1)
        layout.addWidget(right_panel, 2)
        page.setLayout(layout)
        return page

    def update_chat_style(self):
        """Update chat styling based on dark/light mode"""
        bg_color = "#1C1C1E" if self.dark_mode else "#f0f0f0"
        text_color = "#FFFFFF" if self.dark_mode else "#000000"
        my_bubble_color = "#0B84FF" if self.dark_mode else "#007AFF"
        other_bubble_color = "#3A3A3C" if self.dark_mode else "#E9E9EB"
        other_text_color = "#FFFFFF" if self.dark_mode else "#000000"
        name_color = "#8E8E93" if self.dark_mode else "#666666"

        self.message_display.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {bg_color};
                border: none;
                padding: 10px;
                color: {text_color};
            }}
            """
        )
        self.chat_styles = {
            "my_message": f"""
                <div style="margin: 16px 0; text-align: right;">
                    <span style="
                        background-color: {my_bubble_color};
                        color: white;
                        border-radius: 18px;
                        padding: 12px 16px;
                        display: inline-block;
                        max-width: 70%;
                        text-align: left;
                        margin-right: 8px;
                    ">
                        {{content}}
                    </span>
                </div>
            """,
            "other_message": f"""
                <div style="margin: 16px 0;">
                    <div style="color: {name_color}; font-size: 0.8em; margin-left: 16px; margin-bottom: 4px;">
                        {{sender}}
                    </div>
                    <span style="
                        background-color: {other_bubble_color};
                        color: {other_text_color};
                        border-radius: 18px;
                        padding: 12px 16px;
                        display: inline-block;
                        max-width: 70%;
                        margin-left: 8px;
                    ">
                        {{content}}
                    </span>
                </div>
            """,
        }

    def send_and_receive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send request to server and receive response"""
        try:
            if self.socket is None:
                raise Exception("Socket not connected")
            self.socket.sendall(json.dumps(data).encode())
            response = self.socket.recv(4096)
            return json.loads(response.decode())
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Communication error: {e}")
            return {"status": ResponseStatus.ERROR, "message": str(e)}

    def handle_login(self):
        """Handle login button click"""
        self.logger.info(f"Attempting login for user: {self.username_input.text()}")
        request = {
            "command": CommandType.LOGIN,
            "username": self.username_input.text(),
            "password": self.password_input.text(),
        }

        response = self.send_and_receive(request)
        if response["status"] == ResponseStatus.SUCCESS:
            self.current_user = self.username_input.text()
            self.logger.info(f"Login successful for user: {self.current_user}")
            QMessageBox.information(
                self,
                "Success",
                f"Welcome back! You have {response['unread_messages']} unread messages.",
            )
            self.show_chat_interface()
        else:
            self.logger.warning(f"Login failed: {response['message']}")
            QMessageBox.warning(self, "Error", response["message"])

    def handle_create_account(self):
        """Handle account creation"""
        request = {
            "command": CommandType.CREATE_ACCOUNT,
            "username": self.username_input.text(),
            "password": self.password_input.text(),
        }

        response = self.send_and_receive(request)
        if response["status"] == ResponseStatus.SUCCESS:
            QMessageBox.information(self, "Success", "Account created successfully!")
        else:
            QMessageBox.warning(self, "Error", response["message"])

    def show_chat_interface(self):
        """Switch to chat interface"""
        self.stacked_widget.setCurrentIndex(1)
        self.current_user_label.setText(f"Signed in as: {self.current_user}")
        self.update_user_list()
        self.start_message_checker()

    def update_user_list(self):
        """Update the list of users"""
        request = {
            "command": CommandType.LIST_ACCOUNTS,
            "pattern": self.search_input.text() or "%",
            "page": 1,
            "page_size": 50,
        }

        response = self.send_and_receive(request)
        if response["status"] == ResponseStatus.SUCCESS:
            self.user_list.clear()
            # Filter out current user from the list
            other_users = [
                user for user in response["accounts"] if user != self.current_user
            ]
            self.user_list.addItems(other_users)

    def search_users(self):
        """Handle user search"""
        self.update_user_list()

    def send_message(self):
        """Send message to selected user"""
        if not self.user_list.currentItem():
            QMessageBox.warning(self, "Warning", "Please select a recipient")
            return

        if not self.message_input.text().strip():
            return  # Don't send empty messages

        recipient = self.user_list.currentItem().text()
        request = {
            "command": CommandType.SEND_MESSAGE,
            "sender": self.current_user,
            "recipient": recipient,
            "content": self.message_input.text(),
        }

        response = self.send_and_receive(request)
        if response["status"] == ResponseStatus.SUCCESS:
            self.message_input.clear()
            self.read_messages()
        else:
            QMessageBox.warning(self, "Error", response["message"])

    def read_messages(self):
        """Read messages"""
        if not self.current_user:
            return

        # Store current recipient
        current_recipient = (
            self.user_list.currentItem().text()
            if self.user_list.currentItem()
            else None
        )
        if not current_recipient:
            return

        # Get messages sent to me
        request = {
            "command": CommandType.READ_MESSAGES,
            "username": self.current_user,
            "recipient": current_recipient,
            "limit": 50,
        }
        response = self.send_and_receive(request)
        received_messages = (
            response["messages"] if response["status"] == ResponseStatus.SUCCESS else []
        )

        # Get messages I sent
        sent_request = {
            "command": CommandType.READ_MESSAGES,
            "username": self.current_user,
            "sent": True,
            "recipient": current_recipient,  # Only get messages to current chat
            "limit": 50,
        }
        sent_response = self.send_and_receive(sent_request)
        sent_messages = (
            sent_response["messages"]
            if sent_response["status"] == ResponseStatus.SUCCESS
            else []
        )

        # Combine and sort all messages by timestamp
        all_messages = received_messages + sent_messages
        all_messages.sort(key=lambda x: x["timestamp"])  # Oldest first

        self.message_display.clear()
        html_messages = []
        for msg in all_messages:
            if msg["sender"] == self.current_user:
                bubble = self.chat_styles["my_message"].format(content=msg["content"])
            else:
                bubble = self.chat_styles["other_message"].format(
                    sender=msg["sender"], content=msg["content"]
                )
            html_messages.append(bubble)

        self.message_display.setHtml("".join(html_messages))
        # Always scroll to bottom
        scrollbar = self.message_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def delete_messages(self):
        """Delete selected messages"""
        # Implementation depends on how you want to select messages for deletion
        pass

    def delete_account(self):
        """Delete current account"""
        reply = QMessageBox.question(
            self,
            "Confirm",
            "Are you sure you want to delete your account?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            request = {
                "command": CommandType.DELETE_ACCOUNT,
                "username": self.current_user,
            }

            response = self.send_and_receive(request)
            if response["status"] == ResponseStatus.SUCCESS:
                QMessageBox.information(self, "Success", "Account deleted successfully")
                self.close()
            else:
                QMessageBox.warning(self, "Error", response["message"])

    def start_message_checker(self):
        """Start timer to check for new messages"""
        self.message_timer = QTimer()
        self.message_timer.timeout.connect(self.read_messages)
        self.message_timer.start(1000)  # Check every 1 second

    def toggle_dark_mode(self):
        """Toggle between dark and light mode"""
        self.dark_mode = not self.dark_mode
        self.update_chat_style()
        self.read_messages()  # Refresh messages with new style


def main():
    app = QApplication(sys.argv)
    client = ChatClient()
    client.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
