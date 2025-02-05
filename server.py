import socket
import threading
import json
import sqlite3
from datetime import datetime
from typing import Optional
import logging
from models import (
    Protocol,
    CommandType,
    ResponseStatus,
    Message,
    BaseResponse,
    LoginResponse,
    ListAccountsResponse,
    ReadMessagesResponse,
    AuthRequest,
    ListAccountsRequest,
    SendMessageRequest,
    ReadMessagesRequest,
    DeleteMessagesRequest,
    DeleteAccountRequest,
)
from auth import AuthManager


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

        self.host = host
        self.port = port
        self.protocol = protocol
        self.db_path = db_path

        # Initialize server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Initialize database and auth
        self.init_database()
        self.auth_manager = AuthManager(self.conn)

    def init_database(self):
        """Initialize SQLite database with required tables"""
        self.logger.info(f"Initializing database at {self.db_path}")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT
            )
        """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT,
                recipient TEXT,
                content TEXT,
                timestamp REAL,
                read INTEGER DEFAULT 0,
                FOREIGN KEY(sender) REFERENCES users(username),
                FOREIGN KEY(recipient) REFERENCES users(username)
            )
        """
        )
        self.conn.commit()
        self.logger.info("Database initialization complete")

    def start(self):
        """Start the server and listen for connections"""
        self.logger.info(f"Starting server on {self.host}:{self.port}")
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)  # Add timeout to allow clean shutdown

        while True:
            try:
                client_socket, address = self.server_socket.accept()
                self.logger.info(f"New connection from {address}")
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket,),
                    daemon=True,  # Make thread daemon so it exits when main thread exits
                )
                client_thread.start()
            except socket.timeout:
                continue  # Allow checking for shutdown
            except Exception as e:
                self.logger.error(f"Error accepting connection: {e}")
                break  # Exit on serious errors

    def handle_client(self, client_socket: socket.socket):
        """Handle client connection"""
        try:
            self.logger.debug("Starting client handler")
            while True:
                data = client_socket.recv(4096)
                if not data:
                    self.logger.info("Client disconnected")
                    break

                message = json.loads(data.decode())
                self.logger.debug(f"Received message: {message}")
                response = self.process_message(message, client_socket)
                self.logger.debug(f"Sending response: {response}")
                client_socket.sendall(json.dumps(response.model_dump()).encode())

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            self.cleanup_connection(client_socket)

    def cleanup_connection(self, client_socket: socket.socket):
        """Clean up client connection"""
        self.logger.info("Cleaning up client connection")
        self.auth_manager.remove_connection(client_socket)
        client_socket.close()

    def process_message(
        self, message: dict, client_socket: socket.socket
    ) -> BaseResponse:
        """Process incoming messages"""
        try:
            command = CommandType(message.get("command"))
            self.logger.info(f"Processing {command} command")
            handlers = {
                CommandType.CREATE_ACCOUNT: self.handle_create_account,
                CommandType.LOGIN: self.handle_login,
                CommandType.LIST_ACCOUNTS: self.handle_list_accounts,
                CommandType.SEND_MESSAGE: self.handle_send_message,
                CommandType.READ_MESSAGES: self.handle_read_messages,
                CommandType.DELETE_MESSAGES: self.handle_delete_messages,
                CommandType.DELETE_ACCOUNT: self.handle_delete_account,
            }

            handler = handlers.get(command)
            if handler:
                return handler(message, client_socket)
            self.logger.warning(f"Unknown command received: {command}")
            return BaseResponse(status=ResponseStatus.ERROR, message="Unknown command")

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_create_account(
        self, message: dict, client_socket: socket.socket
    ) -> BaseResponse:
        """Handle account creation"""
        try:
            request = AuthRequest(**message)
            return self.auth_manager.create_account(request)
        except Exception as e:
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_login(
        self, message: dict, client_socket: socket.socket
    ) -> LoginResponse:
        """Handle login request"""
        try:
            request = AuthRequest(**message)
            return self.auth_manager.login(request, client_socket)
        except Exception as e:
            return LoginResponse(
                status=ResponseStatus.ERROR, message=str(e), unread_messages=0
            )

    def handle_list_accounts(
        self, message: dict, client_socket: socket.socket
    ) -> ListAccountsResponse:
        """Handle account listing request"""
        try:
            request = ListAccountsRequest(**message)
            cursor = self.conn.cursor()

            # Get total count for pagination
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE username LIKE ?",
                (f"%{request.pattern}%",),
            )
            total_count = cursor.fetchone()[0]

            # Get paginated results
            cursor.execute(
                "SELECT username FROM users WHERE username LIKE ? LIMIT ? OFFSET ?",
                (
                    f"%{request.pattern}%",
                    request.page_size,
                    (request.page - 1) * request.page_size,
                ),
            )
            accounts = [row[0] for row in cursor.fetchall()]

            return ListAccountsResponse(
                status=ResponseStatus.SUCCESS,
                message="Accounts retrieved successfully",
                accounts=accounts,
                total_count=total_count,
                page=request.page,
                total_pages=(total_count + request.page_size - 1) // request.page_size,
            )
        except Exception as e:
            return ListAccountsResponse(
                status=ResponseStatus.ERROR,
                message=str(e),
                accounts=[],
                total_count=0,
                page=1,
                total_pages=1,
            )

    def handle_send_message(
        self, message: dict, client_socket: socket.socket
    ) -> BaseResponse:
        """Handle message sending request"""
        try:
            request = SendMessageRequest(**message)
            cursor = self.conn.cursor()

            # Verify sender exists
            cursor.execute(
                "SELECT username FROM users WHERE username = ?",
                (request.sender,),
            )
            if not cursor.fetchone():
                return BaseResponse(
                    status=ResponseStatus.ERROR,
                    message="Sender does not exist",
                )

            # Verify recipient exists
            cursor.execute(
                "SELECT username FROM users WHERE username = ?",
                (request.recipient,),
            )
            if not cursor.fetchone():
                return BaseResponse(
                    status=ResponseStatus.ERROR,
                    message="Recipient does not exist",
                )

            # Store message
            cursor.execute(
                """INSERT INTO messages (sender, recipient, content, timestamp, read)
                   VALUES (?, ?, ?, ?, 0)""",
                (
                    request.sender,
                    request.recipient,
                    request.content,
                    datetime.now().timestamp(),
                ),
            )
            self.conn.commit()

            return BaseResponse(
                status=ResponseStatus.SUCCESS,
                message="Message sent successfully",
            )
        except Exception as e:
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_read_messages(
        self, message: dict, client_socket: socket.socket
    ) -> ReadMessagesResponse:
        """Handle message reading request"""
        try:
            request = ReadMessagesRequest(**message)
            cursor = self.conn.cursor()

            # Build query based on whether we want sent or received messages
            if hasattr(request, "sent") and request.sent:
                query = """SELECT id, sender, recipient, content, timestamp, read 
                          FROM messages 
                          WHERE sender = ? 
                          AND recipient = ?
                          AND content LIKE ? 
                          ORDER BY timestamp DESC
                          LIMIT ?"""
            else:
                query = """SELECT id, sender, recipient, content, timestamp, read 
                          FROM messages 
                          WHERE recipient = ? 
                          AND sender = ?
                          AND content LIKE ? 
                          ORDER BY timestamp DESC
                          LIMIT ?"""

            pattern = request.pattern if request.pattern else "%"
            cursor.execute(
                query,
                (request.username, request.recipient, pattern, str(request.limit)),
            )

            messages = [
                Message(
                    id=row[0],
                    sender=row[1],
                    recipient=row[2],
                    content=row[3],
                    timestamp=row[4],
                    read=bool(row[5]),
                )
                for row in cursor.fetchall()
            ]

            # Mark messages as read only for received messages
            if messages and not (hasattr(request, "sent") and request.sent):
                cursor.execute(
                    "UPDATE messages SET read = 1 WHERE id IN ({})".format(
                        ",".join("?" * len(messages))
                    ),
                    [msg.id for msg in messages],
                )
                self.conn.commit()

            response = ReadMessagesResponse(
                status=ResponseStatus.SUCCESS,
                message="Messages retrieved successfully",
                messages=messages,
            )
            return response
        except Exception as e:
            return ReadMessagesResponse(
                status=ResponseStatus.ERROR,
                message=str(e),
                messages=[],
            )

    def handle_delete_messages(
        self, message: dict, client_socket: socket.socket
    ) -> BaseResponse:
        """Handle message deletion request"""
        try:
            request = DeleteMessagesRequest(**message)
            cursor = self.conn.cursor()

            # Delete messages
            cursor.execute(
                """DELETE FROM messages 
                   WHERE recipient = ? AND id IN ({})""".format(
                    ",".join("?" * len(request.message_ids))
                ),
                [request.username] + request.message_ids,
            )
            self.conn.commit()

            return BaseResponse(
                status=ResponseStatus.SUCCESS,
                message=f"Deleted {cursor.rowcount} messages",
            )
        except Exception as e:
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def handle_delete_account(
        self, message: dict, client_socket: socket.socket
    ) -> BaseResponse:
        """Handle account deletion request"""
        try:
            request = DeleteAccountRequest(**message)

            # Start transaction
            self.conn.execute("BEGIN TRANSACTION")
            try:
                # Delete messages first
                cursor = self.conn.cursor()
                cursor.execute(
                    "DELETE FROM messages WHERE sender = ? OR recipient = ?",
                    (request.username, request.username),
                )

                # Delete account
                response = self.auth_manager.delete_account(request.username)
                if response.status == ResponseStatus.SUCCESS:
                    self.conn.commit()
                    return response
                else:
                    self.conn.rollback()
                    return response

            except Exception as e:
                self.conn.rollback()
                raise e

        except Exception as e:
            return BaseResponse(status=ResponseStatus.ERROR, message=str(e))


if __name__ == "__main__":
    server = ChatServer()
    server.start()
