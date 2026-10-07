#!/usr/bin/env python3
import socket
import select
import threading
import json
import os
import fnmatch
import sys

# Dynamically resolve paths
REAL_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_DIR = os.environ.get("SANDBOX_CONFIG_DIR", REAL_DIR)
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
RULES_FILE = os.environ.get("SANDBOX_PROXY_RULES", os.path.join(RUNTIME_DIR, "sandbox_proxy_rules.json"))

GROUPINGS_FILE = os.path.join(CONFIG_DIR, "container_groupings.json")
if not os.path.exists(GROUPINGS_FILE):
    alt_groupings = os.path.join(CONFIG_DIR, "container_groupings.example.json")
    if os.path.exists(alt_groupings):
        GROUPINGS_FILE = alt_groupings

BIND_ADDRESS = os.environ.get("SANDBOX_PROXY_HOST", "0.0.0.0")
PORT = int(os.environ.get("SANDBOX_PROXY_PORT", 8888))

def load_rules():
    if not os.path.exists(RULES_FILE):
        return {}
    try:
        with open(RULES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def strip_container_name(name):
    if not name:
        return name
    if not os.path.exists(GROUPINGS_FILE):
        return name
    try:
        with open(GROUPINGS_FILE, "r") as f:
            groupings = json.load(f)
        grp_data = groupings.get("container_groupings", {})
        for grp, info in grp_data.items():
            containers = info.get("containers", [])
            if name in containers:
                return name
            
            naming = info.get("naming", {})
            prefix = naming.get("prefix", "")
            suffix = naming.get("suffix", "")
            
            cand = name
            if prefix and cand.startswith(prefix):
                cand = cand[len(prefix):]
            if suffix and cand.endswith(suffix):
                cand = cand[:-len(suffix)]
                
            if cand in containers:
                return cand
    except Exception:
        pass
    return name

def is_domain_allowed(client_ip, dest_host):
    rules = load_rules()
    allowed_entry = rules.get(client_ip)
    
    # If the IP is not registered in our proxy rules, block it by default
    if allowed_entry is None:
        return False
    
    allowed_domains = []
    allowed_containers = []
    if isinstance(allowed_entry, list):
        allowed_domains = allowed_entry
    elif isinstance(allowed_entry, dict):
        allowed_domains = allowed_entry.get("domains", [])
        allowed_containers = allowed_entry.get("containers", [])
    
    # Clean port if present in dest_host (e.g., github.com:443 -> github.com)
    host = dest_host.split(":")[0].lower()
    
    # Check if target is a known container
    container_ips = rules.get("container_ips", {})
    dest_container_system_name = None
    dest_container_logical_name = None
    
    # 1. Is host an IP that is in container_ips?
    if host in container_ips:
        dest_container_system_name = container_ips[host]
        dest_container_logical_name = strip_container_name(dest_container_system_name)
    else:
        # 2. Match host against container_ips names (either system name or logical name)
        for ip, name in container_ips.items():
            logical = strip_container_name(name)
            if name.lower() == host or logical.lower() == host:
                dest_container_system_name = name
                dest_container_logical_name = logical
                break
                
    if dest_container_system_name is not None:
        # Inter-container connection check
        for pattern in allowed_containers:
            pattern = pattern.lower()
            if pattern == "*":
                return True
            if fnmatch.fnmatch(dest_container_logical_name.lower(), pattern) or fnmatch.fnmatch(dest_container_system_name.lower(), pattern):
                return True
        return False
        
    # Standard external domain/IP check
    for pattern in allowed_domains:
        pattern = pattern.lower()
        if pattern == "*":
            return True
        # Support glob pattern matching (e.g., *.github.com or github.com)
        if fnmatch.fnmatch(host, pattern):
            return True
        # If wildcard pattern like *.github.com is defined, also allow bare github.com
        if pattern.startswith("*.") and host == pattern[2:]:
            return True
    return False

class ProxyConnection:
    def __init__(self, client_conn, client_addr):
        self.client_conn = client_conn
        self.client_ip = client_addr[0]
        self.buffer_size = 8192

    def handle(self):
        try:
            # Read initial request header
            request = self.client_conn.recv(self.buffer_size)
            if not request:
                self.client_conn.close()
                return
            
            # Parse request line
            first_line = request.decode('utf-8', errors='ignore').split('\n')[0]
            parts = first_line.split()
            if len(parts) < 3:
                self.client_conn.close()
                return
            
            method, path, version = parts[0], parts[1], parts[2]
            
            if method == 'CONNECT':
                # HTTPS Tunneling (CONNECT hostname:port HTTP/1.1)
                host_port = path
                if ':' in host_port:
                    host, port_str = host_port.split(':')
                    port = int(port_str)
                else:
                    host = host_port
                    port = 443
                
                if not is_domain_allowed(self.client_ip, host):
                    print(f"🔒 [Proxy] BLOCKED HTTPS access from {self.client_ip} to {host}")
                    self.client_conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\nProxy Blocked Destination\r\n")
                    self.client_conn.close()
                    return
                
                print(f"🔓 [Proxy] ALLOWED HTTPS access from {self.client_ip} to {host}:{port}")
                
                # Resolve host to container IP if it matches a known container name
                rules = load_rules()
                real_host = host
                container_ips = rules.get("container_ips", {})
                for ip, name in container_ips.items():
                    logical = strip_container_name(name)
                    if name.lower() == host.lower() or logical.lower() == host.lower():
                        real_host = ip
                        break
                
                # Connect to destination
                dest_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                dest_sock.settimeout(10.0)
                try:
                    dest_sock.connect((real_host, port))
                except Exception:
                    self.client_conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                    self.client_conn.close()
                    return
                
                # Acknowledge connection
                self.client_conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self.tunnel(self.client_conn, dest_sock)
            else:
                # Standard HTTP Request
                # Parse host from path or headers
                if path.startswith('http://') or path.startswith('https://'):
                    url_part = path.split('//', 1)[1]
                    host_part = url_part.split('/', 1)[0]
                else:
                    # Look for Host header in request
                    host_part = ""
                    for line in request.decode('utf-8', errors='ignore').split('\r\n'):
                        if line.lower().startswith('host:'):
                            host_part = line.split(':', 1)[1].strip()
                            break
                
                if ':' in host_part:
                    host, port_str = host_part.split(':')
                    port = int(port_str)
                else:
                    host = host_part
                    port = 80
                
                if not host:
                    self.client_conn.close()
                    return
                
                if not is_domain_allowed(self.client_ip, host):
                    print(f"🔒 [Proxy] BLOCKED HTTP access from {self.client_ip} to {host}")
                    self.client_conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Type: text/plain\r\n\r\nProxy Blocked Destination\r\n")
                    self.client_conn.close()
                    return
                
                print(f"🔓 [Proxy] ALLOWED HTTP access from {self.client_ip} to {host}:{port}")
                
                # Resolve host to container IP if it matches a known container name
                rules = load_rules()
                real_host = host
                container_ips = rules.get("container_ips", {})
                for ip, name in container_ips.items():
                    logical = strip_container_name(name)
                    if name.lower() == host.lower() or logical.lower() == host.lower():
                        real_host = ip
                        break
                
                # Forward the request
                dest_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                dest_sock.settimeout(10.0)
                try:
                    dest_sock.connect((real_host, port))
                    dest_sock.sendall(request)
                    self.tunnel(self.client_conn, dest_sock)
                except Exception:
                    self.client_conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                    self.client_conn.close()
                    return
        except Exception:
            pass
        finally:
            try:
                self.client_conn.close()
            except Exception:
                pass

    def tunnel(self, client_sock, dest_sock):
        socks = [client_sock, dest_sock]
        try:
            while True:
                r, w, x = select.select(socks, [], [], 30)
                if not r:
                    break  # Timeout after 30s idle
                for s in r:
                    data = s.recv(self.buffer_size)
                    if not data:
                        return
                    if s is client_sock:
                        dest_sock.sendall(data)
                    else:
                        client_sock.sendall(data)
        except Exception:
            pass
        finally:
            dest_sock.close()

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((BIND_ADDRESS, PORT))
    except Exception as e:
        print(f"❌ [Proxy] Failed to bind to {BIND_ADDRESS}:{PORT}: {e}", file=sys.stderr)
        sys.exit(1)
    
    server.listen(128)
    print(f"🛡️  [Proxy] Sandbox Filter Proxy listening on {BIND_ADDRESS}:{PORT}...")
    
    while True:
        try:
            conn, addr = server.accept()
            handler = ProxyConnection(conn, addr)
            t = threading.Thread(target=handler.handle, daemon=True)
            t.start()
        except KeyboardInterrupt:
            break
        except Exception:
            pass

if __name__ == "__main__":
    start_server()
