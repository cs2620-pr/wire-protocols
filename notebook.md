# Design Exercise: Wire Protocols - Notebook

**Pranav Ramesh, Mohammmed Zidan Cassim**

## 02/10

### Update 2

Type Safety and Null State Handling Improvements:

1. Enhanced Type Safety:
   - Added proper type hints to critical class attributes:
     ```python
     self.client: ChatClient | None = None
     self.receive_thread: ReceiveThread | None = None
     self.system_message_display: QTextEdit | None = None
     ```
   - Improved IDE support and static type checking
   - Makes code more maintainable and helps catch type-related bugs early

2. Null State Protection:
   - Added null checks before accessing potentially uninitialized objects:
     ```python
     if not self.client:
         return
     ```
   - Protected key methods:
     * `display_message`
     * `update_user_list`
     * `load_chat_history`
     * `handle_message`
   - Ensures graceful handling of edge cases during initialization and cleanup

3. System Message Display Safety:
   - Added checks before accessing system message display:
     ```python
     if self.system_message_display:
         self.system_message_display.clear()
     ```
   - Prevents null pointer exceptions during:
     * Message display
     * Display clearing
     * System notifications
   - Maintains UI stability during state transitions

4. Implementation Details:
   - Command Line Arguments:
     * Host (default: "localhost")
     * Port (default: 8000)
     * Protocol (default: "json", choices: ["json", "custom"])
   - Type-safe initialization:
     ```python
     def __init__(
         self,
         host: str = "localhost",
         port: int = 8000,
         protocol: str = "json"
     )
     ```
   - Proper state management during:
     * Connection setup
     * Message handling
     * UI updates
     * Cleanup

5. Benefits:
   - Improved code reliability
   - Better error prevention
   - Enhanced maintainability
   - Clearer code intent
   - Better development experience with IDE support

These changes make the application more robust by properly handling null states and providing better type safety, reducing the likelihood of runtime errors and improving the overall code quality.

### Update 1

GUI Improvements and System Message Refinements:

1. System Message Display Consistency:
   - Problem: System message display and user list had inconsistent widths
   - Solution:
     * Added consistent width management using a shared `right_panel_width` variable
     * Set both user list and system message display to the same width (200px)
     * Improved visual alignment and UI consistency
   - Technical Details:
     ```python
     right_panel_width = 200
     self.user_list.setMaximumWidth(right_panel_width)
     self.system_message_display.setMaximumWidth(right_panel_width)
     ```

2. System Message Content Updates:
   - Problem: System messages still referenced CLI commands (e.g., "/fetch [n]") that weren't applicable to GUI
   - Changes Made:
     * Updated `UNREAD_MESSAGES` system message in `schemas.py`
     * Old message: "You have {} unread messages. Use /fetch [n] to retrieve them."
     * New message: "You have {} unread messages"
   - Rationale:
     * GUI handles message fetching automatically
     * No need for manual fetch commands
     * Cleaner, more appropriate messaging for GUI context

3. Implementation Considerations:
   - Layout Management:
     * Used QVBoxLayout for consistent vertical stacking
     * Maintained proper spacing and alignment
     * Ensured scalability for different window sizes
   - Visual Hierarchy:
     * Clear separation between user list and system messages
     * Consistent styling for better readability
     * Proper use of Qt's layout system for reliable rendering

4. Potential Issues Addressed:
   - Width Consistency:
     * Previous implementation had potential for misaligned widths
     * Could cause visual inconsistency on different platforms
     * Fixed by using a shared width constant
   - Message Clarity:
     * Old CLI-style messages could confuse GUI users
     * Removed references to command-line operations
     * Made system messages more intuitive for GUI interaction

5. Future Considerations:
   - Dynamic Sizing:
     * Could add responsive width adjustment based on window size
     * Potential for user-customizable panel widths
   - Theme Integration:
     * System message display follows main theme
     * Could add more sophisticated styling options
   - Message Management:
     * Might need message truncation for long system messages
     * Could add message history scrolling
     * Potential for message filtering or categorization

These changes improve the overall user experience by making the interface more consistent and removing confusing references to command-line operations that aren't relevant in the GUI context. 

## 02/09

### Update 1

Fixed issues with unread message counts and message deletion functionality:

1. Unread Count Issues:
   - Problem: Unread count was always showing 0 and read_status was never being set to true
   - Root Cause: Messages weren't being marked as read when viewed in chat window
   - Solution:
     * Added mark_read_message call in load_chat_history
     * Implemented mark_read_from_user in database to mark all messages from a user as read
     * Enhanced server's handle_mark_read to support both specific messages and all messages from a user
     * Added proper unread count tracking and notification system

2. Message Deletion Improvements:
   - Problem: Users could accidentally delete messages from other conversations
   - Changes Made:
     * Modified delete_messages in database to require both sender and recipient
     * Updated SQL queries to check both sender and recipient using AND conditions
     * Enhanced client code to include current chat recipient in delete requests
     * Improved server-side validation of message ownership
   - Security Benefits:
     * Messages can only be deleted from the specific conversation they belong to
     * Both sender and recipient are verified before deletion
     * Prevents accidental deletion across conversations

