# Design Exercise: Wire Protocols - Notebook

**Pranav Ramesh, Mohammmed Zidan Cassim**

## 02/04

**Pranav**

We implemented basic chat/server + GUI. But then realized that my implementation makes the client poll for messages, while the whole point of sockets is for the server to distribute realtime updates to the clients. Will need to redesign this.