import asyncio
import aiomysql
import aiosqlite
import aioredis
import aiofiles
import aiojobs

# async def operationaio(loop):
#     pool = await aiomysql.create_pool(host='127.0.0.1', port=3306,
#                                       user = 'root', password='020900',
#                                       db = 'test', loop=loop)
#     async with aiosqlite.connect()

async def redis():
    myredis = await aioredis.create_redis_pool('redis://localhost')
    await myredis.set('my-key', 'v')
    val = await myredis.get('my-key', encoding='utf-8')
    print(val)
    async with aiofiles.open('filename', mode='rw') as f:
        await f.write(val)
    myredis.close()
    await myredis.wait_closed()


if __name__ == '__main__':
    asyncio.run(redis())