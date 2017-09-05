#!/usr/bin/python

import argparse
import datetime
from email.mime.text import MIMEText
import git
import os
import smtplib
import sys
import time

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import build_support as bs

parser = argparse.ArgumentParser(description="updates expected failures")

parser.add_argument('--blame_revision', type=str, required=True,
                    help='revision to specify as the cause of any config changes')
parser.add_argument('--result_path', metavar='result_path', type=str, default="",
                    help='path to build results')
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

rev_hash = {}
for a_rev in revs:
    proj = a_rev.split("=")[0]
    rev = a_rev.split("=")[1]
    rev_hash[proj] = rev

blame = args.blame_revision.split("=")
if len(blame) != 2:
    print "ERROR: --blame_revision must be in the format: project=rev"
    sys.exit(-1)

if not rev_hash.has_key(blame[0]):
    print "ERROR: invalid project in --blame_revision: " + blame[0]
    print "ERROR: acceptable projects: " + ",".join(rev_hash.keys())
    sys.exit(-1)

pm = bs.ProjectMap()
spec_xml = pm.build_spec()
results_dir = spec_xml.find("build_master").attrib["results_dir"]
retest_dir = args.dir
if retest_dir == "":
    retest_dir = results_dir + "/update/" + datetime.datetime.now().isoformat()

if rev_hash[blame[0]] == blame[1]:
    # rsync to save build if the blame is the same as the build
    src_dir = "/".join(dirnames[:-1]) + "/"
    dest_dir = bs.convert_rsync_path(retest_dir)
    cmd = ["rsync", "-rlptD", "--exclude", "/*test/", src_dir, dest_dir]
    bs.run_batch_command(cmd)
else:
    rev_hash[blame[0]] = blame[1]

# retest the set of failed tests on the specified blame revision
repos = bs.RepoSet()
_revspec = bs.RevisionSpecification.from_xml_file(
    os.path.join(os.path.abspath(args.result_path), 'revisions.xml'))
_revspec.checkout()
_revspec = bs.RevisionSpecification()

# use the full sha for the blame, so it can be looked up in a map when
# processing the config file
blame[1] = str(repos.repo(blame[0]).git.rev_parse(blame[1]))

if not bs.retest_failures(args.result_path, retest_dir):
    print "ERROR: retest failed"
    sys.exit(-1)
        
# make sure there is enough time for the test files to sync to nfs
time.sleep(20)
reproduced_failures = bs.TestLister(retest_dir + "/test/")

print "Found failures:"
reproduced_failures.Print()

for a_fail in reproduced_failures.Tests():
    a_fail.bisected_revision = " ".join(blame)
    a_fail.UpdateConf()

if args.to:
    patch_text = git.Repo().git.diff()
    print patch_text
    msg = MIMEText(patch_text)
    msg["Subject"] = "[PATCH] mesa jenkins updates due to " + args.blame_revision
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
    msg["Subject"] = "[PATCH] prerelease config updates due to " + args.blame_revision
    msg["From"] = "Do Not Reply <mesa_jenkins@intel.com>"
    msg["To"] = args.to
    s = smtplib.SMTP('or-out.intel.com')
    to = args.to.split(",")
    s.sendmail(msg["From"], to, msg.as_string())
    r.git.reset("--hard")
