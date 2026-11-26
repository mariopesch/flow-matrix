"""
Minimal WebSocket server (RFC 6455, text messages only) using just the standard library.
Used for phone game controllers, which need low-latency messages in both directions.
Each connection runs in its own thread and is handed to  handler(conn).
"""
import base64
import hashlib
import select
import socket
import socketserver
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 64 * 1024


class Closed(Exception):
    pass


class Connection:
    def __init__(self, sock, addr):
        self.sock, self.addr = sock, addr
        self._send_lock = threading.Lock()
        self._parts = []

    # ------------------------------------------------------------ reading
    def _read(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise Closed()
            data += chunk
        return data

    def recv(self, timeout):
        """Next text message, or None if nothing arrived within `timeout` seconds.
        Raises Closed when the client disconnects."""
        while True:
            ready, _, _ = select.select([self.sock], [], [], timeout)
            if not ready:
                return None
            self.sock.settimeout(5)  # a frame has started: the rest must follow quickly
            try:
                b1, b2 = self._read(2)
                opcode, fin = b1 & 0x0F, b1 & 0x80
                length = b2 & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._read(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._read(8))[0]
                if length > MAX_MESSAGE or not b2 & 0x80:  # clients must mask their frames
                    raise Closed()
                mask = self._read(4)
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self._read(length)))
            except (OSError, ValueError):
                raise Closed()
            if opcode == 0x8:      # close
                self._send_frame(0x8, b"")
                raise Closed()
            if opcode == 0x9:      # ping
                self._send_frame(0xA, payload)
                continue
            if opcode in (0x1, 0x0):  # text, continuation
                self._parts.append(payload)
                if sum(len(p) for p in self._parts) > MAX_MESSAGE:
                    raise Closed()
                if fin:
                    msg, self._parts = b"".join(self._parts), []
                    return msg.decode("utf-8", "replace")
            # binary and pong frames are ignored
            timeout = 0

    # ------------------------------------------------------------ writing
    def _send_frame(self, opcode, payload):
        n = len(payload)
        if n < 126:
            header = struct.pack(">BB", 0x80 | opcode, n)
        elif n < 65536:
            header = struct.pack(">BBH", 0x80 | opcode, 126, n)
        else:
            header = struct.pack(">BBQ", 0x80 | opcode, 127, n)
        try:
            with self._send_lock:
                self.sock.sendall(header + payload)
        except OSError:
            raise Closed()

    def send(self, text):
        self._send_frame(0x1, text.encode("utf-8"))


def _handshake(sock):
    sock.settimeout(5)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk or len(data) > 16384:
            return False
        data += chunk
    lines = data.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    key = headers.get("sec-websocket-key")
    if "websocket" not in headers.get("upgrade", "").lower() or not key:
        sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return False
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
    return True


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host, port, handler):
    """Start the server in a background thread. handler(conn) is called per connection."""

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            sock = self.request
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                if not _handshake(sock):
                    return
            except OSError:
                return
            try:
                handler(Connection(sock, self.client_address))
            except Closed:
                pass

    server = _Server((host, port), Handler)
    threading.Thread(target=server.serve_forever, name="websocket", daemon=True).start()
    return server
