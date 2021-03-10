#!/usr/bin/env python

# Python (Euro)DOCSIS Traffic Meter
# Copyright (C) 2018 the contributors

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import collections
import ctypes
import fcntl
import logging
import os
import select
import socket
import time
import datetime
import timeit
import json
from influxdb import InfluxDBClient

# init logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
LOGGER = logging.getLogger(__name__)

# DVB constants from Linux kernel files
DMX_IMMEDIATE_START = 0x4
DMX_IN_FRONTEND = 0x0
DMX_OUT_TS_TAP = 0x2
DMX_PES_OTHER = 0x14
DMX_SET_BUFFER_SIZE = 0x6F2D  # ioctl
DMX_SET_PES_FILTER = 0x40146F2C  # ioctl
DMX_STOP = 0x6F2A
DTV_DELIVERY_SYSTEM = 0x11
DTV_FREQUENCY = 0x3
DTV_INNER_FEC = 0x9
DTV_INVERSION = 0x6
DTV_MODULATION = 0x4
DTV_SYMBOL_RATE = 0x8
DTV_TUNE = 0x1
FEC_AUTO = 0x9
FE_READ_STATUS = -0x7FFB90BB  # ioctl
FE_SET_PROPERTY = 0x40086F52  # ioctl
INVERSION_OFF = 0x0
QAM_256 = 0x5
QAM_64 = 0x3
SYS_DVBC_ANNEX_AC = 0x1

# mappings for DVB API data types - this code was copied
# more or less verbatim from: https://pypi.org/project/linuxdvb/
class dtv_property(ctypes.Structure):
    class _u(ctypes.Union):
        class _s(ctypes.Structure):
            _fields_ = [
                ("data", ctypes.c_uint8 * 32),
                ("len", ctypes.c_uint32),
                ("reserved1", ctypes.c_uint32 * 3),
                ("reserved2", ctypes.c_void_p),
            ]

        _fields_ = [("data", ctypes.c_uint32), ("buffer", _s)]

    _fields_ = [
        ("cmd", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
        ("u", _u),
        ("result", ctypes.c_int),
    ]
    _pack_ = True


class dtv_properties(ctypes.Structure):
    _fields_ = [("num", ctypes.c_uint32), ("props", ctypes.POINTER(dtv_property))]


class dvb_qam_parameters(ctypes.Structure):
    _fields_ = [
        ("symbol_rate", ctypes.c_uint32),
        ("fec_inner", ctypes.c_uint),
        ("modulation", ctypes.c_uint),
    ]


class dvb_frontend_parameters(ctypes.Structure):
    class _u(ctypes.Union):
        _fields_ = [("qam", dvb_qam_parameters)]

    _fields_ = [("frequency", ctypes.c_uint32), ("inversion", ctypes.c_uint), ("u", _u)]


class dvb_frontend_status(ctypes.Structure):
    _fields_ = [("status", ctypes.c_uint)]


class dmx_pes_filter_params(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint16),
        ("input", ctypes.c_uint),
        ("output", ctypes.c_uint),
        ("pes_type", ctypes.c_uint),
        ("flags", ctypes.c_uint32),
    ]


# end code copied from https://pypi.org/project/linuxdvb/

# since (Euro)DOCSIS 3.0 defines a lot of parameters already, when tuning, we are only interested
# in setting a frequency and a modulation
Tunable = collections.namedtuple("Tunable", ["frequency", "modulation"])


