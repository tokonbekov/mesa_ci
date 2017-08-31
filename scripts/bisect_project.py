#!/usr/bin/python

from email.mime.text import MIMEText
import argparse
import datetime
import git
import os
import smtplib
import sys
import time

current_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
sys.path.append(current_dir + "/..")
import build_support as bs

parser = argparse.ArgumentParser(description="bisects failures")
parser.add_argument("--result_path", type=str)
parser.add_argument("--good_rev", type=str,
                    help="project and rev, eg: mesa=hexsha")
parser.add_argument('--to', metavar='to', type=str, default="",
                    help='send resulting patch to this email')
parser.add_argument('--dir', metavar='dir', type=str, default="",
                    help='directory to bisect in')
args = parser.parse_args(sys.argv[1:])

# get revisions from out directory
test_dir = os.path.abspath(args.result_path + "/test")
if not os.path.exists(test_dir):
    print "ERROR: no tests in --result_path: " + test_dir
    sys.exit(-1)

dirnames = os.path.abspath(test_dir).split("/")
hash_dir = dirnames[5]
revs = hash_dir.split("_")

pm = bs.ProjectMap()
spec_xml = pm.build_spec()
results_dir = spec_xml.find("build_master").attrib["results_dir"]

repos = bs.RepoSet()
_revspec = bs.RevisionSpecification.from_cmd_line_param(revs)
_revspec.checkout()

proj_rev = args.good_rev.split("=")
proj = proj_rev[0]
good_rev = proj_rev[1]
proj_repo = repos.repo(proj)

print proj + " revisions under bisection:"
commits = []
for commit in proj_repo.iter_commits(max_count=5000):
    commits.append(commit)
    print commit.hexsha
    if good_rev in commit.hexsha:
        break
else:
    print 'ERROR: Good commit ({}) not found'.format(good_rev)
    sys.exit(1)

# retest build, in case expected failures has been updated
# copy build root to bisect directory
bisect_dir = args.dir
if bisect_dir == "":
    bisect_dir = results_dir + "/bisect/" + datetime.datetime.now().isoformat()

cmd = ["rsync", "-rlptD", "--exclude", "/*test/", "/".join(dirnames[:-1]) +"/", bisect_dir]
bs.run_batch_command(cmd)

if not bs.retest_failures(args.result_path, bisect_dir):
    print "ERROR: retest failed"

# make sure there is enough time for the test files to sync to nfs
time.sleep(20)
new_failures = bs.TestLister(bisect_dir + "/test/")

if not new_failures.Tests():
    print "All tests fixed"
    sys.exit(0)

print "Found failures:"
new_failures.Print()

revspec = bs.RevisionSpecification(revisions={proj: commits[-1].hexsha})
revspec.checkout()
revspec = bs.RevisionSpecification()
hashstr = revspec.to_cmd_line_param().replace(" ", "_")
old_out_dir = "/".join([bisect_dir, hashstr])

print "Building old mesa to: " + old_out_dir
bs.retest_failures(bisect_dir, old_out_dir)

time.sleep(20)
tl = bs.TestLister(old_out_dir + "/test/")
print "old failures:"
tl.Print()
print "failures due to " + proj + ":"
proj_failures = new_failures.TestsNotIn(tl)
for a_test in proj_failures:
    a_test.Print()

for a_test in proj_failures:
    a_test.Bisect(proj, commits, bisect_dir)
    a_test.UpdateConf()

if args.to:
    patch_text = git.Repo().git.diff()
    msg = MIMEText(patch_text)
    msg["Subject"] = "[PATCH] jenkins updates due to bisect of " + proj
    msg["From"] = "Do Not Reply <mesa_jenkins@intel.com>"
    msg["To"] = args.to
    s = smtplib.SMTP('or-out.intel.com')
    to = args.to.split(",")
    s.sendmail(msg["From"], to, msg.as_string())

    os.chdir(pm.source_root() + "/repos/prerelease")
    r = git.Repo()
    patch_text = r.git.diff()
    if not patch_text:
        sys.exit(0)
    print patch_text
    msg = MIMEText(patch_text)
    msg["Subject"] = "[PATCH] prerelease config updates due to bisect of " + proj
    msg["From"] = "Do Not Reply <mesa_jenkins@intel.com>"
    msg["To"] = args.to
    s = smtplib.SMTP('or-out.intel.com')
    to = args.to.split(",")
    s.sendmail(msg["From"], to, msg.as_string())
    r.git.reset("--hard")
