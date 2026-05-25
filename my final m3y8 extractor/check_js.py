import re, subprocess, os

with open(r'c:\Users\AC\Desktop\proxy server\streamvault.html','r',encoding='utf-8') as f:
    t = f.read()

# Match script tags WITH or without attributes for 'inline' content
m = re.findall(r'<script[^>]*>([\s\S]*?)</script>', t)
print('Total <script>: ', len(m))
for i, s in enumerate(m):
    print(i, 'len:', len(s), 'has-content:', len(s.strip())>0)

# extract the largest inline
inline = max(m, key=len)
with open(r'c:\Users\AC\Desktop\my final m3y8 extractor\extracted.js','w',encoding='utf-8') as f:
    f.write(inline)
print('wrote extracted.js, size=',len(inline))

# look for common issues
# 1) check that "appendALTabs" function syntax is OK
idx = inline.find('appendALTabs')
if idx >= 0:
    print('---appendALTabs context---')
    print(inline[idx:idx+800])
    print('---end---')
