# import asyncio
#
# async def run(cmd):
#     proc = await asyncio.create_subprocess_shell(
#         cmd,
#         stdout=asyncio.subprocess.PIPE,
#         stderr=asyncio.subprocess.PIPE)
#
#     stdout, stderr = await proc.communicate()
#
#     print(f'[{cmd!r} exited with {proc.returncode}]')
#     if stdout:
#         print(f'[stdout]\n{stdout.decode()}')
#     if stderr:
#         print(f'[stderr]\n{stderr.decode()}')
#
# if __name__ == '__main__':
#     asyncio.run(run('ls /zzz'))
# import asyncio
#
# async def ns_lookup():
#     proc = await asyncio.create_subprocess_shell(
#         'nslookup', stdin=asyncio.subprocess.PIPE,
#         stdout=asyncio.subprocess.PIPE)
#
#     proc.stdin.write('www.bupt.edu.cn'.encode())
#     await proc.stdin.drain()
#
#     data = await proc.stdout.read()
#     data = data.decode()
#
#     await proc.wait()
#     return data
#
# if __name__ == '__main__':
#     data = asyncio.run(ns_lookup())
#     print(f"Result: {data}")

import asyncio
from aiohttp import web

async def init(loop):
    app = web.Application(loop=loop)
    app.router.add_route('GET', '/', index)
    app.router.add_route('GET', '/hello/{name}', hello)
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 8000)
    print('Server started at http://127.0.0.1:8000...')
    return srv

loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
