# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2011, Martín Raúl Villalba
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#
##############################################################################
# pylint: disable=missing-docstring,invalid-name

import thread
import uuid

from ant.core.constants import (RESPONSE_NO_ERROR, EVENT_CHANNEL_CLOSED,
                                MESSAGE_CAPABILITIES)
from ant.core.exceptions import ChannelError, NodeError
from ant.core import message
from ant.core import event


class NetworkKey(object):
    def __init__(self, name=None, key='\x00' * 8):
        self.key = key
        if name:
            self.name = name
        else:
            self.name = str(uuid.uuid4())
        self.number = 0


class Channel(event.EventCallback):
    cb_lock = thread.allocate_lock()

    def __init__(self, node):
        self.node = node
        self.is_free = True
        self.name = str(uuid.uuid4())
        self.number = 0
        self.cb = []
        self.node.evm.registerCallback(self)

    def __del__(self):
        self.node.evm.removeCallback(self)

    def assign(self, net_key, ch_type):
        msg = message.ChannelAssignMessage(self.number, ch_type,
                                           self.node.getNetworkKey(net_key).number)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not assign channel.')
        self.is_free = False

    def setID(self, dev_type, dev_num, trans_type):
        msg = message.ChannelIDMessage(self.number, dev_num, dev_type, trans_type)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not set channel ID.')

    def setSearchTimeout(self, timeout):
        msg = message.ChannelSearchTimeoutMessage(self.number, timeout)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not set channel search timeout.')

    def setPeriod(self, counts):
        msg = message.ChannelPeriodMessage(self.number, counts)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not set channel period.')

    def setFrequency(self, frequency):
        msg = message.ChannelFrequencyMessage(self.number, frequency)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not set channel frequency.')

    def open(self):
        msg = message.ChannelOpenMessage(number=self.number)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not open channel.')

    def close(self):
        msg = message.ChannelCloseMessage(number=self.number)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not close channel.')

        while True:
            msg = self.node.evm.waitForMessage(message.ChannelEventMessage)
            if msg.messageCode == EVENT_CHANNEL_CLOSED:
                break

    def unassign(self):
        msg = message.ChannelUnassignMessage(number=self.number)
        node = self.node
        node.driver.write(msg.encode())
        if node.evm.waitForAck(msg) != RESPONSE_NO_ERROR:
            raise ChannelError('Could not unassign channel.')
        self.is_free = True

    def registerCallback(self, callback):
        with self.cb_lock:
            if callback not in self.cb:
                self.cb.append(callback)

    def process(self, msg):
        with self.cb_lock:
            if isinstance(msg, message.ChannelMessage) and \
               msg.channelNumber == self.number:
                for callback in self.cb:
                    try:
                        callback.process(msg)
                    except:
                        pass  # Who cares?


class Node(event.EventCallback):
    node_lock = thread.allocate_lock()

    def __init__(self, driver):
        self.driver = driver
        self.evm = event.EventMachine(self.driver)
        self.evm.registerCallback(self)
        self.networks = []
        self.channels = []
        self.running = False
        self.options = [0x00, 0x00, 0x00]

    def start(self):
        if self.running:
            raise NodeError('Could not start ANT node (already started).')

        if not self.driver.isOpen():
            self.driver.open()

        self.evm.start()
        self.reset()
        self.running = True
        self.init()

    def stop(self, reset=True):
        if not self.running:
            raise NodeError('Could not stop ANT node (not started).')

        if reset:
            self.reset()
        self.evm.stop()
        self.running = False
        self.driver.close()

    def reset(self):
        self.driver.write(message.SystemResetMessage().encode())
        self.evm.waitForMessage(message.StartupMessage)

    def init(self):
        if not self.running:
            raise NodeError('Could not reset ANT node (not started).')

        msg = message.ChannelRequestMessage(message_id=MESSAGE_CAPABILITIES)
        self.driver.write(msg.encode())

        caps = self.evm.waitForMessage(message.CapabilitiesMessage)

        self.networks = []
        for i in range(0, caps.getMaxNetworks()):
            self.networks.append(NetworkKey())
            self.setNetworkKey(i)
        self.channels = []
        for i in range(0, caps.getMaxChannels()):
            self.channels.append(Channel(self))
            self.channels[i].number = i
        self.options = (caps.getStdOptions(),
                        caps.getAdvOptions(),
                        caps.getAdvOptions2(),)

    def getCapabilities(self):
        return (len(self.channels), len(self.networks), self.options)

    def setNetworkKey(self, number, key=None):
        networks = self.networks
        if key is not None:
            networks[number] = key
        
        network = networks[number]
        msg = message.NetworkKeyMessage(number, network.key)
        self.driver.write(msg.encode())
        self.evm.waitForAck(msg)
        network.number = number

    def getNetworkKey(self, name):
        for netkey in self.networks:
            if netkey.name == name:
                return netkey
        raise NodeError('Could not find network key with the supplied name.')

    def getFreeChannel(self):
        for channel in self.channels:
            if channel.is_free:
                return channel
        raise NodeError('Could not find free channel.')

    def registerEventListener(self, callback):
        self.evm.registerCallback(callback)

    def process(self, msg):
        pass
