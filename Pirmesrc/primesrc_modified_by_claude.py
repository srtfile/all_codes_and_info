import re
import cloudscraper
from Crypto.Cipher import AES
from urllib.parse import urlparse
from Crypto.Util.Padding import unpad

class Colors:
    okgreen = '\033[92m'
    okcyan = '\033[96m'
    warning = '\033[93m'
    endc = '\033[0m'


def safe_json(response, label=""):
    if not response.text.strip():
        raise ValueError(f"[{label}] Empty response. Status: {response.status_code}")
    try:
        return response.json()
    except Exception as e:
        raise ValueError(
            f"[{label}] Failed to parse JSON. Status: {response.status_code}\n"
            f"Body: {response.text[:500]}"
        ) from e


# ─── PASTE YOUR BROWSER COOKIES HERE ────────────────────────────────────────
CF_CLEARANCE = "paste_cf_clearance_value_here"
DDG1         = "paste___ddg1__value_here"       # may not always be present
# ─────────────────────────────────────────────────────────────────────────────

base_url      = 'https://primesrc.me/embed/movie?imdb=tt0114357'
user_agent    = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
aes_key       = b"kiemtienmua911ca"
aes_iv        = b"1234567890oiuytr"
default_domain = '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(base_url))

# Build scraper with real browser cookies
scraper = cloudscraper.create_scraper()
scraper.headers.update({
    'User-Agent'     : user_agent,
    'Referer'        : default_domain + '/',
    'Origin'         : default_domain,
    'Accept'         : 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
})
scraper.cookies.set('cf_clearance', CF_CLEARANCE, domain='primesrc.me')
scraper.cookies.set('__ddg1_',      DDG1,         domain='primesrc.me')

# Parse content type and ID
match = re.search(r'embed\/(.*?)\?\w+=(tt\d+)', base_url)
if not match:
    raise ValueError("Could not parse URL")
content_type = match.group(1)
content_id   = match.group(2)
print(f"Type: {content_type} | ID: {content_id}")

# Step 1: Get server list
url = f'{default_domain}/api/v1/s?imdb={content_id}&type={content_type}'
print(f"Servers: {url}")
servers = safe_json(scraper.get(url), "servers").get('servers', [])
if not servers:
    raise ValueError("No servers returned")
server_key = servers[0].get('key')
print(f"Server key: {server_key}")

# Step 2: Get server link
url = f'{default_domain}/api/v1/l?key={server_key}'
print(f"Server link: {url}")
server_url = safe_json(scraper.get(url), "server link").get('link')
if not server_url:
    raise ValueError("No link in response")
print(f"Server URL: {server_url}")

new_domain = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(server_url))
server_id  = server_url.split('#')[1]

# Update cookies/referer for new domain
scraper.headers.update({'Referer': new_domain})
scraper.cookies.set('cf_clearance', CF_CLEARANCE, domain=urlparse(server_url).netloc)

# Step 3: Get encrypted video info
url = f'{new_domain}api/v1/video?id={server_id}'
print(f"Video endpoint: {url}")
r = scraper.get(url)
hex_text = r.text.strip()
if not hex_text:
    raise ValueError(f"Empty video response. Status: {r.status_code}")
print(f"Encrypted length: {len(hex_text)}")

# Decrypt AES-CBC
cipher         = AES.new(aes_key, AES.MODE_CBC, aes_iv)
decrypted      = unpad(cipher.decrypt(bytes.fromhex(hex_text)), AES.block_size).decode('utf-8')
unescaped      = decrypted.replace('\\', '')

# Extract stream URL
match = re.search(r'"source":"(.*?)"', unescaped)
if not match:
    raise ValueError(f"No source found in: {unescaped[:300]}")
video_url = match.group(1)

# Output
print("\n" + "#" * 30)
print(f"Stream URL: {Colors.okgreen}{video_url}{Colors.endc}")
print("#" * 30)
print(f"{Colors.warning}Headers needed to play:{Colors.endc}")
print(f"  {Colors.okcyan}Referer:{Colors.endc}    {new_domain}")
print(f"  {Colors.okcyan}User-Agent:{Colors.endc} {user_agent}")