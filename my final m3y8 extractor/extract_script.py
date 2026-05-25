import re
with open(r'c:\Users\AC\Desktop\proxy server\streamvault.html','r',encoding='utf-8') as f:
    t = f.read()
scripts = re.findall(r'<script>([\s\S]*?)</script>', t)
print('scripts:', len(scripts))
# get the inline (non-src) ones
for i, s in enumerate(scripts):
    print(i, 'len:', len(s))
# write the big script to a file for analysis
inline = [s for s in scripts if len(s) > 1000]
if inline:
    with open(r'c:\Users\AC\Desktop\my final m3y8 extractor\extracted_script.js','w',encoding='utf-8') as f:
        f.write(inline[-1])
    print('wrote extracted_script.js')
