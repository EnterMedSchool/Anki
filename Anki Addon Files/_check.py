s=open('__init__.py','r',encoding='utf-8').read()
import sys
try:
    compile(s,'__init__.py','exec')
    print('OK')
except SyntaxError as e:
    print('SYNTAX',e.lineno, e.offset, e.msg)
    import traceback; traceback.print_exc()
    raise

