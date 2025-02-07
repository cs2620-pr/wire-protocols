import socket
import threading
import json
from schemas import ChatMessage, ServerResponse, MessageType, Status


class ChatServer:
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients: dict[socket.socket, str] = {}  # socket -> username
        self.lock = threading.Lock()
        self.running = True

    def start(self):
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"Server started on {self.host}:{self.port}")

            while self.running:
                try:
                    client_socket, address = self.server_socket.accept()
                    print(f"New connection from {address}")
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
            client_socket.send(response.model_dump_json().encode() + b"\n")
            return True
        except:
            return False

    def broadcast(self, message: ChatMessage, exclude_socket=None):
        with self.lock:
            # Create a copy of the clients dict to avoid modification during iteration
            clients_copy = list(self.clients.items())

        # Broadcast outside the lock to prevent deadlock
        for client_socket, username in clients_copy:
            if client_socket == exclude_socket:
                continue

            if not self.send_to_client(client_socket, message):
                # If send fails, schedule the client for removal
                threading.Thread(
                    target=self.remove_client, args=(client_socket, True), daemon=True
                ).start()

    def handle_client(self, client_socket: socket.socket):
        username = None
        try:
            # First message should be the username
            data = client_socket.recv(1024).decode().strip()
            if not data:
                return

            message = ChatMessage.model_validate_json(data)
            username = message.username

            with self.lock:
                self.clients[client_socket] = username

            # Broadcast join message
            join_message = ChatMessage(
                username=username,
                content=f"{username} has joined the chat",
                message_type=MessageType.JOIN,
            )
            self.broadcast(join_message)
            print(f"Client {username} joined the chat")

            while self.running:
                try:
                    data = client_socket.recv(1024).decode().strip()
                    if not data:
                        print(f"Client {username} disconnected")
                        break

                    message = ChatMessage.model_validate_json(data)
                    if message.message_type == MessageType.LEAVE:
                        print(f"Client {username} left the chat")
                        break
                    self.broadcast(message)
                except json.JSONDecodeError:
                    continue
                except (ConnectionError, OSError):
                    print(f"Client {username} connection lost")
                    break
                except Exception as e:
                    print(f"Error handling client {username}: {e}")
                    break

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

        if username and send_leave_message:
            leave_message = ChatMessage(
                username=username,
                content=f"{username} has left the chat",
                message_type=MessageType.LEAVE,
            )
            # Broadcast the leave message before closing the socket
            self.broadcast(leave_message, exclude_socket=client_socket)
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
    server = ChatServer()
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
