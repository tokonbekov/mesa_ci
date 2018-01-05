# Copyright (C) Intel Corp.  2017.  All Rights Reserved.

# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:

# The above copyright notice and this permission notice (including the
# next paragraph) shall be included in all copies or substantial
# portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE COPYRIGHT OWNER(S) AND/OR ITS SUPPLIERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

#  **********************************************************************/
#  * Authors:
#  *   Mark Janes <mark.a.janes@intel.com>
#  *   Clayton Craft <clayton.a.craft@intel.com>
#  **********************************************************************/

# util.py - Collection of useful methods for mesa_jenkins services

import hashlib
import os
import sys


def write_pid(pidfile):
    """Write the PID file."""
    with open(pidfile, 'w') as f:
        f.write(str(os.getpid()))


class TimeoutException(Exception):
    def __init__(self, msg):
        Exception.__init__(self)
        self._msg = msg

    def __str__(self):
        return self._msg


def signal_handler(signum, frame):
    raise TimeoutException("Fetch timed out.")


def signal_handler_quit(signum, frame):
    sys.exit(-1)


def file_checksum(fname):
    """ Generate md5 checksum for given file """
    with open(fname, 'rb') as f:
        return hashlib.md5(f.read()).digest()
