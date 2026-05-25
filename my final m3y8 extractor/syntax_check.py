import subprocess, sys
try:
    import esprima
except ImportError:
    print("Installing esprima...")
    subprocess.run([sys.executable,'-m','pip','install','esprima','-q'])
    import esprima

with open(r'c:\Users\AC\Desktop\my final m3y8 extractor\extracted.js','r',encoding='utf-8') as f:
    src = f.read()

try:
    esprima.parseScript(src, {'tolerant': False, 'loc': True})
    print("OK - no syntax errors")
except esprima.Error as e:
    print("SYNTAX ERROR:", e)
    print("Line:", getattr(e, 'lineNumber', '?'), "Col:", getattr(e, 'column','?'))
