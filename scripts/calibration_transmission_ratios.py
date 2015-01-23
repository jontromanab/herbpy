#!/usr/bin/env python
from __future__ import division
from __future__ import print_function
import herbpy
import prpy.planning
import openravepy
import math
import numpy
import serial
import struct
from enum import IntEnum

class Status(IntEnum):
    Success = 0x00
    InvalidCommand = 0x01
    Reserved = 0x03
    InvalidParameter = 0x04
    InvalidChecksum = 0x05
    FlashEraseError = 0x07
    FlashProgramError = 0x08


class Command(IntEnum):
    GetAllAngles = 0xE1
    SetOneDirection = 0xC4
    SetOneAngleOffset = 0xCF


class Direction(IntEnum):
    NORMAL = 0x00
    REVERSED = 0x01


class X3Inclinometer(object):
    """ Interface to the US Digital X3 Multi-Axis Absolute MEMS Inclinometer
    """
    def __init__(self, port, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.connection = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, type, value, traceback):
        self.disconnect()

    def connect(self):
        assert self.connection is None

        self.connection = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
        )

    def disconnect(self):
        assert self.connection is not None

        self.connection.close()

    def reset(self):
        self.connection.flushInput()
        self.connection.flushOutput()

    def get_all_angles(self, address=0x00):
        assert self.connection

        request = struct.pack('BB', address, Command.GetAllAngles.value)
        self.connection.write(request)

        response_binary = self.connection.read(15)
        self._checksum(response_binary)

        response = struct.unpack('>iiiHB', response_binary)
        angles = [ math.radians(angle / 1000) for angle in response[0:3] ]
        temperature = response[3] / 100

        return angles, temperature

    def set_one_direction(self, axis, direction, address=0):
        assert self.connection
        assert axis in [ 0, 1, 2 ]

        request = struct.pack('BBBB', address, Command.SetOneDirection.value, axis, direction.value)
        checksum = 256 - (self._sum_bytes(request) % 256)
        request += chr(checksum)

        self._checksum(request)
        self.connection.write(request)

        response_binary = self.connection.read(2)
        self._checksum(response_binary)

    def set_one_angle_offset(self, axis, offset, address=0):
        assert self.connection

        offset_raw = int(offset / 1000 + 0.5)
        assert axis in [ 0, 1, 2 ]
        assert -360000 <= offset_raw <= 359999

        request = struct.pack('>BBBi', address, Command.SetOneAngleOffset.value, axis, offset_raw)
        checksum = 256 - (self._sum_bytes(request) % 256)
        request += chr(checksum)

        self._checksum(request)
        self.connection.write(request)

        response_binary = self.connection.read(2)
        self._checksum(response_binary)

        response = struct.unpack('BB', response_binary)
        if response[0] != Status.Success.value:
            raise ValueError('Set failed: {:d}.'.format(response[0]))

    def _sum_bytes(self, data):
        return sum(ord(d) for d in data) 

    def _checksum(self, data):
        if not self._sum_bytes(data) % 256 == 0:
            raise ValueError('Checksum failed.')


def get_gravity_vector(angles):
    # FIXME: This is NOT the correct way to compute the gravity vector.
    return angles / numpy.linalg.norm(angles)

def calibrate(sensor, manipulator, nominal_config, padding=0.05, wait=1.):
    ActiveDOF = openravepy.Robot.SaveParameters.ActiveDOF

    with robot.CreateRobotStateSaver(ActiveDOF):
        robot.SetActiveDOFs(manipulator.GetArmIndices())
        min_limit, max_limit = robot.GetActiveDOFLimits()

        # TODO: This is a hack to avoid hitting the floor/head. We should
        # change the DOF limits outside this function.
        min_limit[1] = -0.5
        max_limit[1] =  0.5
        max_limit[3] =  2.7
        min_limit[5] = -1.4
        max_limit[5] =  1.4

        assert (max_limit - min_limit > padding).all()

        # We should read joint values from waminternals, not wamstate.

        for ijoint in xrange(manipulator.GetArmDOF()):
            print('J{:d}: Moving to nominal configuration'.format(ijoint + 1))
            robot.PlanToConfiguration(nominal_config)

            print('J{:d}: Moving to negative joint limit'.format(ijoint + 1))
            min_config = numpy.array(nominal_config)
            min_config[ijoint] = min_limit[ijoint] + padding
            robot.PlanToConfiguration(min_config)

            print('J{:d}: Collecting sample at negative joint limit'.format(ijoint + 1))
            time.sleep(wait)
            min_actual = robot.GetActiveDOFValues()[ijoint]
            min_measurement, _ = sensor.get_all_angles()
            min_gravity = get_gravity_vector(min_measurement)

            print('J{:d}: Moving to positive joint limit'.format(ijoint + 1))
            max_config = numpy.array(nominal_config)
            max_config[ijoint] = max_limit[ijoint] - padding
            robot.PlanToConfiguration(max_config)

            print('J{:d}: Collecting sample at positive joint limit'.format(ijoint + 1))
            time.sleep(wait)
            max_actual = robot.GetActiveDOFValues()[ijoint]
            max_measurement, _ = sensor.get_all_angles()
            max_gravity = get_gravity_vector(max_measurement)

            angle_actual = max_actual - min_actual
            angle_measurement = math.acos(numpy.dot(min_gravity, max_gravity))
            print('J{:d}: Predicted: {: 1.10f} radians'.format(ijoint + 1, angle_actual))
            print('J{:d}: Measured:  {: 1.10f} radians'.format(ijoint + 1, angle_measurement))


if __name__ == '__main__':
    env, robot = herbpy.initialize(sim=True, attach_viewer='interactivemarker')
    robot.planner = prpy.planning.SnapPlanner()

    nominal_config = [ math.pi, 0., 0., 0., 0., 0., 0. ]

    import time
    time.sleep(0.1)

    for link in robot.GetLinks():
        if link.GetName().startswith('/left'):
            link.Enable(False)
            link.SetVisible(False)

    robot.right_arm.hand.CloseHand()

    with X3Inclinometer(port='/dev/ttyUSB0') as sensor:
        # Reset the inclinometer by setting all offsets to zero and reverting
        # to the default sign on all axes.
        sensor.reset()

        for iaxis in range(3):
            sensor.set_one_angle_offset(iaxis, 0.)
            sensor.set_one_direction(iaxis, Direction.NORMAL)

        #calibrate(sensor, robot.right_arm, nominal_config)

        while True:
            angles, _ = sensor.get_all_angles()
            print('angles =', angles)
