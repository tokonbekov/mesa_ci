#!/usr/bin/python2

from __future__ import print_function
import hashlib
import os
import sys
import time
import urllib2

# When running as a service, mesa_jenkins must be available to
# automation.  See:
# https://github.com/janesma/mesa_jenkins/wiki/services-setup

# this service triggers builds based on commits made to repos as set
# in the build_specification.xml at
# build_specification/branches/branch tags.

# append services directory to pythonpath, so we can make use of
# Daemon.  Second line is for finding Daemon when running from the
# checkout, and not when runnning as a service.
sys.path.append("/var/lib/git/mesa_jenkins/services/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))

# append build_support directory to pythonpath, so we can make use of
# RepoSet etc.  Second line is for finding build_support when running
# from the checkout, and not when runnning as a service.
sys.path.append("/var/lib/git/mesa_jenkins/")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "../.."))
import build_support as bs

# running a service through intel's proxy requires some annoying settings.
os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = "/usr/local/bin/git"
# without this, git-remote-https spins at 100%
os.environ["http_proxy"] = "http://proxy.jf.intel.com:911/"
os.environ["https_proxy"] = "http://proxy.jf.intel.com:911/"


def write_pid(pidfile):
    """Write the PID file."""
    with open(pidfile, 'w') as f:
        f.write(str(os.getpid()))


def file_checksum(fname):
    return hashlib.md5(open(fname, 'rb').read()).digest()


def main():
    write_pid('/var/run/poll_branches.pid')
    try:
        bs.ProjectMap()
    except:
        sys.argv[0] = "/var/lib/git/mesa_jenkins/foo.py"
    pm = bs.ProjectMap()
    spec_file = pm.source_root() + "/build_specification.xml"

    new_spec_hash = None
    while True:
        orig_spec_hash = file_checksum(spec_file)
        spec = pm.build_spec()
        server = spec.find("build_master").attrib["host"]
        if new_spec_hash is not None:
            print("Build Specification updated", file=sys.stderr)
            sys.stderr.flush()
        new_spec_hash = file_checksum(spec_file)
        status = bs.RepoStatus(cached_only=True)
        while new_spec_hash == orig_spec_hash:
            branches = status.poll()
            sys.stderr.flush()
            sys.stdout.flush()
            for (branch, commit) in branches.iteritems():
                print("Building " + branch, file=sys.stderr)
                sys.stderr.flush()
                job_url = "http://" + server + "/job/" + branch + \
                          "/buildWithParameters?token=noauth&name=" + commit + "&type=percheckin"
                retry_count = 0

                # how wonderful, the proxy setting is required for
                # git but prevents the service from accessing
                # otc-mesa-ci.
                os.environ["http_proxy"] = ""
                while retry_count < 10:
                    try:
                        f = urllib2.urlopen(job_url)
                        f.read()
                        break
                    except urllib2.HTTPError as e:
                        print(e, file=sys.stderr)
                        retry_count = retry_count + 1
                        print("ERROR: failed to reach jenkins, retrying: " + job_url,
                              file=sys.stderr)
                        sys.stderr.flush()
                        time.sleep(10)
                os.environ["http_proxy"] = "http://proxy.jf.intel.com:911/"

            time.sleep(30)
            new_spec_hash = file_checksum(spec_file)

if __name__ == "__main__":
    main()
