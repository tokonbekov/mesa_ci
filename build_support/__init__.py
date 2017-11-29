# Copyright (C) Intel Corp.  2014.  All Rights Reserved.

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
#  **********************************************************************/

#!/usr/bin/python

import time
import os
from command import *
#from command import killMajorProcesses
from options import *
from project_map import ProjectMap
#from export import Export
#from export import ExportTest
#from export import ExportSymbols
#from jenkins import Jenkins
#from spec import BuildInvoke
#from spec import BuildSpec
#from export import ExportZip
#from gtest import GTest as GTest
#from clean_server import CleanServer
from repo_set import *
from dependency_graph import DependencyGraph
from export import Export, convert_rsync_path
from gtest import *
from jenkins import *
from bisect_test import *
from builders import *
from timer import TimeOut
from deqp_builder import *
from perf_builder import *

class DefaultTimeout:
    def __init__(self, options=None):
        self._options = options
        if not options:
            self._options = Options()

    def GetDuration(self):
        """by default, components should finish in under 15 minutes.
        For daily builds, 60 minutes is acceptable."""

        if self._options.type == "daily" or self._options.type == "release":
            return 120
        if self._options.hardware == "byt":
            # bay trail takes 15min to rsync to /tmp on the sdcard
            return 30
        return 15

def null_build():
    pass

class NullInvoke:
    """masquerades as an invoke object, so the main routine can post
    results even if there is no server to post to"""
    def __init__(self):
        pass
    
    def set_info(self, *args):
        pass

    def set_status(self, *args):
        pass

def build(builder, options=None, time_limit=None, import_build=True):

    if not time_limit:
        time_limit = DefaultTimeout()
    if not options:
        options = Options()
    action_map = [
        ("clean", builder.clean),
        ("build", builder.build),
        ("test", builder.test),
    ]
    actions = options.action

    invoke = NullInvoke()

    if os.environ.has_key("PKG_CONFIG_PATH"):
        del os.environ["PKG_CONFIG_PATH"]
    if os.environ.has_key("LD_LIBRARY_PATH"):
        del os.environ["LD_LIBRARY_PATH"]
    if os.environ.has_key("LIBGL_DRIVERS_PATH"):
        del os.environ["LIBGL_DRIVERS_PATH"]

    # TODO: add this stuff
    if (options.result_path):
        # if we aren't posting to a server, don't attempt to write
        # status
        invoke = ProjectInvoke(options)

    invoke.set_info("start_time", time.time())

    # start a thread to limit the run-time of the build
    to = TimeOut(time_limit)
    to.start()

    if options.hardware != "builder" and check_gpu_hang():
        return

    if import_build:
        Export().import_build_root()

    if type(actions) is str:
        actions = [actions]

    # clean out the test results directory, so jenkins processes only
    # the files for the current build
    if "test" in actions:
        test_out_dir = ProjectMap().source_root() + "/test"
        if os.path.exists(test_out_dir):
            rmtree(test_out_dir)

    # Walk through the possible actions in order, if those actions are not
    # requested go on. The order does matter.
    for k, a in action_map:
        if k not in actions:
            continue
        options.action = a

        try:
            a()
            if k == "test" and "CACHE_DISABLE" in options.env:
                print("Running a second time to test shader cache!")
                a()
        except:
            # we need to cancel the timer first, in case
            # set_status fails, and the timer is left running
            to.end()
            invoke.set_info("status", "failed")
            # must cancel timeout timer, which will prevent process from ending
            raise        
                
    # must cancel timeout timer, which will prevent process from
    # ending.  cancel the timer first, in case set_status fails, and
    # the timer is left running
    to.end()
    invoke.set_info("end_time", time.time())
    invoke.set_info("status", "success")


