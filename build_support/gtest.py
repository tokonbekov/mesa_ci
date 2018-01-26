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

"""Handles running of gtest executables"""
import os
import sys
import subprocess

from . import Options
from . import ProjectMap
from . import rmfile
from . import run_batch_command
from . import Export

class GTest:
    """Runs google test executables, publishing results to server"""
    def __init__(self, binary_dir, executables):
        """explanation of parameters:
            binary_dir:  directory containing the executables.
            executables: list of gtest executables
        """
        self._bin_dir = binary_dir
        self._executables = executables
        if type(executables) != type([]):
            self._executables = [executables]

    def run_tests(self):
        """
        nonzero return is an error
        """
        
        options = Options()

        env = {}
        options.update_env(env)
            
        pm = ProjectMap()
        br = pm.build_root()
        for test in self._executables:
            outname = "_".join(["gtest", 
                                os.path.basename(test),
                                options.config, 
                                options.arch,
                                options.hardware,
                            ]) + ".xml"
            outpath = br + "/../test/" + outname
            if os.path.exists(outpath):
                rmfile(outpath)

            test_path = os.path.join(self._bin_dir, test)
            if not os.path.exists(test_path):
                Export().create_failing_test("missing-gtest-" + test,
                                             "ERROR: gtest does not exist: " + test_path)
                continue
            cmd = [test_path,
                   "--gtest_output=xml:" + outpath,
                   "--gtest_catch_exceptions"]
            try:
                run_batch_command(cmd, env=env)
            except(subprocess.CalledProcessError):
                Export().create_failing_test("failing-gtest-" + test,
                                             "WARN: gtest returned non-zero status: " + test_path)
                continue
            if not os.path.exists(outpath):
                Export().create_failing_test("silent-gtest-" + test,
                                             "ERROR: gtest produced no output: " + test_path)
                continue

        # create a copy of the test xml in the source root, where
        # jenkins can access it.
        cmd = ["cp", "-a",
               br + "/../test", pm.source_root()]
        run_batch_command(cmd)
