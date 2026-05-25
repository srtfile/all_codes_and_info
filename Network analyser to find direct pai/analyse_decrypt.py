"""
analyse_decrypt.py  —  Extract full decrypt logic from 1386 chunk
"""
import re

with open(r'c:\Users\AC\Desktop\Network analyser to find direct pai\js_full_1386.js',
          encoding='utf-8', errors='ignore') as f:
    js = f.read()

# Find module 91712 — the decryptData module
idx = js.find('91712:')
if idx != -1:
    snippet = js[idx:idx+3000]
    print("=== MODULE 91712 (decryptData) ===")
    print(snippet)
    print()

# Find the full decrypt function with aes-256-gcm
idx2 = js.find('aes-256-gcm')
if idx2 != -1:
    snippet2 = js[max(0,idx2-500):idx2+2000]
    print("=== AES-256-GCM CONTEXT ===")
    print(snippet2)
    print()

# Find the encrypted/cin/mao structure
idx3 = js.find('encrypted:d,cin:m,mao:u')
if idx3 == -1:
    idx3 = js.find('encrypted:d,cin')
if idx3 != -1:
    snippet3 = js[max(0,idx3-1000):idx3+2000]
    print("=== ENCRYPTED/CIN/MAO STRUCTURE ===")
    print(snippet3)
    print()

# Find the key derivation: createHash sha256
idx4 = js.find('createHash("sha256")')
if idx4 != -1:
    snippet4 = js[max(0,idx4-500):idx4+1000]
    print("=== KEY DERIVATION (sha256) ===")
    print(snippet4)
    print()

# Find the _rk hardcoded value
idx5 = js.find('2549b22d9bf0d91847a2811baac98d0079e02dba592aea94')
if idx5 != -1:
    snippet5 = js[max(0,idx5-300):idx5+500]
    print("=== _rk HARDCODED VALUE CONTEXT ===")
    print(snippet5)
    print()

# Find the secret param construction
idx6 = js.find('"secret"')
while idx6 != -1:
    snippet6 = js[max(0,idx6-200):idx6+400]
    if 'append' in snippet6 or 'param' in snippet6.lower() or 'hash' in snippet6.lower():
        print("=== SECRET PARAM CONSTRUCTION ===")
        print(snippet6)
        print()
    idx6 = js.find('"secret"', idx6+1)
    if idx6 > 50000:
        break

# Find the hardcoded keys in 1386
print("=== HARDCODED 64-CHAR HEX STRINGS IN 1386 ===")
for m in re.findall(r'["\']([0-9a-fA-F]{64})["\']', js):
    print(f"  {m}")
