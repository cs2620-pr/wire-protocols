from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QLabel,
    QStackedWidget,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
)
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt, QTimer
from client import ChatClient
from models import ResponseStatus
import sys


class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client = ChatClient()
        self.current_user = None
        self.selected_user = None  # Track selected user
        self.last_message_id = 0
        self.is_dark_mode = self.detect_dark_mode()
        self.init_ui()

        # Check messages periodically
        self.message_timer = QTimer()
        self.message_timer.timeout.connect(self.check_messages)
        self.message_timer.start(5000)  # Check every 5 seconds

        # Add periodic user list updates
        self.user_list_timer = QTimer()
        self.user_list_timer.timeout.connect(self.update_user_list)
        self.user_list_timer.start(3000)  # Update every 3 seconds

    def detect_dark_mode(self):
        """Detect if system is using dark mode"""
        app = QApplication.instance()
        palette = app.palette()
        bg_color = palette.color(QPalette.Window)
        # Calculate perceived brightness
        brightness = (
            bg_color.red() * 299 + bg_color.green() * 587 + bg_color.blue() * 114
        ) / 1000
        return brightness < 128

    def get_chat_styles(self):
        """Get chat bubble styles based on theme"""
        if self.is_dark_mode:
            return {
                "background": "#424242",
                "sent_bubble": "#0084ff",
                "received_bubble": "#303030",
                "sent_text": "white",
                "received_text": "#e0e0e0",
            }
        else:
            return {
                "background": "#f0f0f0",
                "sent_bubble": "#0084ff",
                "received_bubble": "#e9ecef",
                "sent_text": "white",
                "received_text": "black",
            }

    def init_ui(self):
        self.setWindowTitle("Chat Application")
        self.setGeometry(100, 100, 800, 600)

        # Create stacked widget for different screens
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Create different screens
        self.login_screen = self.create_login_screen()
        self.chat_screen = self.create_chat_screen()

        # Add screens to stacked widget
        self.stacked_widget.addWidget(self.login_screen)
        self.stacked_widget.addWidget(self.chat_screen)

        # Start with login screen
        self.stacked_widget.setCurrentWidget(self.login_screen)

    def create_login_screen(self):
        widget = QWidget()
        layout = QVBoxLayout()

        # Username input
        username_layout = QHBoxLayout()
        username_label = QLabel("Username:")
        self.username_input = QLineEdit()
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.username_input)

        # Password input
        password_layout = QHBoxLayout()
        password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.password_input)

        # Login and Create Account buttons
        button_layout = QHBoxLayout()
        login_button = QPushButton("Login")
        create_account_button = QPushButton("Create Account")
        login_button.clicked.connect(self.handle_login)
        create_account_button.clicked.connect(self.handle_create_account)
        button_layout.addWidget(login_button)
        button_layout.addWidget(create_account_button)

        # Add all layouts to main layout
        layout.addLayout(username_layout)
        layout.addLayout(password_layout)
        layout.addLayout(button_layout)
        layout.addStretch()

        widget.setLayout(layout)
        return widget

    def create_chat_screen(self):
        widget = QWidget()
        layout = QVBoxLayout()

        # Top bar with user info and logout
        top_bar = QHBoxLayout()
        self.user_label = QLabel()
        logout_button = QPushButton("Logout")
        logout_button.clicked.connect(self.handle_logout)
        top_bar.addWidget(self.user_label)
        top_bar.addStretch()
        top_bar.addWidget(logout_button)

        # Main chat area
        chat_area = QHBoxLayout()

        # User list on the left
        user_list_layout = QVBoxLayout()
        user_list_label = QLabel("Online Users:")
        self.user_list = QListWidget()
        self.user_list.itemClicked.connect(self.select_user)
        user_list_layout.addWidget(user_list_label)
        user_list_layout.addWidget(self.user_list)

        # Chat display and input on the right
        chat_layout = QVBoxLayout()
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        styles = self.get_chat_styles()
        self.chat_display.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {styles['background']};
                padding: 10px;
            }}
        """
        )
        self.message_input = QLineEdit()
        self.message_input.returnPressed.connect(self.send_message)
        send_button = QPushButton("Send")
        send_button.clicked.connect(self.send_message)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(send_button)

        chat_layout.addWidget(self.chat_display)
        chat_layout.addLayout(input_layout)

        # Add layouts to chat area
        chat_area.addLayout(user_list_layout, 1)
        chat_area.addLayout(chat_layout, 3)

        # Add all to main layout
        layout.addLayout(top_bar)
        layout.addLayout(chat_area)

        widget.setLayout(layout)
        return widget

    def handle_login(self):
        username = self.username_input.text()
        password = self.password_input.text()

        try:
            response = self.client.login(username, password)
            if response.status == ResponseStatus.SUCCESS:
                self.current_user = username
                self.user_label.setText(f"Logged in as: {username}")
                self.stacked_widget.setCurrentWidget(self.chat_screen)
                # Start timers when logging in
                self.message_timer.start()
                self.user_list_timer.start()
                self.update_user_list()
                self.check_messages()
            else:
                QMessageBox.warning(self, "Login Failed", response.message)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection error: {str(e)}")

    def handle_create_account(self):
        username = self.username_input.text()
        password = self.password_input.text()

        try:
            response = self.client.create_account(username, password)
            if response.status == ResponseStatus.SUCCESS:
                QMessageBox.information(
                    self, "Success", "Account created successfully!"
                )
                self.handle_login()
            else:
                QMessageBox.warning(self, "Creation Failed", response.message)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection error: {str(e)}")

    def handle_logout(self):
        self.current_user = None
        self.selected_user = None
        self.last_message_id = 0  # Reset message tracking on logout
        self.username_input.clear()
        self.password_input.clear()
        self.stacked_widget.setCurrentWidget(self.login_screen)
        # Stop timers when logging out
        self.message_timer.stop()
        self.user_list_timer.stop()
        self.client.disconnect()

    def update_user_list(self):
        try:
            response = self.client.list_accounts()
            # Check if we got a message notification instead of list response
            if isinstance(response, dict) and "type" in response:
                # Skip message notifications during user list updates
                return

            if response.status == ResponseStatus.SUCCESS:
                # Store current selection
                current_selected = self.user_list.currentItem()
                selected_username = (
                    current_selected.text() if current_selected else None
                )

                self.user_list.clear()
                for user in response.accounts:
                    if user != self.current_user:
                        item = QListWidgetItem(user)
                        self.user_list.addItem(item)
                        # Restore selection if user still exists
                        if user == selected_username:
                            self.user_list.setCurrentItem(item)

        except Exception as e:
            # Don't show warning for message notifications
            if not (isinstance(e, ValueError) and "validation error" in str(e).lower()):
                QMessageBox.warning(
                    self, "Error", f"Failed to update user list: {str(e)}"
                )

    def check_messages(self):
        if not self.current_user:
            return

        try:
            response = self.client.read_messages(self.current_user)
            if response.status == ResponseStatus.SUCCESS:
                selected_user = self.user_list.currentItem()
                if not selected_user:
                    return

                styles = self.get_chat_styles()
                conversation_messages = [
                    msg
                    for msg in response.messages
                    if msg.id > self.last_message_id
                    and (
                        (
                            msg.sender == selected_user.text()
                            and msg.recipient == self.current_user
                        )
                        or (
                            msg.sender == self.current_user
                            and msg.recipient == selected_user.text()
                        )
                    )
                ]

                for message in conversation_messages:
                    if message.sender == self.current_user:
                        # Right-aligned sent message
                        self.chat_display.append(
                            f'<div style="text-align: right;">'
                            f'<span style="background-color: {styles["sent_bubble"]}; '
                            f'color: {styles["sent_text"]}; '
                            f'border-radius: 15px; padding: 8px; margin: 4px; display: inline-block;">'
                            f"{message.content}</span></div>"
                        )
                    else:
                        # Left-aligned received message
                        self.chat_display.append(
                            f'<div style="text-align: left;">'
                            f'<span style="background-color: {styles["received_bubble"]}; '
                            f'color: {styles["received_text"]}; '
                            f'border-radius: 15px; padding: 8px; margin: 4px; display: inline-block;">'
                            f"{message.content}</span></div>"
                        )
                    self.last_message_id = max(self.last_message_id, message.id)

                scrollbar = self.chat_display.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

        except Exception as e:
            print(f"Error checking messages: {e}")

    def select_user(self, item):
        """Handle user selection from the list"""
        self.selected_user = item.text()
        self.chat_display.clear()
        self.last_message_id = 0  # Reset to load all messages with this user
        self.check_messages()  # Immediately load messages

    def send_message(self):
        if not self.current_user or not self.selected_user:
            return

        message = self.message_input.text()
        if not message:
            return

        try:
            response = self.client.send_message(
                self.current_user, self.selected_user, message
            )
            if response.status == ResponseStatus.SUCCESS:
                self.message_input.clear()
                # Message will appear in next check_messages
            else:
                QMessageBox.warning(self, "Error", "Failed to send message")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send message: {str(e)}")


def main():
    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
