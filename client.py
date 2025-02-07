import socket
import threading
import time
import sys
from queue import Queue, Empty
from typing import Tuple, Optional
from schemas import ChatMessage, MessageType, ServerResponse, Status
from protocol import Protocol, ProtocolFactory


class ChatClient:
    def __init__(
        self,
        username: str,
        protocol: Optional[Protocol] = None,
        host: str = "localhost",
        port: int = 8000,
    ):
        self.username = username
        self.host = host
        self.port = port
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected = False
        self._lock = threading.Lock()
        self.message_queue: Queue[Tuple[str, Optional[str]]] = Queue()
        self.input_thread = None
        self.protocol = protocol or ProtocolFactory.create(
            "json"
        )  # Default to JSON if not specified
        self.receive_buffer = b""

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
        print("Type your message ('quit' to exit)")
        print("For DMs use: username;your message")
        print("For group chat just type your message")

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

    def send_message(self, message: ChatMessage) -> bool:
        if not self.connected:
            return False

        try:
            with self._lock:
                data = self.protocol.serialize_message(message)
                framed_data = self.protocol.frame_message(data)
                self.client_socket.send(framed_data)
                return True
        except Exception as e:
            print(f"Error sending message: {e}")
            self.connected = False
            return False

    def send_chat_message(self, content: str):
        # Check if this is a DM (contains semicolon)
        if ";" in content:
            recipient, message_content = content.split(";", 1)
            recipient = recipient.strip()
            message_content = message_content.strip()

            if not recipient or not message_content:
                print("Invalid format. Use: username;message")
                return True  # Return True to keep the client running

            message = ChatMessage(
                username=self.username,
                content=message_content,
                message_type=MessageType.DM,
                recipients=[recipient],
            )
        else:
            # Regular chat message
            message = ChatMessage(
                username=self.username, content=content, message_type=MessageType.CHAT
            )

        return self.send_message(message)

    def receive_messages(self):
        while self.connected:
            try:
                data = self.client_socket.recv(1024)
                if not data:
                    print("Lost connection to server")
                    self.connected = False
                    self.message_queue.put(("quit", None))
                    break

                self.receive_buffer += data
                while True:
                    message_data, self.receive_buffer = self.protocol.extract_message(
                        self.receive_buffer
                    )
                    if message_data is None:
                        break

                    response = self.protocol.deserialize_response(message_data)

                    if response.status == Status.ERROR:
                        print(f"Error: {response.message}")
                        if response.message == "Username already taken":
                            self.connected = False
                            self.message_queue.put(("quit", None))
                            break

                    if response.data:
                        # Handle different message types
                        if response.data.message_type == MessageType.CHAT:
                            print(f"{response.data.username}: {response.data.content}")
                        elif response.data.message_type == MessageType.DM:
                            if response.data.username == self.username:
                                print(
                                    f"To {response.data.recipients[0]}: {response.data.content}"
                                )
                            else:
                                print(
                                    f"From {response.data.username}: {response.data.content}"
                                )
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
            data = self.protocol.serialize_message(leave_message)
            framed_data = self.protocol.frame_message(data)
            self.client_socket.send(framed_data)
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

        print("Connected to server!")

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
    # Can specify protocol type: "json" or "custom"
    protocol = ProtocolFactory.create("json")
    client = ChatClient(username, protocol=protocol)
    try:
        client.run()
    except KeyboardInterrupt:
        pass  # Already handled in run()
    sys.exit(0)
