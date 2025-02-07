# Design Exercise: Wire Protocols - Notebook

**Pranav Ramesh, Mohammmed Zidan Cassim**

## 02/07

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

The system now properly handles various edge cases:

- Client crashes or force-quits
- Network disconnections
- Server shutdowns
- Multiple clients chatting simultaneously
- Clean client removal and notification to other clients

## 02/04

We implemented basic chat/server + GUI. But then realized that my implementation makes the client poll for messages, while the whole point of sockets is for the server to distribute realtime updates to the clients. Will need to redesign this.