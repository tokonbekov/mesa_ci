#!/usr/bin/python

import argparse
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..")))
import build_support as bs

parser = argparse.ArgumentParser(description="checks out branches and commits")
parser.add_argument('--branch', type=str, default="mesa_master",
                    help="The branch to base the checkout on. (default: %(default)s)")
parser.add_argument('commits', metavar='commits', type=str, nargs='*',
                    help='commits to check out, in repo=sha format')
args = parser.parse_args()

repos = bs.RepoSet()
repos.clone()
repos.fetch()
bs.BuildSpecification().checkout(args.branch, args.commits)


