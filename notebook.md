# Design Exercise: Wire Protocols - Notebook

**Pranav Ramesh, Mohammmed Zidan Cassim**

## 02/07

### Update 5

Added user authentication functionality:

1. User Management:
   - Implemented secure user registration and login
   - Passwords are hashed using bcrypt before storage
   - Added new users table in SQLite database
   - Foreign key constraints ensure data integrity

2. Authentication Flow:
   - New message types: LOGIN, REGISTER, LOGOUT
   - Users must authenticate before accessing chat
   - Registration creates account, then prompts for login
   - Prevents multiple logins from same user

3. Security Features:
   - Password hashing with bcrypt for secure storage
   - Server-side validation of credentials
   - Protection against duplicate usernames
   - Session management to prevent multiple logins

4. User Experience:
   - Clear prompts for login/register choice
   - Immediate feedback on authentication status
   - Automatic notification of unread messages on login
   - Clean logout process with proper cleanup

5. Design Decisions:
   - Separate authentication from message handling
   - Stateful session management
   - Server-side enforcement of authentication
   - Database-backed persistent user storage

The system now provides secure user authentication while maintaining a smooth user experience.

### Update 4

Added message deletion functionality:

1. Message Identification:
   - Added visible message IDs to all messages
   - Updated message display to show IDs in format: [id] message
   - IDs are preserved across sessions via SQLite storage

2. Deletion Implementation:
   - New DELETE message type for deletion requests
   - Added `/delete id [id ...]` command to delete multiple messages
   - Messages can be deleted by either sender or recipient
   - Deletion is permanent and immediate

3. Security Considerations:
   - Users can only delete messages they sent or received
   - Database validates ownership before deletion
   - Server notifies user of successful deletion count

4. User Experience:
   - Clear command syntax with helpful usage messages
   - Immediate feedback on deletion success
   - Error handling for invalid message IDs
   - System notifications for deletion confirmation

5. Design Decisions:
   - Chose to show message IDs inline for easy reference
   - Allowed batch deletion for efficiency
   - Made deletion permanent (no soft delete) for simplicity
   - Limited deletion to participants only

The system now provides complete message lifecycle management: creation, delivery, reading, and deletion.

### Update 3

Fixed message delivery and read status tracking:

1. Message State Management:
   - Added proper tracking of message states (unread, delivered, read)
   - Messages have three distinct states:
     * Undelivered: Message stored but recipient hasn't received it
     * Delivered: Message successfully sent to recipient's client
     * Read: Recipient has explicitly marked the message as read

2. Delivery Status Implementation:
   - Messages are marked as delivered in two scenarios:
     * Immediately when sent to an online recipient
     * When successfully fetched by the recipient later
   - This prevents messages from appearing as "unread" if they were already seen

3. Database Optimizations:
   - Modified queries to consider both read_status and delivered flags
   - Added index on (recipient, read_status) for faster lookups
   - Ensures accurate unread message counts

4. Design Decisions:
   - Chose to separate "delivered" from "read" status:
     * Delivered = message reached client
     * Read = user explicitly acknowledged
   - This distinction allows for more accurate message tracking
   - Helps prevent duplicate message delivery
   - Provides better UX by showing accurate unread counts

5. Error Handling:
   - Added null checks for message IDs
   - Proper error handling for database operations
   - Graceful handling of disconnections

The system now properly handles the full lifecycle of messages, from sending to delivery to read status, providing a more reliable messaging experience.

### Update 2

The system now properly handles various edge cases:

- Client crashes or force-quits
- Network disconnections
- Server shutdowns
- Multiple clients chatting simultaneously
- Clean client removal and notification to other clients

Then, we extended the functionality to support direct messaging between users:

- Added username;message format for DMs
- Server routes DMs only to intended recipients
- Different display formats for sent vs received DMs
- Proper handling of invalid DM formats

Finally, we abstracted the wire protocol to support multiple implementations:

- Created a Protocol base class with serialize/deserialize methods
- Implemented JSONProtocol using newline-delimited messages
- Added CustomWireProtocol skeleton for future optimization
- Created ProtocolFactory for easy protocol switching
- Added proper message framing and buffering
- Made both client and server protocol-agnostic

The architecture is now ready for:

1. Implementing an efficient binary wire protocol
2. Easy switching between protocols for testing/comparison
3. Adding new protocol implementations without changing client/server code
4. Future extensions and optimizations

### Update 1

Just to start simple, we set up a universal chatroom with one server and multiple clients. The implementation uses:

- TCP sockets for reliable communication
- Threading to handle multiple concurrent clients
- Pydantic for message validation and serialization
- JSON for the wire protocol format

Key features implemented:

- Real-time message broadcasting to all connected clients
- Join/leave notifications
- Clean disconnection handling (both graceful exits and force quits)
- Thread-safe message broadcasting
- Proper cleanup of disconnected clients

## 02/04

We implemented basic chat/server + GUI. But then realized that my implementation makes the client poll for messages, while the whole point of sockets is for the server to distribute realtime updates to the clients. Will need to redesign this.
