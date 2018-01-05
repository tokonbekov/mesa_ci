#!/usr/bin/python2

from __future__ import print_function
import os
import signal
import sys
import time

sys.path.append("/var/cache/mesa_jenkins/services/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import util

sys.path.append("/var/cache/mesa_jenkins/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "../.."))
import build_support as bs

sys.argv[0] = os.path.abspath(sys.argv[0])


def main():
    # Write the PID file
    util.write_pid('/var/run/fetch_mesa_mirrors.pid')

    signal.signal(signal.SIGALRM, util.signal_handler)
    signal.signal(signal.SIGINT, util.signal_handler_quit)
    signal.signal(signal.SIGTERM, util.signal_handler_quit)

    # running a service through intel's proxy requires some
    # annoying settings.
    os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = "/usr/local/bin/git"
    # without this, git-remote-https spins at 100%
    os.environ["http_proxy"] = "http://proxy.jf.intel.com:911/"
    os.environ["https_proxy"] = "http://proxy.jf.intel.com:911/"
    cache_location = os.environ.get("FETCH_MIRRORS_CACHE_DIR")
    if not cache_location:
        cache_location = "/var/lib/git/"

    try:
        bs.ProjectMap()
    except:
        sys.argv[0] = "/var/cache/mesa_jenkins/foo.py"

    if not os.path.exists(cache_location):
        os.makedirs(cache_location)
    # This *is* the service that creates the git cache, so do not use a cache
    # and create repos that are git clone mirrors:
    repos = bs.RepoSet(repos_root=cache_location, use_cache=False, mirror=True)
    repos.clone()

    while True:
        try:
            signal.alarm(300)   # 5 minutes
            repos.fetch()
        except bs.repo_set.RepoNotCloned:
            repos.clone()
        finally:
            signal.alarm(0)
            # pause a bit before fetching the next round
        time.sleep(20)


if __name__ == "__main__":
    main()
