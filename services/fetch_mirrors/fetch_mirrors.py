#!/usr/bin/python2

from __future__ import print_function
import hashlib
import os
import signal
import subprocess
import sys
import time

import git
import socket
if socket.gethostname() == "otc-mesa-ci":
    sys.path.append("/var/lib/git/mesa_jenkins/services/")
elif socket.gethostname() == "otc-mesa-android":
    sys.path.append("/var/lib/git/mesa_perf/repos/mesa_ci/services/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))

sys.path.append("/var/lib/git/mesa_jenkins/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "../.."))
import build_support as bs

sys.argv[0] = os.path.abspath(sys.argv[0])

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


def robust_clone(url, directory):
    success = False
    while not success:
        try:
            bs.run_batch_command(["/usr/local/bin/git", "clone", "--mirror",
                                  url, directory])
            success = True
        except(subprocess.CalledProcessError):
            print("Error: could not clone " + url, file=sys.stderr)
            time.sleep(10)


def robust_update():
    _success = False
    while not _success:
        try:
            _repo = git.Repo("/var/lib/git/mesa_jenkins")
            _repo.remotes.origin.pull()
            _success = True
        except:
            print("Error: could not update buildsupport", file=sys.stderr)
            time.sleep(10)
            

def file_checksum(fname):
    with open(fname, 'rb') as f:
        return hashlib.md5(f.read()).digest()


def main():
    # Write the PID file
    with open('/var/run/fetch_mesa_mirrors.pid', 'w') as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGALRM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler_quit)
    signal.signal(signal.SIGTERM, signal_handler_quit)

    # running a service through intel's proxy requires some
    # annoying settings.
    os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = "/usr/local/bin/git"
    # without this, git-remote-https spins at 100%
    os.environ["http_proxy"] = "http://proxy.jf.intel.com:911/"
    os.environ["https_proxy"] = "http://proxy.jf.intel.com:911/"

    try:
        bs.ProjectMap()
    except:
        sys.argv[0] = "/var/lib/git/mesa_jenkins/foo.py"

    pm = bs.ProjectMap()
    spec_file = pm.source_root() + "/build_specification.xml"
    new_spec_hash = None

    while True:
        orig_spec_hash = file_checksum(spec_file)
        if new_spec_hash is not None:
            print("Build Specification updated")
        new_spec_hash = file_checksum(spec_file)

        while new_spec_hash == orig_spec_hash:
            buildspec = bs.ProjectMap().build_spec()

            repo_dir = "/var/lib/git/"

            # build up a list of git repo objects for all known repos.  If the
            # origin or the remotes are not already cloned, clone them.
            repos = []
            repo_tags = buildspec.find("repos")
            for tag in repo_tags:
                url = tag.attrib["repo"]
                project = tag.tag
                origin_dir = repo_dir + project + "/origin"
                if not os.path.exists(origin_dir):
                    robust_clone(url, origin_dir)
                    bs.run_batch_command(["touch", origin_dir + "/git-daemon-export-ok"])
                repos.append(git.Repo(origin_dir))
                for a_remote in tag.findall("remote"):
                    remote_dir = repo_dir + project + "/" + a_remote.attrib["name"]
                    if not os.path.exists(remote_dir):
                        robust_clone(a_remote.attrib["repo"], remote_dir)
                        bs.run_batch_command(["touch", remote_dir + "/git-daemon-export-ok"])
                    repos.append(git.Repo(remote_dir))

            for repo in repos:
                try:
                    signal.alarm(300)   # 5 minutes
                    repo.git.fetch()
                    signal.alarm(0)
                except git.GitCommandError as e:
                    print("error fetching, ignoring: " + str(e), file=sys.stderr)
                    signal.alarm(0)
                except AssertionError as e:
                    print("assertion while fetching: " + str(e), file=sys.stderr)
                    signal.alarm(0)
                except TimeoutException as e:
                    print (str(e), file=sys.stderr)
                    signal.alarm(0)
            # pause a bit before fetching the next round
            time.sleep(20)
            robust_update()
            new_spec_hash = file_checksum(spec_file)


if __name__ == "__main__":
    main()
