import aiohttp
import asyncio
import pymysql
from aiohttp import web
import aiomysql
import asyncio

async def handle(request):
    name = request.match_info.get('name', "Anonymous")
    text = "Hello, " + name
    return web.Response(text = text)

# 1
# async def main():
#
#     async with aiohttp.ClientSession() as session:
#         async with session.get("http://www.baidu.com") as response:
#
#             print("Status:", response.status)
#             print("Content-type", response.headers['content-type'])
#
#             html = await response.text()
#             print("Body:", html[:15])

# 2
# app = web.Application()
# app.add_routes([web.get('/', handle),
#                 web.get('/{name}', handle)])

async def aiomysql_sample(loop):
    pool = await aiomysql.create_pool(host='127.0.0.1', port=3306,
                                      user = 'root', password='020900',
                                      db = 'test', loop=loop)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * from news;")
            print(cur.description)
            r = await cur.fetchone()
            print(r)
    pool.close()
    await pool.wait_closed()



if __name__ == '__main__':
    myconn = pymysql.connect(host='localhost', user = 'root', password = '020900', charset = 'utf8mb4')
    cursor = myconn.cursor()
    # sql_stmt = "CREATE database if not exists test;"
    # cursor.execute(sql_stmt)
    sql_stmt1 = "use test;"
    cursor.execute(sql_stmt1)
    # sql_stmt = '''drop table news'''
    # cursor.execute(sql_stmt)
    # sql_stmt2 = '''CREATE TABLE news(
    #     id INT ,
    #     topic INT ,
    #     PRIMARY KEY (id))
    #     '''
    # cursor.execute(sql_stmt2)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(aiomysql_sample(loop))
    # 2
    # web.run_app(app)