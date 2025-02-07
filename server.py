import socket
import threading
import json
from typing import Dict, List, Set, Optional
from schemas import ChatMessage, ServerResponse, MessageType, Status
from protocol import Protocol, ProtocolFactory


class ChatServer:
    def __init__(
        self,
        protocol: Optional[Protocol] = None,
        host: str = "localhost",
        port: int = 8000,
    ):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients: Dict[socket.socket, str] = {}  # socket -> username
        self.usernames: Dict[str, socket.socket] = {}  # username -> socket
        self.lock = threading.Lock()
        self.running = True
        self.protocol = protocol or ProtocolFactory.create(
            "json"
        )  # Default to JSON if not specified
        self.client_buffers: Dict[socket.socket, bytes] = {}  # Buffer for each client

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
        self, client_socket: socket.socket, message: ChatMessage
    ) -> bool:
        try:
            response = ServerResponse(
                status=Status.SUCCESS, message="new_message", data=message
            )
            data = self.protocol.serialize_response(response)
            framed_data = self.protocol.frame_message(data)
            client_socket.send(framed_data)
            return True
        except:
            return False

    def send_to_recipients(self, message: ChatMessage, exclude_socket=None):
        """Send message to specific recipients or broadcast if no recipients specified"""
        with self.lock:
            if message.recipients:
                # Send to specific recipients
                for recipient in message.recipients:
                    if recipient in self.usernames:
                        recipient_socket = self.usernames[recipient]
                        if recipient_socket != exclude_socket:
                            if not self.send_to_client(recipient_socket, message):
                                # If send fails, schedule the client for removal
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
                    # If send fails, schedule the client for removal
                    threading.Thread(
                        target=self.remove_client,
                        args=(client_socket, True),
                        daemon=True,
                    ).start()

    def handle_client(self, client_socket: socket.socket):
        username = None
        try:
            while self.running:
                data = client_socket.recv(1024)
                if not data:
                    break

                # Accumulate data in the client's buffer
                self.client_buffers[client_socket] += data

                # Process complete messages
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
                        # First message should be the username
                        username = message.username
                        # Check if username is already taken
                        with self.lock:
                            if username in self.usernames:
                                error_response = ServerResponse(
                                    status=Status.ERROR,
                                    message="Username already taken",
                                    data=None,
                                )
                                data = self.protocol.serialize_response(error_response)
                                framed_data = self.protocol.frame_message(data)
                                client_socket.send(framed_data)
                                return

                            self.clients[client_socket] = username
                            self.usernames[username] = client_socket

                        # Broadcast join message
                        join_message = ChatMessage(
                            username=username,
                            content=f"{username} has joined the chat",
                            message_type=MessageType.JOIN,
                        )
                        self.send_to_recipients(join_message)
                        print(f"Client {username} joined the chat")
                        continue

                    if message.message_type == MessageType.LEAVE:
                        print(f"Client {username} left the chat")
                        break

                    # Handle the message based on its type
                    if message.message_type == MessageType.DM:
                        # For DMs, only send to specified recipients
                        if not message.recipients:
                            continue  # Ignore DMs without recipients
                        print(f"DM from {username} to {message.recipients}")

                    self.send_to_recipients(message)

        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            if username:
                print(f"Removing client {username}")
                self.remove_client(client_socket, send_leave_message=True)
            else:
                self.remove_client(client_socket, send_leave_message=False)

    def remove_client(
        self, client_socket: socket.socket, send_leave_message: bool = True
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

        if username and send_leave_message:
            leave_message = ChatMessage(
                username=username,
                content=f"{username} has left the chat",
                message_type=MessageType.LEAVE,
            )
            # Broadcast the leave message before closing the socket
            self.send_to_recipients(leave_message, exclude_socket=client_socket)
            print(f"Broadcasting that {username} has left")

        try:
            client_socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            client_socket.close()
        except:
            pass

    def shutdown(self):
        self.running = False
        with self.lock:
            clients_to_remove = list(self.clients.keys())

        for client_socket in clients_to_remove:
            self.remove_client(client_socket)

        try:
            self.server_socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            self.server_socket.close()
        except:
            pass
        print("Server shutdown complete")


if __name__ == "__main__":
    # Can specify protocol type: "json" or "custom"
    protocol = ProtocolFactory.create("json")
    server = ChatServer(protocol=protocol)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
