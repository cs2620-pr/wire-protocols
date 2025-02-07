# Design Exercise: Wire Protocols - Notebook

**Pranav Ramesh, Mohammmed Zidan Cassim**

## 02/07

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