import re, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("dashboard.py", "r", encoding="utf-8") as f:
    content = f.read()
    lines = content.splitlines()

for i, line in enumerate(lines):
    if line.strip().startswith("PAGES = ["):
        print("PAGES line %d" % (i+1))
        break

match = re.search(r"PAGES\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
if match:
    items = [x.strip().strip('"') for x in match.group(1).split(",") if x.strip()]
    print("PAGES count: %d" % len(items))
    print("Last item: %s" % items[-1].encode("ascii", "replace").decode())

print("Total lines: %d" % len(lines))
print("Last line (ascii): %s" % lines[-1].encode("ascii", "replace").decode())
