#!/usr/bin/python2

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
#  *   Clayton Craft <clayton.a.craft@intel.com>
#  **********************************************************************/

"""
Notes:
    - monitors the following files and restarts poll_branches and fetch_mirrors
      services on any changes:
        - services/fetch_mirrors/fetch_mirrors.py
        - services/poll_branches/poll_branches.py
        - build_specification.xml
    - updates mesa_jenkins workspace (/var/cache/mesa_jenkins

"""
import git
import os
import subprocess
import sys
import time

sys.path.append("/var/cache/mesa_jenkins/services/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import util

sys.path.append("/var/cache/mesa_jenkins/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "../.."))
import build_support as bs

# Branch to use for mesa_jenkins working directory
BRANCH = "master"


class ServiceRestartFailure(Exception):
    def __init__(self, service_name, stdout, stderr):
        self.name = service_name
        self.stdout = stdout
        self.stderr = stderr

    def __str__(self):
        return ("FATAL: Unable to restart service %s:\n"
                "Output from failing command: %s\n%s"
                % (self.name, self.stdout, self.stderr))


def restart_service(service_name):
    # Restart service
    p = subprocess.Popen(["systemctl", "restart", service_name],
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode:
        raise ServiceRestartFailure(service_name, out, err)


def reload_service_files():
    # Call daemon-reload in case systemd .service file was changed
    subprocess.check_call(["systemctl", "daemon-reload"],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)


def main():

    util.write_pid('/var/run/mesa_jenkins_monitor.pid')
    try:
        bs.ProjectMap()
    except:
        sys.argv[0] = "/var/cache/mesa_jenkins/foo.py"
    pm = bs.ProjectMap()

    # Locations of files that trigger service restarts:
    spec_file = os.path.join(pm.source_root(), "build_specification.xml")
    poll_branches_file = os.path.join(pm.source_root(),
                                      "services/poll_branches"
                                      "/poll_branches.py")
    fetch_mirrors_file = os.path.join(pm.source_root(),
                                      "services/fetch_mirrors/"
                                      "fetch_mirrors.py")
    new_spec_hash = None
    new_poll_branches_hash = None
    new_fetch_mirrors_hash = None

    mesa_jenkins_repo = git.Repo(pm.source_root())
    while True:
        spec_hash = util.file_checksum(spec_file)
        if os.path.exists(poll_branches_file):
            poll_branches_hash = util.file_checksum(poll_branches_file)
        if os.path.exists(fetch_mirrors_file):
            fetch_mirrors_hash = util.file_checksum(fetch_mirrors_file)
        try:
            mesa_jenkins_repo.git.pull("origin", BRANCH)
            mesa_jenkins_repo.git.checkout(BRANCH, force=True)
        except git.GitCommandError:
            raise Exception("FATAL: Unable to update mesa_jenkins "
                            "work directory: %s" % pm.source_root())

        new_spec_hash = util.file_checksum(spec_file)
        if os.path.exists(poll_branches_file):
            new_poll_branches_hash = util.file_checksum(poll_branches_file)
        if os.path.exists(fetch_mirrors_file):
            new_fetch_mirrors_hash = util.file_checksum(fetch_mirrors_file)

        # Reload service files and restart services if any interesting files
        # have changed
        if (new_spec_hash != spec_hash or
                new_poll_branches_hash != poll_branches_hash or
                new_fetch_mirrors_hash != fetch_mirrors_hash):

            print("INFO: Change detected in service files and/or build_spec, "
                  "restarting services!")
            spec_hash = new_spec_hash
            poll_branches_hash = new_poll_branches_hash
            fetch_mirrors_hash = new_fetch_mirrors_hash

            reload_service_files()
            if os.path.exists(fetch_mirrors_file):
                restart_service("fetch_mirrors")
            if os.path.exists(poll_branches_file):
                restart_service("poll_branches")
        time.sleep(30)
    return


if __name__ == "__main__":
    main()
