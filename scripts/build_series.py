#!/usr/bin/python

import git
import argparse
import sys
import urllib
import urllib2
import time
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import build_support as bs

parser = argparse.ArgumentParser(description="builds a sequence of commits on jenkins")

parser.add_argument('--start_rev', type=str, default='',
                    help="The sha starting the sequence to be tested")

parser.add_argument('--end_rev', type=str, default='',
                    help="The sha ending the sequence to be tested")

parser.add_argument('--project', type=str, default='all-test',
                    choices=['test-single-arch', 'piglit', 'piglit-test', 'piglit-full',
                             'deqp-full', 'crucible-all', 'crucible-test', "cts-test", "mesa", "vulkancts-full", "glescts-full"],
                    help="The jenkins project to build")

parser.add_argument('--series_name', type=str, default='',
                    help="The name to apply to each custom build")

parser.add_argument('--arch', type=str, default='m64',
                    help="The arch for the build")

parser.add_argument('--hardware', type=str, default='builder',
                    help="The hardware to be targeted for test "
                    "('builder', 'snbgt1', 'ivb', 'hsw', 'bdw'). "
                    "(default: %(default)s)")

parser.add_argument('--build_support_branch', type=str, default='master',
                    help="The automation branch to use"
                    "(default: %(default)s)")

parser.add_argument('--branch', type=str, default='mesa_master',
                    help="The branch to use"
                    "(default: %(default)s)")

args = parser.parse_args(sys.argv[1:])

if not args.series_name:
    print "ERROR: --series_name required"
    sys.exit(-1)

repos = bs.RepoSet()
repos.fetch()

found = False

for project in ["mesa", "piglit", "waffle", "drm", "crucible"]:
    try:
        revspec = bs.RevisionSpecification(revisions={project: args.start_rev})
        revspec.checkout()
    except:
        print args.start_rev + " not found in " + project
        continue

    print args.start_rev + " found in " + project
    found = True
    break

if not found:
    sys.exit(-1)    

repo = repos.repo(project)

try:
    repo.git.checkout(args.end_rev)
except:
    print "ERROR: could not check out end_rev: " + args.end_rev + ". Please provide --end_rev"
    sys.exit(-1)

commits = []
for commit in repo.iter_commits(max_count=1000):
    commits.append(commit)
    if args.start_rev in commit.hexsha:
        break

if args.start_rev not in commits[-1].hexsha:
    print "ERROR: could not find start_rev in history: " + args.start_rev + ". Please provide --start_rev"

commits.reverse()
print "building series:"
for commit in commits:
    print commit.hexsha

    server = bs.ProjectMap().build_spec().find("build_master").attrib["host"]
    custom_url = "http://" + server + "/job/mesa_custom/buildWithParameters?token=noauth&{0}"
    job_args = { "name" : args.series_name + "_" + commit.hexsha[:8],
                 "revision" : project + "=" + commit.hexsha,
                 "project" : args.project,
                 "hardware" : args.hardware,
                 "rebuild" : "true",
                 "arch" : args.arch,
                 "build_support_branch" : args.build_support_branch,
                 "branch" : args.branch }
    url = custom_url.format(urllib.urlencode(job_args))

    failcount = 0
    while True:
        try:
            f = urllib2.urlopen(url)
            break
        except (urllib2.HTTPError, urllib2.URLError):
            print "failure urllib2.urlopen(\"{0}\")".format(url)
            failcount += 1
            if failcount == 5:
                raise
            time.sleep(5)