def parse_arguments():
    """This function parses the command line arguments and return them."""
    # create comand line parser
    parser = argparse.ArgumentParser(
        description="pydtm - measure EuroDOCSIS 3.0 data rate",
        epilog="Note: By default, each frequency is scanned for step/num(frequencies) seconds. "
        "All parameters can also be passed as environment variables, e.g. PYDTM_ADAPTER, "
        "PYDTM_INFLUXDB_HOST, PYDTM_INFLUXDB_PORT, PYDTM_INFLUXDB_USERNAME, PYDTM_INFLUXDB_PASSWORD, "
        "PYDTM_INFLUXDB_DATABASE, PYDTM_DEBUG, PYDTM_INTERVAL, PYDTM_FREQUENCIES, PYDTM_STEP, PYTDM_TUNER and "
        "PYDTM_LOCKTIME"
    )
    # add arguments
    parser.add_argument(
        "-a",
        "--adapter",
        type=int,
        default=0,
        help="use /dev/dvb/adapterN devices (default: 0)",
    )
    parser.add_argument(
        "-ih",
        "--influx-host",
        type=str,
        default="localhost",
        help="address of influxdb (default: localhost)",
    )
    parser.add_argument(
        "-ihp",
        "--influx-port",
        type=str,
        default="8086",
        help="port of influxdb (default: 8086)",
    )
    parser.add_argument(
        "-iu",
        "--influx-username",
        type=str,
        default="influx",
        help="username for influxdb (default: influx)",
    )
    parser.add_argument(
        "-ip",
        "--influx-password",
        type=str,
        default="",
        help="password for influxdb (default: empty)",
    )
    parser.add_argument(
        "-id",
        "--influx-database",
        type=str,
        default="pydtm",
        help="database name for influxdb (default: pydtm)",
    )
    parser.add_argument(
        "-d",
        "--debug",
        type=bool,
        default=False,
        help="enable debug logging (default: not enabled)",
    )
    parser.add_argument(
        "-f",
        "--frequencies",
        type=str,
        default="114:256",  # this is a completely arbitrary value
        help=(
            "a list of 'frequency' or 'frequency:modulation'" "pairs (default: 114:256)"
        ),
    )
    parser.add_argument(
        "-s",
        "--step",
        type=int,
        default="60",
        help="metrics backend default resolution in seconds (default: 60)",
    )
    parser.add_argument(
        "-t",
        "--tuner",
        type=int,
        default=0,
        help="use adapter's frontendN/dmxN/dvrN devices (default: 0)",
    )
    parser.add_argument(
        "-lt",
        "--locktime",
        type=int,
        default=1,
        help="locktime for frontend in sec. (default: 1)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=300,
        help="amount of seconds to wait between each scan cycle. (default: 300)",
    )

    # return parsed arguments
    return parser.parse_args()


def set_from_env(envvar, default):
    """If envar is set, return it, else default"""
    if envvar in os.environ:
        return os.environ[envvar]
    return default


def eval_envvars(args):
    """Parse environment variables if present."""
    # overwrite with environment values
    try:
        args.adapter = int(set_from_env("PYDTM_ADAPTER", args.adapter))
    except ValueError:
        LOGGER.error(
            "error parsing PYDTM_ADAPTER value %s as integer, using %d instead",
            os.environ["PYDTM_ADAPTER"],
            args.adapter,
        )
    args.influx_host = set_from_env("PYDTM_INFLUXDB_HOST", args.influx_host)
    args.influx_port = set_from_env("PYDTM_INFLUXDB_PORT", args.influx_port)
    args.influx_username = set_from_env("PYDTM_INFLUXDB_USERNAME", args.influx_username)
    args.influx_password = set_from_env("PYDTM_INFLUXDB_PASSWORD", args.influx_password)
    args.influx_database = set_from_env("PYDTM_INFLUXDB_DATABASE", args.influx_database)
    try:
        args.locktime = int(set_from_env("PYDTM_LOCKTIME", args.locktime))
    except ValueError:
        LOGGER.error(
            "error parsing PYDTM_LOCKTIME value %s as integer, using %d instead",
            os.environ["PYDTM_LOCKTIME"],
            args.locktime,
        )
    if "PYDTM_DEBUG" in os.environ:
        args.debug = True
    args.frequencies = set_from_env("PYDTM_FREQUENCIES", args.frequencies)
    try:
        args.step = int(set_from_env("PYDTM_STEP", args.step))
    except ValueError:
        LOGGER.error(
            "error parsing PYDTM_STEP value %s as integer, using %d instead",
            os.environ["PYDTM_STEP"],
            args.step,
        )
    try:
        args.tuner = int(set_from_env("PYDTM_TUNER", args.tuner))
    except ValueError:
        LOGGER.error(
            "error parsing PYDTM_TUNER value %s as integer, using %d instead",
            os.environ["PYDTM_TUNER"],
            args.tuner,
        )
    try:
        args.interval = int(set_from_env("PYDTM_INTERVAL", args.interval))
    except ValueError:
        LOGGER.error(
            "error parsing PYDTM_INTERVAL value %s as integer, using %d instead",
            os.environ["PYDTM_INTERVAL"],
            args.step,
        )


def frequency_list(frequencies):
    """parse frequency list from arguments"""
    # generate a list of frequencies
    f_list = []
    for freq in frequencies.split(","):
        mod = "256"
        if freq.find(":") > 0:
            freq, mod = freq.split(":")

        # try to parse frequency
        try:
            freq = int(freq)
        except ValueError:
            LOGGER.critical("error parsing frequency %s as integer, aborting", freq)
            exit(1)

        # generate list of tunable frequency/modulation combinations, translate human readable
        # modulation to DVB API
        if mod == "256":
            f_list.append(Tunable(freq, QAM_256))
        elif mod == "64":
            f_list.append(Tunable(freq, QAM_64))
        else:
            LOGGER.critical("invalid modulation QAM_%s detected, aborting", mod)
            exit(1)
    return f_list


