import socket
import threading
import time
import sys
from queue import Queue, Empty
from typing import Tuple, Optional, List, Set
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
        self.protocol = protocol or ProtocolFactory.create("json")
        self.receive_buffer = b""
        self.unread_messages: Set[int] = set()  # Track message IDs for marking as read

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
        print("Commands:")
        print("  username;message - Send DM to user")
        print("  /fetch [n]      - Fetch n unread messages (default 10)")
        print("  /read           - Mark displayed messages as read")
        print("  /delete id [id] - Delete messages by ID")
        print("  /quit           - Exit the chat")

        while self.connected:
            try:
                message = input()
                if not message:
                    continue

                if message.startswith("/"):
                    self.handle_command(message[1:])
                else:
                    self.message_queue.put(("message", message))
            except (EOFError, KeyboardInterrupt):
                self.message_queue.put(("quit", None))
                break

    def handle_command(self, command: str):
        parts = command.split()
        cmd = parts[0].lower()

        if cmd == "quit":
            self.message_queue.put(("quit", None))
        elif cmd == "fetch":
            try:
                count = int(parts[1]) if len(parts) > 1 else 10
                self.fetch_messages(count)
            except ValueError:
                print("Invalid count. Usage: /fetch [n]")
        elif cmd == "read":
            self.mark_messages_read()
        elif cmd == "delete":
            try:
                message_ids = [int(id) for id in parts[1:]]
                if not message_ids:
                    print("Usage: /delete message_id [message_id ...]")
                    return
                self.delete_messages(message_ids)
            except ValueError:
                print("Invalid message ID. Usage: /delete message_id [message_id ...]")
        else:
            print("Unknown command. Available commands:")
            print("  /fetch [n] - Fetch n unread messages")
            print("  /read      - Mark displayed messages as read")
            print("  /delete id [id] - Delete messages by ID")
            print("  /quit      - Exit the chat")

    def fetch_messages(self, count: int = 10):
        """Request unread messages from the server"""
        fetch_message = ChatMessage(
            username=self.username,
            content="",
            message_type=MessageType.FETCH,
            fetch_count=count,
        )
        self.send_message(fetch_message)

    def mark_messages_read(self):
        """Mark displayed messages as read"""
        if not self.unread_messages:
            print("No messages to mark as read")
            return

        mark_read_message = ChatMessage(
            username=self.username,
            content="",
            message_type=MessageType.MARK_READ,
            message_ids=list(self.unread_messages),
        )
        if self.send_message(mark_read_message):
            self.unread_messages.clear()
            print("Messages marked as read")

    def delete_messages(self, message_ids: List[int]):
        """Delete specified messages"""
        delete_message = ChatMessage(
            username=self.username,
            content="",
            message_type=MessageType.DELETE,
            message_ids=message_ids,
        )
        if self.send_message(delete_message):
            print("Delete request sent")

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
                        # Track message ID for marking as read later
                        if response.data.message_id:
                            self.unread_messages.add(response.data.message_id)

                        # Handle different message types
                        if response.data.message_type == MessageType.CHAT:
                            print(f"{response.data.username}: {str(response.data)}")
                        elif response.data.message_type == MessageType.DM:
                            if response.data.username == self.username:
                                print(str(response.data))
                            else:
                                print(
                                    f"From {response.data.username}: {str(response.data)}"
                                )
                        elif response.data.message_type in [
                            MessageType.JOIN,
                            MessageType.LEAVE,
                        ]:
                            print(f"*** {response.data.content} ***")

                        # Show unread count if provided
                        if response.unread_count is not None:
                            print(f"({response.unread_count} more unread messages)")

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
    protocol = ProtocolFactory.create("json")
    client = ChatClient(username, protocol=protocol)
    try:
        client.run()
    except KeyboardInterrupt:
        pass  # Already handled in run()
    sys.exit(0)
