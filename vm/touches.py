#!/usr/bin/env python3
"""Envoie une suite de touches à la machine virtuelle par le moniteur QEMU.

    ./touches.py tab ret clic:1036,716
"""
import socket, sys, time
s = socket.socket(socket.AF_UNIX); s.connect(__file__.rsplit("/",1)[0] + "/moniteur.sock"); s.settimeout(3)
def lire():
    t=b""
    try:
        while not t.endswith(b"(qemu) "): t += s.recv(4096)
    except socket.timeout: pass
lire()
for k in sys.argv[1:]:
    if k.startswith("clic:"):
        # Pointeur absolu (usb-tablet) : coordonnées en pixels de l'écran virtuel.
        x, y = k[5:].split(",")
        for c in (f"mouse_move {x} {y}", "mouse_button 1", "mouse_button 0"):
            s.sendall((c + "\n").encode()); lire(); time.sleep(0.2)
    else:
        s.sendall(f"sendkey {k}\n".encode()); lire()
    time.sleep(0.4)
s.close()
print("envoyé :", " ".join(sys.argv[1:]))
