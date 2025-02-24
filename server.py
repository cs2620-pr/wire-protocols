import grpc
from concurrent import futures
import protocol_pb2
import protocol_pb2_grpc
from database import Database

class ChatService(protocol_pb2_grpc.ChatServiceServicer):
    def __init__(self):
        self.db = Database()
        self.online_users = {}  # Tracks currently logged-in users

    def Register(self, request, context):
        """Handles account creation."""
        success = self.db.create_user(request.username, request.password)
        if success:
            return protocol_pb2.ServerResponse(status="success", message="Registration successful")
        return protocol_pb2.ServerResponse(status="error", message="Username already exists")

    def Login(self, request, context):
        """Handles user login and tracks online users."""
        valid = self.db.verify_user(request.username, request.password)
        if valid:
            unread_count = self.db.get_unread_count(request.username)
            self.online_users[request.username] = True  # Mark user as online
            return protocol_pb2.LoginResponse(
                status="success",
                message="Login successful",
                unread_messages=unread_count
            )
        return protocol_pb2.LoginResponse(status="error", message="Invalid credentials", unread_messages=0)

    def ListAccounts(self, request, context):
        """Lists accounts based on a wildcard pattern."""
        users = self.db.get_all_users(request.pattern)
        return protocol_pb2.UserList(usernames=users)

    def SendMessage(self, request, context):
        """Handles sending messages (instant delivery or store for later)."""
        msg_id = self.db.store_message(request)

        # Deliver instantly if recipient is online
        if request.recipient in self.online_users:
            return protocol_pb2.ServerResponse(status="success", message="Message delivered")
        return protocol_pb2.ServerResponse(status="success", message="Message stored for later")

    def FetchMessages(self, request, context):
        """Streams unread messages to the client."""
        messages = self.db.get_unread_messages(request.username, request.limit)
        for msg in messages:
            yield protocol_pb2.ChatResponse(
                sender=msg.username,
                recipient=msg.recipients[0],
                content=msg.content,
                timestamp=int(msg.timestamp.timestamp())
            )

    def MarkMessagesRead(self, request, context):
        """Marks specified messages as read."""
        self.db.mark_read(request.message_ids, request.username)
        return protocol_pb2.ServerResponse(status="success", message="Messages marked as read")

    def DeleteMessages(self, request, context):
        """Handles message deletion."""
        deleted_count, _ = self.db.delete_messages(request.message_ids, request.username, request.username)
        return protocol_pb2.ServerResponse(status="success", message=f"{deleted_count} messages deleted")

    def DeleteAccount(self, request, context):
        """Handles account deletion."""
        success = self.db.delete_user(request.username, request.password)
        if success:
            return protocol_pb2.ServerResponse(status="success", message="Account deleted")
        return protocol_pb2.ServerResponse(status="error", message="Account deletion failed")

    def Logout(self, request, context):
        """Handles user logout."""
        if request.username in self.online_users:
            del self.online_users[request.username]
        return protocol_pb2.ServerResponse(status="success", message="User logged out")

def serve():
    """Starts the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    protocol_pb2_grpc.add_ChatServiceServicer_to_server(ChatService(), server)
    server.add_insecure_port("[::]:50051")
    print("Server running on port 50051...")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
