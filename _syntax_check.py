import ast, sys
with open(r'C:\Users\Lenovo\psx_pipeline\dashboard.py', 'r', encoding='utf-8') as f:
    source = f.read()
try:
    ast.parse(source)
    print('SYNTAX OK')
except SyntaxError as e:
    print(f'SYNTAX ERROR: {e}')
    sys.exit(1)
