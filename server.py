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
    def __init__(
        self,
        protocol: Optional[Protocol] = None,
        host: str = "localhost",
        port: int = 8000,
        db_path: str = "chat.db",
    ):
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
        return Database(self.db_path)

    def start(self):
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
        """Handle direct message, storing and delivering as appropriate"""
        if not message.recipients:
            return

        db = self.db()

        # Validate recipient exists
        recipient = message.recipients[0]
        if not db.user_exists(recipient):
            self.send_error(sender_socket, f"User '{recipient}' does not exist")
            return

        # Store the message
        message_id = db.store_message(message)
        message.message_id = message_id

        # Send to recipient if they're online
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
        """Handle request to fetch messages"""
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
        """Handle request to mark messages as read"""
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
        """Handle request to delete messages"""
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
        """Send message to specific recipients or broadcast if no recipients specified"""
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
        """Validate username format. Returns (is_valid, error_message)"""
        if not username:
            return False, SystemMessage.USERNAME_REQUIRED
        if len(username) < 2:
            return False, SystemMessage.USERNAME_TOO_SHORT
        if not username.replace("_", "").isalnum():
            return False, SystemMessage.INVALID_USERNAME
        return True, ""

    def handle_client(self, client_socket: socket.socket):
        username = None
        db = self.db()
        try:
            while self.running:
                data = client_socket.recv(1024)
                if not data:
                    break

                self.client_buffers[client_socket] += data

                while True:
                    message_data, self.client_buffers[client_socket] = (
                        self.protocol.extract_message(
                            self.client_buffers[client_socket]
                        )
                    )
                    if message_data is None:
                        break

                    message = self.protocol.deserialize_message(message_data)

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
                            # Validate username format
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
        """Shutdown the server and close all client connections"""
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
        """Send an error response to a client"""
        error_response = ServerResponse(
            status=Status.ERROR,
            message=error_message,
            data=None,
        )
        data = self.protocol.serialize_response(error_response)
        framed_data = self.protocol.frame_message(data)
        client_socket.send(framed_data)


if __name__ == "__main__":
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

    protocol = ProtocolFactory.create(args.protocol)
    server = ChatServer(
        protocol=protocol, host=args.host, port=args.port, db_path=args.db_path
    )
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
