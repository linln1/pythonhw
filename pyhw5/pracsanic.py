from sanic.response import json
from sanic import response
from sanic import Sanic
import asyncio

app = Sanic(__name__)

@app.route("/")
async def nottest(request):
    return json({"hello" : "world"})

@app.route("/json")
async def post_json(request):
    return json({"received":True, "message":request.json})

@app.route("/query_string")
def query_string(request):
    return json({"parsed":True, "args":request.args, "url":request.url, "query_string":request.query_string})

# @app('/put_stream', stream=True)
# async def app_run_handler(request):
#     result = ''
#     while True:
#         body = await request.stream.read()
#         if body is None:
#             break
#         result += body.decode('utf-8').replace('1', 'A')
#
#     return response.text(result)

if __name__ == "__main__":
    app.run(host="localhost", port = 8000)