def build_configuration():
    """Build basic configuration."""
    # parse command line arguments first, then evaluate environment
    args = parse_arguments()
    eval_envvars(args)

    # parse frequency list
    frequencies = frequency_list(args.frequencies)

    # show all settings
    LOGGER.info("Current settings:")
    for key, value in vars(args).items():
        if key.find("password") != -1:
            value = "*************"
        LOGGER.info("  %s=%s", key, value)

    # make sure we got at least one second per frequency
    if args.step / len(frequencies) < 1:
        LOGGER.warning(
            "A step of %d seconds with %d different frequencies will result in less "
            "than one second of scan time per frequency, which is not supported.",
            args.step,
            len(frequencies),
        )

    return args


def tune(fefd, tunable, locktime, num, total):
    """tune to given frequency"""
    LOGGER.debug(
        "%d/%d: tuning to frequency %dMHz with modulation %d",
        num, 
        total,
        tunable.frequency,
        tunable.modulation,
    )
    # we are about to issue 7 commands to the DVB frontend
    proptype = dtv_property * 7
    prop = proptype()
    # set delivery system to DVB-C
    prop[0].cmd = DTV_DELIVERY_SYSTEM
    prop[0].u.data = SYS_DVBC_ANNEX_AC
    # set modulation
    # TODO: support QAM_AUTO?
    prop[1].cmd = DTV_MODULATION
    prop[1].u.data = tunable.modulation
    # set EuroDOCSIS symbol rate
    prop[2].cmd = DTV_SYMBOL_RATE
    prop[2].u.data = 6952000
    # DOCSIS profiles always set frequency inversion to off
    prop[3].cmd = DTV_INVERSION
    prop[3].u.data = INVERSION_OFF
    # autodetect Forward Error Correction
    prop[4].cmd = DTV_INNER_FEC
    prop[4].u.data = FEC_AUTO
    # set frequency
    prop[5].cmd = DTV_FREQUENCY
    prop[5].u.data = tunable.frequency * 1000000
    # tell the kernel to actually tune into the given frequency
    prop[6].cmd = DTV_TUNE
    dtv_props = dtv_properties()
    dtv_props.num = 7
    dtv_props.props = ctypes.pointer(prop[0])
    if fcntl.ioctl(fefd, FE_SET_PROPERTY, dtv_props) == 0:
        # determine wheter the frontend actually has a lock
        # FIXME: why do I need this?
        time.sleep(locktime)
        # make sure the FE has a lock
        festatus = dvb_frontend_status()
        if fcntl.ioctl(fefd, FE_READ_STATUS, festatus) == 0:
            if (festatus.status & 0x10) == 0:
                LOGGER.error("  frontend has no lock")
                return -1
        else:
            LOGGER.error("  FE_READ_STATUS failed, unable to verify signal lock")
            return -1
    else:
        LOGGER.error("  FE_SET_PROPERTY failed, unable to tune")
        return -1
    LOGGER.debug("  tuning successful")
    return 0


def start_demuxer(dmxfd):
    """start demuxer"""
    # DOCSIS uses the MPEG-TS Packet Identifier 8190
    # tell the demuxer to get us the transport stream
    LOGGER.debug("  starting demuxer")
    pesfilter = dmx_pes_filter_params()
    pesfilter.pid = 8190
    pesfilter.input = DMX_IN_FRONTEND
    pesfilter.output = DMX_OUT_TS_TAP
    pesfilter.pes_type = DMX_PES_OTHER
    pesfilter.flags = DMX_IMMEDIATE_START
    if fcntl.ioctl(dmxfd, DMX_SET_PES_FILTER, pesfilter) != 0:
        LOGGER.error("  unable to start demuxer")
        return -1
    LOGGER.debug("  demuxer initialization successful")
    return 0


def stop_demuxer(dmxfd):
    """stop demuxer"""
    LOGGER.debug("  stopping demuxer")
    if fcntl.ioctl(dmxfd, DMX_STOP) != 0:
        LOGGER.error("  DMX_STOP failed, unable to stop demuxer (erm, what?)")
        return -1
    return 0


