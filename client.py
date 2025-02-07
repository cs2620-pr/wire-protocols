import socket
import threading
import time
import sys
from queue import Queue, Empty
from typing import Tuple, Optional
from schemas import ChatMessage, MessageType, ServerResponse


class ChatClient:
    def __init__(self, username: str, host: str = "localhost", port: int = 8000):
        self.username = username
        self.host = host
        self.port = port
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected = False
        self._lock = threading.Lock()
        self.message_queue: Queue[Tuple[str, Optional[str]]] = Queue()
        self.input_thread = None

    def connect(self):
        try:
            self.client_socket.connect((self.host, self.port))
            self.connected = True

            # Send initial join message with username
            join_message = ChatMessage(
                username=self.username, content="", message_type=MessageType.JOIN
            )
            self.send_message(join_message)

            # Start receiving messages in a separate thread
            receive_thread = threading.Thread(target=self.receive_messages)
            receive_thread.daemon = True
            receive_thread.start()

            # Start input thread
            self.input_thread = threading.Thread(target=self.handle_input)
            self.input_thread.daemon = True
            self.input_thread.start()

            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def handle_input(self):
        while self.connected:
            try:
                message = input()
                if message.lower() == "quit":
                    self.message_queue.put(("quit", None))
                    break
                self.message_queue.put(("message", message))
            except (EOFError, KeyboardInterrupt):
                self.message_queue.put(("quit", None))
                break

    def send_message(self, message: ChatMessage):
        if not self.connected:
            return False

        try:
            with self._lock:
                self.client_socket.send(message.model_dump_json().encode() + b"\n")
                return True
        except Exception as e:
            print(f"Error sending message: {e}")
            self.connected = False
            return False

    def send_chat_message(self, content: str):
        message = ChatMessage(username=self.username, content=content)
        return self.send_message(message)

    def receive_messages(self):
        while self.connected:
            try:
                data = self.client_socket.recv(1024).decode().strip()
                if not data:
                    print("Lost connection to server")
                    self.connected = False
                    self.message_queue.put(("quit", None))
                    break

                response = ServerResponse.model_validate_json(data)
                if response.data:
                    # Handle different message types
                    if response.data.message_type == MessageType.CHAT:
                        print(f"{response.data.username}: {response.data.content}")
                    elif response.data.message_type in [
                        MessageType.JOIN,
                        MessageType.LEAVE,
                    ]:
                        print(f"*** {response.data.content} ***")

            except (ConnectionError, OSError) as e:
                if self.connected:  # Only print if we haven't initiated the disconnect
                    print(f"Lost connection to server: {e}")
                self.connected = False
                self.message_queue.put(("quit", None))
                break
            except Exception as e:
                if self.connected:  # Only print if we haven't initiated the disconnect
                    print(f"Error receiving message: {e}")
                self.connected = False
                self.message_queue.put(("quit", None))
                break

    def disconnect(self):
        if not self.connected:
            return

        # Set connected to False first
        self.connected = False

        try:
            # Send leave message before disconnecting
            leave_message = ChatMessage(
                username=self.username,
                content=f"{self.username} has left the chat",
                message_type=MessageType.LEAVE,
            )
            # Send without using send_message to avoid the lock
            self.client_socket.send(leave_message.model_dump_json().encode() + b"\n")
            time.sleep(0.1)  # Give the server a moment to process
        except Exception:
            pass  # Ignore any errors during disconnect
        finally:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # Socket might already be closed
            self.client_socket.close()
            print("Disconnected from server")

    def run(self):
        if not self.connect():
            print("Failed to connect to server")
            return

        print("Connected to server! Type your messages (or 'quit' to exit)")

        try:
            while self.connected:
                try:
                    msg_type, content = self.message_queue.get(timeout=0.1)
                    if msg_type == "quit":
                        break
                    elif msg_type == "message" and content:
                        if not self.send_chat_message(content):
                            print("Failed to send message, disconnecting...")
                            break
                except Empty:
                    continue  # Use the proper Queue.Empty exception
                except KeyboardInterrupt:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            print("\nDisconnecting...")
            self.disconnect()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python client.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    client = ChatClient(username)
    try:
        client.run()
    except KeyboardInterrupt:
        pass  # Already handled in run()
    sys.exit(0)
