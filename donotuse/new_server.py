import socket
import threading
import json
import sqlite3
import logging
from typing import Dict, Set, Optional
from datetime import datetime
from new_models import *
import time


class ChatServer:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        protocol: Protocol = Protocol.JSON,
        db_path: str = "chat.db",
    ):
        # Setup logging
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(__name__)

        # Server configuration
        self.host = host
        self.port = port
        self.protocol = protocol
        self.db_path = db_path

        # Initialize connections and state
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.active_connections: Dict[str, socket.socket] = {}
        self.connection_lock = threading.Lock()

        # Initialize database
        self.init_database()

    def init_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                read INTEGER DEFAULT 0,
                FOREIGN KEY (sender) REFERENCES users(username),
                FOREIGN KEY (recipient) REFERENCES users(username)
            )
        """
        )
        self.conn.commit()

    def start(self):
        """Start the chat server"""
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.logger.info(f"Server started on {self.host}:{self.port}")

        try:
            while True:
                client_socket, address = self.server_socket.accept()
                self.logger.info(f"New connection from {address}")
                client_thread = threading.Thread(
                    target=self.handle_client, args=(client_socket,), daemon=True
                )
                client_thread.start()
        except KeyboardInterrupt:
            self.logger.info("Server shutting down...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up server resources"""
        self.server_socket.close()
        self.conn.close()
        for sock in self.active_connections.copy().values():
            sock.close()

    def handle_client(self, client_socket: socket.socket):
        """Handle individual client connection"""
        username = None
        try:
            while True:
                data = self.receive_data(client_socket)
                if not data:
                    break

                response = self.process_message(data, client_socket)
                self.send_data(client_socket, response)

                # Update active connections after successful login
                if (
                    isinstance(response, AuthResponse)
                    and response.status == ResponseStatus.SUCCESS
                    and data.get("command") == CommandType.LOGIN
                ):
                    username = data.get("username")
                    if username:
                        with self.connection_lock:
                            self.active_connections[username] = client_socket

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            if username:
                with self.connection_lock:
                    self.active_connections.pop(username, None)
            client_socket.close()

    def send_data(self, sock: socket.socket, data: BaseModel):
        """Send data using the configured protocol"""
        try:
            encoded_data = ProtocolHelper.encode(data, self.protocol)
            sock.sendall(encoded_data)
        except Exception as e:
            self.logger.error(f"Error sending data: {e}")
            raise

    def receive_data(self, sock: socket.socket) -> Optional[Dict]:
        """Receive data using the configured protocol"""
        try:
            data = sock.recv(4096)
            if not data:
                return None
            return ProtocolHelper.decode(data, self.protocol)
        except Exception as e:
            self.logger.error(f"Error receiving data: {e}")
            raise

    def process_message(self, data: Dict, client_socket: socket.socket) -> BaseResponse:
        """Process incoming messages and route to appropriate handler"""
        try:
            # Log incoming data for debugging
            self.logger.info(f"Processing message: {data}")

            message_type = data.get("type")
            command = data.get("command")

            if not message_type or not command:
                raise ValueError(f"Missing message type or command in request: {data}")

            # Convert string values to enum types
            try:
                message_type = MessageType(message_type)
                command = CommandType(command)
            except ValueError as e:
                raise ValueError(
                    f"Invalid message type or command: {message_type}, {command}"
                )

            if message_type == MessageType.AUTH:
                if command == CommandType.CREATE_ACCOUNT:
                    return self.handle_create_account(data)
                elif command == CommandType.LOGIN:
                    return self.handle_login(data)
                elif command == CommandType.DELETE_ACCOUNT:
                    return self.handle_delete_account(data)
            elif message_type == MessageType.SYSTEM:
                if command == CommandType.LIST_USERS:
                    return self.handle_list_users(data)
            elif message_type == MessageType.CHAT:
                if command == CommandType.SEND_MESSAGE:
                    return self.handle_send_message(data)
                elif command == CommandType.READ_MESSAGES:
                    return self.handle_read_messages(data)

            raise ValueError(
                f"Unsupported combination of message type and command: {message_type}, {command}"
            )

        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_create_account(self, data: Dict) -> BaseResponse:
        """Handle account creation"""
        try:
            request = AuthRequest(**data)
            cursor = self.conn.cursor()

            # Check if username exists
            cursor.execute(
                "SELECT username FROM users WHERE username = ?", (request.username,)
            )
            if cursor.fetchone():
                return BaseResponse(
                    status=ResponseStatus.ERROR, message="Username already exists"
                )

            # Create account
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (
                    request.username,
                    request.password,
                ),  # In real app, hash password first
            )
            self.conn.commit()

            return BaseResponse(
                status=ResponseStatus.SUCCESS, message="Account created successfully"
            )

        except Exception as e:
            self.logger.error(f"Error creating account: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_login(self, data: Dict) -> AuthResponse:
        """Handle login request"""
        try:
            request = AuthRequest(**data)
            cursor = self.conn.cursor()

            # Verify credentials
            cursor.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                (request.username,),
            )
            result = cursor.fetchone()

            if not result or result[0] != request.password:  # In real app, verify hash
                return AuthResponse(
                    status=ResponseStatus.ERROR,
                    message="Invalid credentials",
                    unread_count=0,
                )

            # Get unread message count
            cursor.execute(
                """SELECT COUNT(*) FROM messages 
                   WHERE recipient = ? AND read = 0""",
                (request.username,),
            )
            unread_count = cursor.fetchone()[0]

            return AuthResponse(
                status=ResponseStatus.SUCCESS,
                message="Login successful",
                token="dummy_token",  # In real app, generate proper token
                unread_count=unread_count,
            )

        except Exception as e:
            self.logger.error(f"Error during login: {e}")
            return AuthResponse(
                status=ResponseStatus.ERROR, message=str(e), unread_count=0
            )

    def handle_list_users(self, data: Dict) -> BaseResponse:
        """Handle listing online users"""
        try:
            self.logger.info("Processing list users request")
            cursor = self.conn.cursor()
            cursor.execute("SELECT username FROM users")
            all_users = [row[0] for row in cursor.fetchall()]

            self.logger.info(f"Found users: {all_users}")

            response = BaseResponse(
                status=ResponseStatus.SUCCESS,
                message="Users retrieved successfully",
                data={"users": all_users},
            )

            self.logger.info(f"Sending response: {response.model_dump()}")
            return response

        except Exception as e:
            self.logger.error(f"Error listing users: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def broadcast_message(self, message: ChatMessage):
        """Broadcast message to recipient if online"""
        try:
            recipient_socket = self.active_connections.get(message.recipient)
            if recipient_socket:
                self.send_data(recipient_socket, message)
        except Exception as e:
            self.logger.error(f"Error broadcasting message: {e}")

    def handle_send_message(self, data: Dict) -> BaseResponse:
        """Handle message sending"""
        try:
            request = SendMessageRequest(**data)
            cursor = self.conn.cursor()

            # Store message
            cursor.execute(
                """INSERT INTO messages 
                   (sender, recipient, content, timestamp, read)
                   VALUES (?, ?, ?, ?, 0)""",
                (request.sender, request.recipient, request.content, request.timestamp),
            )
            self.conn.commit()

            sender = data.get("sender")
            if sender is None:
                raise ValueError("Sender is required")

            # Create chat message for broadcast
            message = ChatMessage(
                id=cursor.lastrowid,
                sender=sender,
                recipient=request.recipient,
                content=request.content,
                timestamp=time.time(),
            )

            # Broadcast to recipient if online
            self.broadcast_message(message)

            return BaseResponse(
                status=ResponseStatus.SUCCESS, message="Message sent successfully"
            )

        except Exception as e:
            self.logger.error(f"Error sending message: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_read_messages(self, data: Dict) -> BaseResponse:
        """Handle message reading"""
        try:
            request = ReadMessagesRequest(**data)
            username = data.get("username")
            if username is None:
                raise ValueError("Username is required")

            cursor = self.conn.cursor()

            # Get messages
            cursor.execute(
                """SELECT id, sender, recipient, content, timestamp, read
                   FROM messages 
                   WHERE recipient = ?
                   ORDER BY timestamp DESC
                   LIMIT ? OFFSET ?""",
                (username, request.limit, request.offset),
            )

            messages = [
                ChatMessage(
                    id=row[0],
                    sender=row[1],
                    recipient=row[2],
                    content=row[3],
                    timestamp=row[4],
                    read=bool(row[5]),
                )
                for row in cursor.fetchall()
            ]

            # Mark messages as read
            if messages:
                cursor.execute(
                    """UPDATE messages SET read = 1 
                       WHERE id IN ({})""".format(
                        ",".join("?" * len(messages))
                    ),
                    [msg.id for msg in messages],
                )
                self.conn.commit()

            return BaseResponse(
                status=ResponseStatus.SUCCESS,
                message="Messages retrieved successfully",
                data={"messages": [msg.model_dump() for msg in messages]},
            )

        except Exception as e:
            self.logger.error(f"Error reading messages: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_delete_messages(self, data: Dict) -> BaseResponse:
        """Handle message deletion"""
        try:
            request = DeleteMessagesRequest(**data)
            cursor = self.conn.cursor()

            # Delete messages
            cursor.execute(
                """DELETE FROM messages 
                   WHERE id IN ({})""".format(
                    ",".join("?" * len(request.message_ids))
                ),
                request.message_ids,
            )
            self.conn.commit()

            return BaseResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Deleted {cursor.rowcount} messages",
            )

        except Exception as e:
            self.logger.error(f"Error deleting messages: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_delete_account(self, data: Dict) -> BaseResponse:
        """Handle account deletion"""
        try:
            username = data.get("username")
            if username is None:
                raise ValueError("Username is required")

            cursor = self.conn.cursor()

            # Delete messages first
            cursor.execute(
                "DELETE FROM messages WHERE sender = ? OR recipient = ?",
                (username, username),
            )

            # Delete user
            cursor.execute("DELETE FROM users WHERE username = ?", (username,))
            rows_affected = cursor.rowcount
            self.conn.commit()

            if rows_affected == 0:
                return BaseResponse(
                    status=ResponseStatus.ERROR, message="Account not found"
                )

            # Remove from active connections
            with self.connection_lock:
                self.active_connections.pop(username, None)

            return BaseResponse(
                status=ResponseStatus.SUCCESS, message="Account deleted successfully"
            )

        except Exception as e:
            self.logger.error(f"Error deleting account: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_logout(self, data: Dict) -> BaseResponse:
        """Handle logout request"""
        try:
            username = data.get("username")
            if username is None:
                raise ValueError("Username is required")
            with self.connection_lock:
                self.active_connections.pop(username, None)

            return BaseResponse(
                status=ResponseStatus.SUCCESS, message="Logged out successfully"
            )

        except Exception as e:
            self.logger.error(f"Error during logout: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))


if __name__ == "__main__":
    server = ChatServer()
    server.start()
