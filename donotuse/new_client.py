import sys
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QSplitter,
    QGroupBox,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import socket
import threading
import time
from typing import Dict, List, Optional
from new_models import *


class NetworkThread(QThread):
    message_received = pyqtSignal(dict)
    connection_error = pyqtSignal(str)
    response_received = pyqtSignal(dict)

    def __init__(self, socket):
        super().__init__()
        self.socket = socket
        self.running = True
        self.waiting_for_response = False
        self.lock = threading.Lock()

    def run(self):
        while self.running:
            try:
                data = self.socket.recv(4096)
                if not data:
                    break

                decoded = ProtocolHelper.decode(data, Protocol.JSON)

                with self.lock:
                    if self.waiting_for_response:
                        self.waiting_for_response = False
                        self.response_received.emit(decoded)
                    else:
                        self.message_received.emit(decoded)

            except Exception as e:
                self.connection_error.emit(str(e))
                break

    def send_request(self, data: BaseModel):
        with self.lock:
            self.waiting_for_response = True
            encoded = ProtocolHelper.encode(data, Protocol.JSON)
            self.socket.sendall(encoded)


class ChatClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.socket: Optional[socket.socket] = None
        self.username: Optional[str] = None
        self.selected_user: Optional[str] = None
        self.online_users: set = set()
        self.network_thread = None
        self.waiting_for: Optional[str] = None
        self.setup_ui()
        self.setup_network()

    def setup_ui(self):
        self.setWindowTitle("Chat Client")
        self.setGeometry(100, 100, 800, 600)

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # Login group
        login_group = QGroupBox("Login")
        login_layout = QVBoxLayout()

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.handle_login)

        login_layout.addWidget(self.username_input)
        login_layout.addWidget(self.password_input)
        login_layout.addWidget(self.login_button)
        login_group.setLayout(login_layout)
        left_layout.addWidget(login_group)

        # Users group
        users_group = QGroupBox("Users")
        users_layout = QVBoxLayout()
        self.users_tree = QTreeWidget()
        self.users_tree.setHeaderLabels(["Username", "Status"])
        self.users_tree.itemClicked.connect(self.on_user_select)
        users_layout.addWidget(self.users_tree)
        users_group.setLayout(users_layout)
        left_layout.addWidget(users_group)

        # Right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Chat area
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        right_layout.addWidget(self.chat_area)

        # Message input area
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.returnPressed.connect(self.send_message)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)

        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        right_layout.addLayout(input_layout)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)

        # Disable chat controls initially
        self.message_input.setEnabled(False)
        self.send_button.setEnabled(False)

    def setup_network(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect(("localhost", 8000))

            self.network_thread = NetworkThread(self.socket)
            self.network_thread.message_received.connect(self.handle_server_message)
            self.network_thread.connection_error.connect(self.show_error)
            self.network_thread.response_received.connect(self.handle_response)
            self.network_thread.start()

        except Exception as e:
            self.show_error(f"Connection failed: {e}")

    def handle_server_message(self, event: Dict):
        if event["type"] == "user_status":
            if event["status"] == "online":
                self.online_users.add(event["username"])
            else:
                self.online_users.discard(event["username"])
            self.fetch_users()

        elif event["type"] == "new_message":
            if self.selected_user in (event["sender"], event["recipient"]):
                self.fetch_chat_history()

    def handle_response(self, response: Dict):
        if self.waiting_for == "login":
            self.waiting_for = None
            if response["status"] == ResponseStatus.SUCCESS:
                self.username = self.pending_username
                self.username_input.setEnabled(False)
                self.password_input.setEnabled(False)
                self.login_button.setEnabled(False)
                self.fetch_users()
                self.message_input.setEnabled(True)
                self.send_button.setEnabled(True)
            else:
                self.show_error(response["message"])

        elif self.waiting_for == "users":
            self.waiting_for = None
            if response["status"] == ResponseStatus.SUCCESS:
                self.update_users_list(response["data"]["users"])

        elif self.waiting_for == "history":
            self.waiting_for = None
            if response["status"] == ResponseStatus.SUCCESS:
                self.display_messages(response["data"]["messages"])

        elif self.waiting_for == "send":
            self.waiting_for = None
            if response["status"] == ResponseStatus.SUCCESS:
                self.message_input.clear()
                self.fetch_chat_history()

    def handle_login(self):
        username = self.username_input.text()
        password = self.password_input.text()
        self.pending_username = username

        login_request = AuthRequest(
            type=MessageType.AUTH,
            command=CommandType.LOGIN,
            username=username,
            password=password,
        )

        self.waiting_for = "login"
        self.network_thread.send_request(login_request)

    def fetch_users(self):
        request = ListUsersRequest(
            type=MessageType.SYSTEM, command=CommandType.LIST_USERS, pattern="%"
        )
        self.waiting_for = "users"
        self.network_thread.send_request(request)

    def fetch_chat_history(self):
        if not self.selected_user:
            return

        request = ReadMessagesRequest(
            type=MessageType.CHAT,
            command=CommandType.READ_MESSAGES,
            username=self.username,
            other_user=self.selected_user,
            limit=50,
            offset=0,
        )

        self.waiting_for = "history"
        self.network_thread.send_request(request)

    def send_message(self):
        if not self.selected_user or not self.message_input.text():
            return

        request = SendMessageRequest(
            type=MessageType.CHAT,
            command=CommandType.SEND_MESSAGE,
            sender=self.username,
            recipient=self.selected_user,
            content=self.message_input.text(),
            timestamp=time.time(),
        )

        self.waiting_for = "send"
        self.network_thread.send_request(request)

    def update_users_list(self, users: List[str]):
        self.users_tree.clear()
        for user in sorted(users):
            if user != self.username:
                item = QTreeWidgetItem()
                item.setText(0, user)
                status = "🟢 Online" if user in self.online_users else "⚪ Offline"
                item.setText(1, status)
                self.users_tree.addTopLevelItem(item)

    def on_user_select(self, item: QTreeWidgetItem, column: int):
        self.selected_user = item.text(0)
        self.fetch_chat_history()

    def display_messages(self, messages: List[Dict]):
        self.chat_area.clear()
        cursor = self.chat_area.textCursor()

        for msg in messages:
            is_own = msg["sender"] == self.username
            is_read = msg.get("read", False)

            timestamp = time.strftime("%H:%M:%S", time.localtime(msg["timestamp"]))

            if is_own:
                alignment = Qt.AlignmentFlag.AlignRight
                color = "blue"
                status = "✓✓" if is_read else "✓"
            else:
                alignment = Qt.AlignmentFlag.AlignLeft
                color = "green"
                status = ""

            cursor.insertHtml(
                f'<div align="{alignment}">'
                f'<span style="color: gray">{timestamp}</span> '
                f'<span style="color: {color}">{msg["content"]}</span> '
                f"{status}</div><br>"
            )

    def show_error(self, message: str):
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        if self.network_thread:
            self.network_thread.stop()
        if self.socket:
            self.socket.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    client = ChatClient()
    client.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