def main():
    """run main program"""
    LOGGER.info("+++ Welcome to pydtm - Python (Euro)DOCSIS (3.0) Traffic Meter! +++ ")

    # simulate frequency and modulation list
    config = build_configuration()

    # update log level
    if not config.debug:
        LOGGER.setLevel(logging.INFO)
    else:
        LOGGER.setLevel(logging.DEBUG)

    # dbconnection
    try:
        client = InfluxDBClient(host=config.influx_host, port=config.influx_port, username=config.influx_username, password=config.influx_password)
        client.switch_database(config.influx_database)
    except:
        LOGGER.error(
            "error connecting to influxdb"
        )
        exit()
    

    # open the frontend device, demuxer and DVR device
    config.adapter = "/dev/dvb/adapter" + str(config.adapter)
    with open(config.adapter + "/frontend" + str(config.tuner), "r+") as fefd, open(
        config.adapter + "/demux" + str(config.tuner), "r+"
    ) as dmxfd, open(config.adapter + "/dvr" + str(config.tuner), "rb") as dvrfd:

        # the demux device needs to be opened non blocking
        flag = fcntl.fcntl(dvrfd, fcntl.F_GETFL)
        fcntl.fcntl(dvrfd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

        # we will need to poll the DVR
        dvr_poller = select.poll()
        dvr_poller.register(dvrfd, select.POLLIN | select.POLLPRI)

        # set appropriate buffer size
        # MPEG-TS are chopped into (at most) 188 sections
        ts_length = 189
        ts_buffer = ts_length * 2048
        LOGGER.debug("Setting demuxer buffer size to %d", ts_buffer)
        if fcntl.ioctl(dmxfd, DMX_SET_BUFFER_SIZE, ts_buffer) != 0:
            LOGGER.error("DMX_SET_BUFFER_SIZE failed, aborting")
            exit(1)

        # timeout for polling
        frequencies_count = len(frequency_list(config.frequencies))
        timeout = config.step / frequencies_count
        LOGGER.debug("Spending about %ds per frequency with data retrieval", timeout)
        
        LOGGER.debug("--- begin main loop ---")

        # begin main loop
        while True:
            
            LOGGER.info("Start new scan cycle (%d frequencies)", frequencies_count)
            total_start_time = datetime.datetime.now()
            total_speed = 0

            # prepare message array for sending to influxdb
            influx_messages = []
            
            # for debugging
            num = 0
            # iterate over all given frequency and modulation paris
            for tunable in frequency_list(config.frequencies):
                # try to tune and start the filter process
                count = 0
                num += 1
                if tune(fefd, tunable, config.locktime, num, frequencies_count)  != 0 or start_demuxer(dmxfd) != 0:
                    break

                # make sure we spend at most (step / number of frequencies) second per frequency
                start_time = timeit.default_timer()
                end_time = start_time
                while (end_time - start_time) < timeout:
                    # interrupting a poll() system call will cause a traceback
                    # using try/except will suppress that for SIGTERM, but not for SIGINT
                    # (Python got it"s own SIGINT handler)
                    try:
                        events = dvr_poller.poll(timeout * 1000)
                    except IOError:
                        LOGGER.warning("  event polling was interrupted", exc_info=True)
                        # try to stop the demuxer
                        stop_demuxer(dmxfd)
                        break

                    for _, flag in events:
                        if flag & (select.POLLIN | select.POLLPRI):
                            data = dvrfd.read(ts_buffer)
                            count += len(data)
                            end_time = timeit.default_timer()
                # record final end time
                elapsed = timeit.default_timer() - start_time

                # stop filtering
                if stop_demuxer(dmxfd) != 0:
                    break

                # append data to infuxdb message
                if tunable.modulation == QAM_256:
                    m_type = "qam256"
                else:
                    m_type = "qam64"
                influx_messages.append(
                    {
                        "measurement": "pydtm",
                        "tags":{
                            "name": "{}.{}".format(m_type,tunable.frequency),
                            "frequency": tunable.frequency,
                            "modulation": m_type,
                        },
                        "fields": {
                            "speed":round((count * 8 / elapsed) / 1024, 2),
                        },
                        "time":int(round(time.time() * 1000)),
                    }
                )

                # for debugging purposes, output data
                LOGGER.debug(
                    "  frequency %d done: spent %fs, got %d packets (%d bytes) equaling a rate"
                    "of %fkBit/s",
                    tunable.frequency,
                    elapsed,
                    len(data) / ts_length,
                    len(data),
                    round((count * 8) / elapsed / 1024, 2),
                )
                total_speed += round((count * 8) / elapsed / 1024, 2)

            total_time_diff = datetime.datetime.now() - total_start_time
            LOGGER.info("Scan completed in %ds (%d/%d frequencies, %.2f MB/s total).", 
                total_time_diff.seconds,
                #datetime.datetime.strftime(total_time_diff, "%M:%S"),
                num,
                frequencies_count,
                total_speed / 1024
            )

            # send data
            LOGGER.info("Sending data to database...")
            LOGGER.debug("Data: %s", influx_messages)
            try:
                client.write_points(influx_messages, time_precision='ms')
            except:
                LOGGER.error(
                    "Error sending to database"
                )

            sleeptime = (config.interval - total_time_diff.seconds)
            if sleeptime > 0:
                nextRun = datetime.datetime.now() + datetime.timedelta(seconds=sleeptime)
                LOGGER.info("Scheduled next run at %s (sleep %ds)",
                    nextRun.strftime("%Y-%m-%d %H:%M:%S"),
                    sleeptime
                )
            
                time.sleep(sleeptime)
            else:
                LOGGER.debug("Start next run immediately")
            
                    

if __name__ == "__main__":
    main()
