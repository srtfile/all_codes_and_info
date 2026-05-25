from playwright.sync_api import sync_playwright
from pathlib import Path

errors = []
console_msgs = []
network_failures = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    page.on('console', lambda msg: console_msgs.append(f"[{msg.type}] {msg.text}"))
    page.on('requestfailed', lambda req: network_failures.append(f"{req.url} - {req.failure}"))

    url = Path(r'c:\Users\AC\Desktop\proxy server\streamvault.html').as_uri()
    print('Navigating:', url)
    page.goto(url, wait_until='load', timeout=30000)

    # Give it some time to make API calls
    page.wait_for_timeout(8000)

    print('\n--- PAGE ERRORS ---')
    for e in errors:
        print(e)

    print('\n--- CONSOLE (last 30) ---')
    for m in console_msgs[-30:]:
        print(m)

    print('\n--- NETWORK FAILS ---')
    for f in network_failures[:30]:
        print(f)

    # Check what's in the trending row
    trending_html = page.evaluate("document.getElementById('trending-row').innerHTML.substring(0, 200)")
    print('\nTRENDING ROW HTML[0:200]:', trending_html)
    top10_html = page.evaluate("document.getElementById('top10').innerHTML.substring(0, 200)")
    print('\nTOP10 HTML[0:200]:', top10_html)
    
    browser.close()
