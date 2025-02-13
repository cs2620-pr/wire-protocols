"""A multi-threaded chat server implementation supporting multiple protocols and persistent storage.

This module provides a flexible chat server that can handle multiple concurrent client connections,
supports different wire protocols, and persists chat data in a SQLite database. The server supports
features like direct messaging, message fetching, read receipts, and account management.
"""

import socket
import threading
import json
import traceback
from typing import Dict, List, Set, Optional
from schemas import ChatMessage, ServerResponse, MessageType, Status, SystemMessage
from protocol import Protocol, ProtocolFactory
from database import Database
import argparse


class ChatServer:
    """A multi-threaded chat server that handles client connections and message routing.

    This class implements a chat server that can:
    - Accept and manage multiple client connections
    - Handle user authentication and registration
    - Route messages between clients
    - Support direct messaging and message history
    - Manage user sessions and connection states
    - Persist messages and user data in a database

    Attributes:
        host (str): The hostname to bind the server to
        port (int): The port number to listen on
        server_socket (socket.socket): The main server socket for accepting connections
        clients (Dict[socket.socket, str]): Maps client sockets to usernames
        usernames (Dict[str, socket.socket]): Maps usernames to client sockets
        lock (threading.Lock): Thread synchronization lock
        running (bool): Server running state flag
        protocol (Protocol): The wire protocol implementation to use
        client_buffers (Dict[socket.socket, bytes]): Buffers for incomplete messages
        db_path (str): Path to the SQLite database file
    """

    def __init__(
        self,
        protocol: Optional[Protocol] = None,
        host: str = "localhost",
        port: int = 8000,
        db_path: str = "chat.db",
    ):
        """Initialize the chat server with the specified configuration.

        Args:
            protocol: The wire protocol to use for message serialization/deserialization
            host: The hostname to bind the server to
            port: The port number to listen on
            db_path: Path to the SQLite database file
        """
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients: Dict[socket.socket, str] = {}  # socket -> username
        self.usernames: Dict[str, socket.socket] = {}  # username -> socket
        self.lock = threading.Lock()
        self.running = True
        self.protocol = protocol or ProtocolFactory.create("json")
        self.client_buffers: Dict[socket.socket, bytes] = {}
        self.db_path = db_path

    def db(self):
        """Get a new database connection instance.

        Returns:
            Database: A new database connection for thread-safe operations
        """
        return Database(self.db_path)

    def start(self):
        """Start the chat server and begin accepting client connections.

        This method runs in an infinite loop until shutdown is requested. For each new
        client connection, it spawns a new thread to handle that client's communication.
        """
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"Server started on {self.host}:{self.port}")

            while self.running:
                try:
                    client_socket, address = self.server_socket.accept()
                    print(f"New connection from {address}")
                    self.client_buffers[client_socket] = (
                        b""  # Initialize buffer for new client
                    )
                    client_thread = threading.Thread(
                        target=self.handle_client, args=(client_socket,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except Exception as e:
                    if self.running:
                        print(f"Error accepting connection: {e}")
        except KeyboardInterrupt:
            print("\nShutting down server...")
        finally:
            self.shutdown()

    def send_to_client(
        self,
        client_socket: socket.socket,
        message: ChatMessage,
        unread_count: Optional[int] = None,
    ) -> bool:
        """Send a message to a specific client.

        Args:
            client_socket: The socket connection to the client
            message: The chat message to send
            unread_count: Optional count of unread messages to include

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        try:
            response = ServerResponse(
                status=Status.SUCCESS,
                message=SystemMessage.NEW_MESSAGE,
                data=message,
                unread_count=unread_count,
            )
            data = self.protocol.serialize_response(response)
            framed_data = self.protocol.frame_message(data)
            client_socket.send(framed_data)
            return True
        except:
            return False

    def handle_dm(self, message: ChatMessage, sender_socket: socket.socket) -> None:
        """Handle direct message, storing and delivering as appropriate.

        Args:
            message: The direct message to handle
            sender_socket: The socket of the sending client

        The function:
        1. Validates all recipients exist
        2. Stores the message in the database
        3. Delivers to all recipients if online
        4. Sends confirmation back to sender
        """
        if not message.recipients:
            return

        # Validate message content
        if not message.content or message.content.isspace():
            self.send_error(sender_socket, "Empty message not allowed")
            return

        db = self.db()

        # Validate all recipients exist
        for recipient in message.recipients:
            if not db.user_exists(recipient):
                self.send_error(sender_socket, f"User '{recipient}' does not exist")
                return

        # Store the message
        message_id = db.store_message(message)
        message.message_id = message_id

        # Send to all recipients if they're online
        for recipient in message.recipients:
            if recipient in self.usernames:
                recipient_socket = self.usernames[recipient]
                if self.send_to_client(recipient_socket, message):
                    db.mark_delivered(message_id)

        # Also send back to sender so they see their own message with the ID
        if message.username in self.usernames:
            self.send_to_client(self.usernames[message.username], message)

    def handle_fetch_request(
        self, message: ChatMessage, client_socket: socket.socket
    ) -> None:
        """Handle a request to fetch messages from history.

        Args:
            message: The fetch request message containing parameters
            client_socket: The requesting client's socket

        The function handles two types of fetches:
        1. Messages between two specific users
        2. Unread messages for a single user
        """
        if not message.fetch_count:
            message.fetch_count = 10  # Default limit

        db = self.db()

        # If recipients list has two users, fetch messages between them
        if message.recipients and len(message.recipients) == 2:
            user1, user2 = message.recipients
            # Get messages where either user is sender and other is recipient
            messages = db.get_messages_between_users(
                user1=user1, user2=user2, limit=message.fetch_count
            )
        else:
            # Get unread messages for single user
            messages = db.get_unread_messages(
                recipient=message.username, limit=message.fetch_count
            )

        # Get total unread count for progress tracking
        total_unread = db.get_unread_count(message.username)

        # Send each message and mark as delivered if successful
        for msg in messages:
            if self.send_to_client(client_socket, msg, unread_count=total_unread):
                if msg.message_id is not None:
                    db.mark_delivered(msg.message_id)

    def handle_mark_read(self, message: ChatMessage) -> None:
        """Handle a request to mark messages as read.

        Args:
            message: The mark read request containing either:
                    - A recipient username to mark all messages from them as read
                    - A list of specific message IDs to mark as read

        The function updates the read status and sends updated unread counts.
        """
        db = self.db()
        if message.recipients:
            # Mark all messages from the specified user as read
            db.mark_read_from_user(message.username, message.recipients[0])

            # Send updated unread count to the user
            unread_count = db.get_unread_count(message.username)
            if message.username in self.usernames:
                notification = ChatMessage(
                    username="System",
                    content="",
                    message_type=MessageType.CHAT,
                    unread_count=unread_count,
                )
                self.send_to_client(self.usernames[message.username], notification)
        elif message.message_ids:
            # Mark specific messages as read
            db.mark_read(message.message_ids, message.username)

            # Send updated unread count to the user
            unread_count = db.get_unread_count(message.username)
            if message.username in self.usernames:
                notification = ChatMessage(
                    username="System",
                    content="",
                    message_type=MessageType.CHAT,
                    unread_count=unread_count,
                )
                self.send_to_client(self.usernames[message.username], notification)

    def handle_delete_messages(self, message: ChatMessage) -> None:
        """Handle a request to delete messages.

        Args:
            message: The delete request containing message IDs and recipient

        The function:
        1. Deletes the specified messages
        2. Tracks which messages were unread
        3. Notifies affected users about the deletion
        4. Updates unread counts for affected users
        """
        db = self.db()
        if (
            message.message_ids and message.recipients
        ):  # Ensure we have both message IDs and recipient
            deleted_count, deleted_info = db.delete_messages(
                message.message_ids, message.username, message.recipients[0]
            )

            # Create a set of users to notify (both sender and recipients)
            users_to_notify = {message.username}  # Start with the sender

            # Track unread counts per user that need to be decremented
            unread_decrements: Dict[str, int] = (
                {}
            )  # user -> count of their unread messages being deleted

            # Process deleted messages info
            for recipient, was_unread in deleted_info:
                users_to_notify.add(recipient)
                if was_unread:
                    # If this message was unread, increment the count for the recipient
                    unread_decrements[recipient] = (
                        unread_decrements.get(recipient, 0) + 1
                    )

            # Notify all affected users
            for user in users_to_notify:
                if user in self.usernames:
                    # For each user, send their specific unread decrement
                    # Only include unread_count if this user had unread messages deleted
                    unread_count = unread_decrements.get(user, 0)
                    notification = ChatMessage(
                        username=message.username,  # Who deleted the messages
                        content="",  # No content needed
                        message_type=MessageType.DELETE_NOTIFICATION,
                        message_ids=message.message_ids,  # Include the deleted message IDs
                        unread_count=unread_count,  # Include unread decrement for this specific user
                    )
                    self.send_to_client(self.usernames[user], notification)

    def send_to_recipients(self, message: ChatMessage, exclude_socket=None):
        """Send a message to specified recipients or broadcast to all clients.

        Args:
            message: The message to send
            exclude_socket: Optional socket to exclude from receiving the message

        The function handles both targeted messages and broadcasts:
        1. For DMs, it uses handle_dm()
        2. For specific recipients, it sends only to those users
        3. For broadcasts, it sends to all connected clients except excluded
        """
        if message.message_type == MessageType.DM:
            self.handle_dm(message, exclude_socket)
            return

        with self.lock:
            if message.recipients:
                # Send to specific recipients
                for recipient in message.recipients:
                    if recipient in self.usernames:
                        recipient_socket = self.usernames[recipient]
                        if recipient_socket != exclude_socket:
                            if not self.send_to_client(recipient_socket, message):
                                threading.Thread(
                                    target=self.remove_client,
                                    args=(recipient_socket, True),
                                    daemon=True,
                                ).start()
            else:
                # Broadcast to all if no recipients specified
                clients_copy = list(self.clients.items())

        if not message.recipients:
            # Broadcast outside the lock to prevent deadlock
            for client_socket, username in clients_copy:
                if client_socket == exclude_socket:
                    continue

                if not self.send_to_client(client_socket, message):
                    threading.Thread(
                        target=self.remove_client,
                        args=(client_socket, True),
                        daemon=True,
                    ).start()

    def validate_username(self, username: str) -> tuple[bool, str]:
        """Validate the format of a username.

        Args:
            username: The username to validate

        Returns:
            tuple: (is_valid, error_message)
            - is_valid: True if username is valid, False otherwise
            - error_message: Empty string if valid, error description if invalid
        """
        if not username:
            return False, SystemMessage.USERNAME_REQUIRED
        if len(username) < 2:
            return False, SystemMessage.USERNAME_TOO_SHORT
        if not username.replace("_", "").isalnum():
            return False, SystemMessage.INVALID_USERNAME
        return True, ""

    def handle_client(self, client_socket: socket.socket):
        """Handle all communication with a connected client.

        Args:
            client_socket: The socket connection to the client

        This is the main client handling loop that:
        1. Handles authentication/registration
        2. Processes incoming messages
        3. Routes messages to appropriate handlers
        4. Manages client disconnection
        """
        username = None
        db = self.db()
        try:
            while self.running:
                # Receive data from client
                data = client_socket.recv(1024)
                if not data:
                    break

                # Accumulate received data in buffer
                self.client_buffers[client_socket] += data

                while True:
                    # Extract complete messages from buffer
                    message_data, self.client_buffers[client_socket] = (
                        self.protocol.extract_message(
                            self.client_buffers[client_socket]
                        )
                    )
                    if message_data is None:
                        break

                    message = self.protocol.deserialize_message(message_data)

                    # Handle unauthenticated state
                    if username is None:
                        # First message should be login or register
                        if message.message_type not in [
                            MessageType.LOGIN,
                            MessageType.REGISTER,
                        ]:
                            error_response = ServerResponse(
                                status=Status.ERROR,
                                message=SystemMessage.LOGIN_REQUIRED,
                                data=None,
                            )
                            data = self.protocol.serialize_response(error_response)
                            framed_data = self.protocol.frame_message(data)
                            client_socket.send(framed_data)
                            return

                        if message.message_type == MessageType.REGISTER:
                            # Handle registration request
                            is_valid, error_message = self.validate_username(
                                message.username
                            )
                            if not is_valid:
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message=error_message,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                continue  # Keep connection open, allow retry

                            if db.user_exists(message.username):
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message=SystemMessage.USER_EXISTS,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                continue  # Keep connection open, allow retry

                            if not message.password:
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message=SystemMessage.PASSWORD_REQUIRED,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                continue  # Keep connection open, allow retry

                            if db.create_user(message.username, message.password):
                                success_response = ServerResponse(
                                    status=Status.SUCCESS,
                                    message=SystemMessage.REGISTRATION_SUCCESS,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(
                                    success_response
                                )
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                continue  # Keep connection open for login
                            else:
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message=SystemMessage.REGISTRATION_FAILED,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                continue  # Keep connection open, allow retry

                        elif message.message_type == MessageType.LOGIN:
                            # Handle login request
                            if not message.password:
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message=SystemMessage.PASSWORD_REQUIRED,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                return

                            if not db.verify_user(message.username, message.password):
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message=SystemMessage.INVALID_CREDENTIALS,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                return

                            # Check if user is already logged in
                            if message.username in self.usernames:
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message=SystemMessage.USER_ALREADY_LOGGED_IN,
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                return

                            # Login successful, setup client state
                            username = message.username
                            with self.lock:
                                self.clients[client_socket] = username
                                self.usernames[username] = client_socket

                            # Send join notification
                            join_message = ChatMessage(
                                username=username,
                                content=SystemMessage.USER_JOINED.format(username),
                                message_type=MessageType.JOIN,
                            )
                            self.send_to_recipients(join_message)
                            print(f"Client {username} joined the chat")

                            # Send success response with user list
                            all_users = db.get_all_users()
                            active_users = list(self.usernames.keys())
                            success_response = ServerResponse(
                                status=Status.SUCCESS,
                                message=SystemMessage.LOGIN_SUCCESS,
                                data=ChatMessage(
                                    username="System",
                                    content="",
                                    message_type=MessageType.LOGIN,
                                    recipients=all_users,  # All users
                                    active_users=active_users,  # Active users
                                ),
                            )
                            data = self.protocol.serialize_response(success_response)
                            framed_data = self.protocol.frame_message(data)
                            client_socket.send(framed_data)

                            # Check for unread messages
                            unread_count = db.get_unread_count(username)
                            if unread_count > 0:
                                notification = ChatMessage(
                                    username="System",
                                    content=SystemMessage.UNREAD_MESSAGES.format(
                                        unread_count
                                    ),
                                    message_type=MessageType.CHAT,
                                )
                                self.send_to_client(client_socket, notification)
                            continue

                    # Handle authenticated state messages
                    if message.message_type == MessageType.LOGOUT:
                        print(f"Client {username} logged out")
                        break
                    elif message.message_type == MessageType.FETCH:
                        self.handle_fetch_request(message, client_socket)
                    elif message.message_type == MessageType.MARK_READ:
                        self.handle_mark_read(message)
                    elif message.message_type == MessageType.DELETE:
                        self.handle_delete_messages(message)
                    elif message.message_type == MessageType.DM:
                        if not message.recipients:
                            continue
                        print(f"DM from {username} to {message.recipients}")
                        self.handle_dm(message, client_socket)
                    elif message.message_type == MessageType.DELETE_ACCOUNT:
                        # Delete the user's account
                        if username is None:
                            continue

                        if db.delete_user(username):
                            # Notify all users about the account deletion
                            notification = ChatMessage(
                                username="System",
                                content=SystemMessage.ACCOUNT_DELETED.format(username),
                                message_type=MessageType.DELETE_ACCOUNT,
                                recipients=list(
                                    self.usernames.keys()
                                ),  # Send to all active users
                            )
                            self.send_to_recipients(notification)

                            # Send updated user list to all remaining users
                            all_users = db.get_all_users()
                            active_users = [
                                u for u in self.usernames.keys() if u != username
                            ]
                            update = ChatMessage(
                                username="System",
                                content="",
                                message_type=MessageType.LOGIN,  # Reuse LOGIN type for user list update
                                recipients=all_users,
                                active_users=active_users,
                            )
                            self.send_to_recipients(update)

                            # Close the connection
                            break
                    else:
                        self.send_to_recipients(message)

        except Exception as e:
            print(f"Error handling client: {e}")
            traceback.print_exc()
        finally:
            if username:
                print(f"Removing client {username}")
                self.remove_client(client_socket, send_logout_message=True)
            else:
                self.remove_client(client_socket, send_logout_message=False)

    def remove_client(
        self, client_socket: socket.socket, send_logout_message: bool = True
    ):
        """Remove a client from the server and clean up their resources.

        Args:
            client_socket: The socket connection to remove
            send_logout_message: Whether to broadcast a logout notification

        This function:
        1. Removes client from internal tracking
        2. Optionally broadcasts logout message
        3. Closes the client socket
        """
        username = None
        with self.lock:
            if client_socket in self.clients:
                username = self.clients[client_socket]
                del self.clients[client_socket]
                if username in self.usernames:
                    del self.usernames[username]
                if client_socket in self.client_buffers:
                    del self.client_buffers[client_socket]

        if username and send_logout_message:
            logout_message = ChatMessage(
                username=username,
                content=SystemMessage.USER_LOGGED_OUT.format(username),
                message_type=MessageType.LOGOUT,
            )
            self.send_to_recipients(logout_message, exclude_socket=client_socket)
            print(f"Broadcasting that {username} has logged out")

        try:
            client_socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            client_socket.close()
        except:
            pass

    def shutdown(self):
        """Gracefully shut down the server.

        This function:
        1. Sets the running flag to False
        2. Closes all client connections
        3. Closes the server socket
        """
        self.running = False

        # First close all client sockets
        with self.lock:
            clients_to_remove = list(self.clients.keys())

        # Let remove_client handle the socket shutdown/close
        for client_socket in clients_to_remove:
            self.remove_client(client_socket)

        # Then close the server socket
        try:
            self.server_socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            self.server_socket.close()
        except:
            pass

        print("Server shutdown complete")

    def send_error(self, client_socket: socket.socket, error_message: str) -> None:
        """Send an error response to a client.

        Args:
            client_socket: The socket connection to send the error to
            error_message: The error message to send
        """
        error_response = ServerResponse(
            status=Status.ERROR,
            message=error_message,
            data=None,
        )
        data = self.protocol.serialize_response(error_response)
        framed_data = self.protocol.frame_message(data)
        client_socket.send(framed_data)


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Start the chat server")
    parser.add_argument("--host", default="localhost", help="Host address to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument(
        "--protocol",
        default="json",
        choices=["json", "custom"],
        help="Protocol type to use",
    )
    parser.add_argument(
        "--db-path",
        default="chat.db",
        help="Path to the SQLite database file",
    )

    args = parser.parse_args()

    # Create and start the server
    protocol = ProtocolFactory.create(args.protocol)
    server = ChatServer(
        protocol=protocol, host=args.host, port=args.port, db_path=args.db_path
    )
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
