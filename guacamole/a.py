import time
import asyncio
import socket


async def _connect():
    # _client_reader, _client_writer = await asyncio.open_connection(
    #     "127.0.0.1", 4822)
    reader, writer = await asyncio.open_connection("127.0.0.1", 4822)
    print(reader,2, writer,'测试')
    writer.write('6.select,3.vnc;'.encode())
    data = await reader.read(4096)
    print(data.decode(), "测试2")

#
# _client = socket.create_connection(("127.0.0.1", 4822), 15)
# print(_client.send('3.ack,1.1,2.OK,1.0;'.encode()),'ces')
# print(_client.recv(4096),'ces')
# time.sleep(1)
# print(_client.recv(4096),"ces")

loop = asyncio.get_event_loop()
try:
    loop.run_until_complete(_connect())
finally:
    loop.close()