3. Technical Challenges:
   - Database Schema:
     * Had to carefully modify SQL queries to maintain data integrity
     * Needed to handle both sender->recipient and recipient->sender message patterns
   - Concurrency:
     * Ensuring thread-safe updates to unread counts
     * Managing simultaneous delete operations
   - State Management:
     * Tracking unread counts across multiple chat windows
     * Maintaining consistency between client and server state

4. Implementation Details:
   - Client Changes:
     * Added mark_read_message in load_chat_history:
       ```python
       mark_read_message = ChatMessage(
           username=self.client.username,
           content="",
           message_type=MessageType.MARK_READ,
           recipients=[username],
       )
       ```
     * Enhanced delete_messages to include recipient:
       ```python
       delete_message = ChatMessage(
           username=self.username,
           content="",
           message_type=MessageType.DELETE,
           message_ids=message_ids,
           recipients=[recipient],
       )
       ```

   - Server Changes:
     * Added mark_read_from_user support:
       ```python
       def handle_mark_read(self, message: ChatMessage) -> None:
           if message.recipients:
               self.db.mark_read_from_user(message.username, message.recipients[0])
           elif message.message_ids:
               self.db.mark_read(message.message_ids, message.username)
       ```
     * Enhanced delete message handling:
       ```python
       def handle_delete_messages(self, message: ChatMessage) -> None:
           if message.message_ids and message.recipients:
               deleted_count, deleted_info = self.db.delete_messages(
                   message.message_ids, message.username, message.recipients[0]
               )
       ```

   - Database Changes:
     * Modified delete_messages query:
       ```sql
       DELETE FROM messages 
       WHERE id IN ({}) AND (
           (sender = ? AND recipient = ?) OR
           (sender = ? AND recipient = ?)
       )
       ```
     * Added mark_read_from_user method:
       ```sql
       UPDATE messages 
       SET read_status = TRUE 
       WHERE sender = ? AND recipient = ? AND read_status = FALSE
       ```

5. User Experience Improvements:
   - Real-time unread count updates in user list
   - Clear visual feedback when messages are marked as read
   - Proper error handling for invalid delete attempts
   - Consistent behavior across multiple chat windows

6. Remaining Considerations:
   - Performance optimization for large message histories
   - Potential for batch operations to reduce database load
   - Additional error handling for edge cases
   - Future enhancements to message status tracking

These changes have significantly improved the reliability and security of the chat system, particularly in handling unread messages and message deletion.

## 02/08

### Update 1

Enhanced the GUI client's user experience and fixed user status synchronization:

1. User Interface Improvements:
   - Added username display in window title bar (e.g., "Chat Client - Alice")
   - Title bar updates dynamically on login/logout
   - Provides clear visual indication of which account is active
   - Helpful for users running multiple chat windows

2. User Status Synchronization:
   - Fixed issue where user statuses weren't properly synchronized
   - Improved active user list management in the GUI
   - Maintains accurate active/inactive status across all clients
   - Properly handles JOIN/LEAVE message updates

3. Design Decisions:
   - Used window title for username display to avoid cluttering the main interface
   - Implemented proper state management for user status tracking
   - Maintained existing active users when new users join
   - Ensured consistent status display across all connected clients

4. Technical Implementation:
   - Enhanced `handle_server_message` to properly track active users
   - Added current user status preservation during updates
   - Improved user list synchronization logic
   - Clean title bar management during login/logout cycles

5. User Experience Benefits:
   - Clear indication of current logged-in user
   - Accurate representation of all users' statuses
   - Consistent behavior across multiple client windows
   - Improved overall usability and user feedback

These changes have made the chat client more user-friendly and reliable, particularly when multiple users are active simultaneously.

## 02/07

### Update 6

Migrated to a PyQt5-based GUI client:

1. Architecture Changes:
   - Separated network operations into NetworkManager class
   - Implemented threaded message receiving with QThread
   - Moved from CLI to event-driven GUI architecture
   - Connection lifecycle now tied to window lifecycle

2. User Interface:
   - Two-window system: Login/Register and Main Chat
   - Split-view chat interface with user list and chat area
   - Real-time user status indicators (active/inactive)
   - Message operations integrated into GUI (fetch, read, delete)
   - Visual feedback for all operations

3. Authentication Flow:
   - Dedicated login/register window
   - Connection established at window creation
   - Proper session handling with GUI state updates
   - Clean connection termination on window close

4. Message Management:
   - Visual message threading by conversation
   - Integrated message deletion with UI updates
   - Real-time updates for both participants
   - Improved message status visibility

5. Design Decisions:
   - Qt signals/slots for thread-safe communication
   - Separate network thread for responsive UI
   - Connection management tied to window lifecycle
   - Consistent visual feedback for all operations

The system now provides a modern, user-friendly interface while maintaining all existing functionality.

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
