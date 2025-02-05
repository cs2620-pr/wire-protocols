import hashlib
import socket
import sqlite3
import threading
from typing import Tuple
from models import LoginResponse, BaseResponse, AuthRequest, ResponseStatus


class AuthManager:
    def __init__(self, db_connection: sqlite3.Connection):
        self.conn = db_connection
        self.lock = threading.Lock()
        self.active_connections: dict[str, socket.socket] = {}

    def hash_password(self, password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    def create_account(self, request: AuthRequest) -> BaseResponse:
        """Create a new user account"""
        with self.lock:
            try:
                # Validate username
                if not request.username:
                    return BaseResponse(
                        status=ResponseStatus.ERROR, message="Username cannot be empty"
                    )

                cursor = self.conn.cursor()
                if cursor.execute(
                    "SELECT 1 FROM users WHERE username = ?", (request.username,)
                ).fetchone():
                    return BaseResponse(
                        status=ResponseStatus.ERROR, message="Username already exists"
                    )

                cursor.execute(
                    "INSERT INTO users VALUES (?, ?)",
                    (request.username, self.hash_password(request.password)),
                )
                self.conn.commit()
                return BaseResponse(
                    status=ResponseStatus.SUCCESS,
                    message="Account created successfully",
                )
            except Exception as e:
                return BaseResponse(status=ResponseStatus.ERROR, message=str(e))

    def verify_login(self, username: str, password: str) -> Tuple[bool, str]:
        """Verify login credentials"""
        cursor = self.conn.cursor()
        print(f"Verifying login for {username}")  # Debug print
        cursor.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        )
        result = cursor.fetchone()

        if not result:
            print("User not found")  # Debug print
            return False, "User does not exist"

        stored_hash = result[0]
        input_hash = self.hash_password(password)
        print(f"Stored hash: {stored_hash}")  # Debug print
        print(f"Input hash: {input_hash}")  # Debug print
        if input_hash == stored_hash:
            return True, "Login successful"
        return False, "Invalid password"

    def login(
        self, request: AuthRequest, client_socket: socket.socket
    ) -> LoginResponse:
        """Handle login request"""
        try:
            success, msg = self.verify_login(request.username, request.password)
            if not success:
                return LoginResponse(
                    status=ResponseStatus.ERROR, message=msg, unread_messages=0
                )

            # Get unread message count
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE recipient = ? AND read = 0",
                (request.username,),
            )
            unread_count = cursor.fetchone()[0]

            # Store active connection
            self.active_connections[request.username] = client_socket

            return LoginResponse(
                status=ResponseStatus.SUCCESS,
                message="Login successful",
                unread_messages=unread_count,
            )
        except Exception as e:
            print(f"Login error: {e}")  # Add debug print
            return LoginResponse(
                status=ResponseStatus.ERROR, message=str(e), unread_messages=0
            )

    def delete_account(self, username: str) -> BaseResponse:
        """Delete a user account"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM users WHERE username = ?", (username,))
            if cursor.rowcount == 0:
                return BaseResponse(
                    status=ResponseStatus.ERROR, message="Account not found"
                )
            self.conn.commit()

            # Remove from active connections if logged in
            self.active_connections.pop(username, None)

            return BaseResponse(
                status=ResponseStatus.SUCCESS, message="Account deleted successfully"
            )
        except Exception as e:
            return BaseResponse(
                status=ResponseStatus.ERROR, message=f"Error deleting account: {str(e)}"
            )

    def get_active_connections(self) -> dict[str, socket.socket]:
        """Get dictionary of active connections"""
        return self.active_connections

    def remove_connection(self, client_socket: socket.socket) -> None:
        """Remove a client connection"""
        for username, sock in list(self.active_connections.items()):
            if sock == client_socket:
                del self.active_connections[username]
                break
