"""
The MIT License (MIT)

Copyright (c)   2014 rescale
                2014 - 2016 Mohab Usama
"""

import asyncio
import logging

from guacamole import logger as guac_logger
from guacamole.exceptions import GuacamoleError, InvalidInstruction
from guacamole.instruction import GuacamoleInstruction as Instruction
from guacamole.instruction import INST_TERM

# supported protocols
PROTOCOLS = ('vnc', 'rdp', 'ssh')

PROTOCOL_NAME = 'guacamole'

BUF_LEN = 4096


class AsyncGuacamoleClient:
    """异步Guacamole Client class."""

    def __init__(self, host, port, timeout=20, debug=False, logger=None):
        """
        异步Guacamole客户端初始化。
        """
        self.host = host
        self.port = port
        self.timeout = timeout

        self._client_reader = None
        self._client_writer = None

        # handshake established?
        self.connected = False

        # Receiving buffer
        self._buffer = bytearray()

        # Client ID
        self._id = None

        self.logger = guac_logger
        if logger:
            self.logger = logger

        if debug:
            self.logger.setLevel(logging.DEBUG)

    async def _connect(self):
        """
        创建异步套接字连接到guacd服务器。
        """
        try:
            self._client_reader, self._client_writer = await asyncio.wait_for(asyncio.open_connection(
                self.host, self.port), timeout=self.timeout)
            self.logger.info('Client connected with guacd server (%s, %s, %s)'
                             % (self.host, self.port, self.timeout))
        except asyncio.TimeoutError:
            self.logger.info('Client connected with guacd server timeout (%s, %s, %s)'
                             % (self.host, self.port, self.timeout))
            self._client_reader, self._client_writer = None, None
            self.connected = False

    async def close(self):
        """
        终止与Guacamole guacd服务器的连接。
        """
        self._client_writer.close()
        await self._client_writer.wait_closed()
        self._client_reader = None
        self._client_writer = None
        self.connected = False
        self.logger.info('Connection closed.')

    async def _receive(self):
        """
        异步接收来自Guacamole guacd服务器的指令。
        """
        start = 0
        while True:
            idx = self._buffer.find(INST_TERM.encode(), start)
            if idx != -1:
                line = self._buffer[:idx + 1].decode()
                self._buffer = self._buffer[idx + 1:]
                self.logger.debug('Received instruction: %s' % line)
                return line
            else:
                start = len(self._buffer)
                buf = await self._client_reader.read(BUF_LEN)
                if not buf:
                    await self.close()
                    self.logger.warn(
                        'Failed to receive instruction. Closing.')
                    return None
                self._buffer.extend(buf)
            # timeout += 1

    async def send(self, data):
        """
        异步发送编码后的指令到Guacamole guacd服务器。
        """
        self.logger.debug('Sending data: %s' % data)
        # self.logger.info('发送数据: %s' % data)
        self._client_writer.write(data.encode())

    async def read_instruction(self):
        """
        异步读取并解码指令。
        """
        if not self._client_reader and not self._client_writer:
            await self._connect()  # 确保连接已建立
        try:
            raw_instruction = await self._receive()
            if not raw_instruction:
                return None
            instruction = Instruction.load(raw_instruction)
            return instruction
        except InvalidInstruction as e:
            self.logger.error(f"Failed to decode instruction: {e}")
            return None
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while reading instruction: {e}")
            return None

    async def send_instruction(self, instruction):
        """
        异步发送指令（已编码）。
        """
        if not self._client_reader and not self._client_writer:
            await self._connect()  # 确保连接已建立
        self.logger.debug('Sending instruction: %s' % str(instruction))
        await self.send(instruction.encode())

    async def handshake(self, protocol='vnc', width=1024, height=768, dpi=96,
                        audio=None, video=None, image=None, width_override=None,
                        height_override=None, dpi_override=None, **kwargs):
        """
        Establish connection with Guacamole guacd server via handshake.

        """
        if protocol not in PROTOCOLS and 'connectionid' not in kwargs:
            self.logger.error(
                'Invalid protocol: %s and no connectionid provided' % protocol)
            raise GuacamoleError('Cannot start Handshake. '
                                 'Missing protocol or connectionid.')

        if audio is None:
            audio = list()

        if video is None:
            video = list()

        if image is None:
            image = list()

        # 1. Send 'select' instruction
        self.logger.debug('Send `select` instruction.')

        # if connectionid is provided - connect to existing connectionid
        if 'connectionid' in kwargs:
            await self.send_instruction(Instruction('select',
                                                    kwargs.get('connectionid')))
        else:
            await self.send_instruction(Instruction('select', protocol))

        # 2. Receive `args` instruction
        instruction = await self.read_instruction()
        self.logger.debug('Expecting `args` instruction, received: %s'
                          % str(instruction))
        if not instruction:
            await self.close()
            raise GuacamoleError(
                'Cannot establish Handshake. Connection Lost!')

        if instruction.opcode != 'args':
            await self.close()
            raise GuacamoleError(
                'Cannot establish Handshake. Expected opcode `args`, '
                'received `%s` instead.' % instruction.opcode)

        # 3. Respond with size, audio & video support
        self.logger.debug('Send `size` instruction (%s, %s, %s)'
                          % (width, height, dpi))
        await self.send_instruction(Instruction('size', width, height, dpi))

        self.logger.debug('Send `audio` instruction (%s)' % audio)
        await self.send_instruction(Instruction('audio', *audio))

        self.logger.debug('Send `video` instruction (%s)' % video)
        await self.send_instruction(Instruction('video', *video))

        self.logger.debug('Send `image` instruction (%s)' % image)
        await self.send_instruction(Instruction('image', *image))

        if width_override:
            kwargs["width"] = width_override
        if height_override:
            kwargs["height"] = height_override
        if dpi_override:
            kwargs["dpi"] = dpi_override

        # 4. Send `connect` instruction with proper values
        connection_args = [
            kwargs.get(arg.replace('-', '_'), '') for arg in instruction.args
        ]

        self.logger.debug('Send `connect` instruction (%s)' % connection_args)
        await self.send_instruction(Instruction('connect', *connection_args))

        # 5. Receive ``ready`` instruction, with client ID.
        instruction = await self.read_instruction()
        self.logger.debug('Expecting `ready` instruction, received: %s'
                          % str(instruction))

        if instruction.opcode != 'ready':
            self.logger.warning(
                'Expected `ready` instruction, received: %s instead')

        if instruction.args:
            self._id = instruction.args[0]
            self.logger.debug(
                'Established connection with client id: %s' % self._id)

        self.logger.debug('Handshake completed.')
        self.connected = True
