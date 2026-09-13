#!/usr/bin/env python3
"""Capture l'écran de la machine virtuelle par le moniteur QEMU, sans visionneuse.

Attend que la socket réponde (au plus DELAI secondes), demande un `screendump`, et
convertit l'image en PNG. Sert à savoir si une installation avance ou si elle attend
une réponse que personne ne donnera.
"""
import os, socket, sys, time
from PIL import Image

ICI = os.path.dirname(os.path.abspath(__file__))
SOCK = os.path.join(ICI, "moniteur.sock")
SORTIE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ICI, "ecran.png")
DELAI = float(sys.argv[2]) if len(sys.argv) > 2 else 120
PPM = SORTIE + ".ppm"

fin = time.monotonic() + DELAI
while True:
    try:
        s = socket.socket(socket.AF_UNIX); s.connect(SOCK); break
    except OSError:
        if time.monotonic() > fin:
            sys.exit("moniteur injoignable : la machine virtuelle ne tourne pas")
        time.sleep(1)

s.settimeout(5)
def lire():
    tampon = b""
    try:
        while not tampon.endswith(b"(qemu) "):
            morceau = s.recv(4096)
            if not morceau: break
            tampon += morceau
    except socket.timeout:
        pass
    return tampon

lire()
s.sendall(f"screendump {PPM}\n".encode()); lire()
s.close()
for _ in range(20):
    if os.path.exists(PPM) and os.path.getsize(PPM) > 0: break
    time.sleep(0.5)
im = Image.open(PPM); im.save(SORTIE); os.remove(PPM)
print(f"{SORTIE}  {im.size[0]}x{im.size[1]}")
