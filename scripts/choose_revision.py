import argparse
import random
import git
import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import build_support as bs

def main():
    parser= argparse.ArgumentParser(description="Choose a random revision of mesa")
    parser.add_argument('--revision', type=str, default="",
                        help="bounds for mesa revision to test, start:[finish]")

    args = parser.parse_args()
    revision = args.revision
    bspec = bs.BuildSpecification()
    bspec.checkout("mesa_master")
    mesa_repo = git.Repo(bs.ProjectMap().project_source_dir("mesa"))
    if ":" in revision:
        (start_rev, end_rev) = revision.split(":")
        if not end_rev:
            # user selected the last point in a plot.  Build current master
            revision = "mesa=" + mesa_repo.git.rev_parse("HEAD", short=True)
        elif not start_rev:
            print "ERROR: user-generated perf builds cannot add older data points to the plot"
            sys.exit(-1)
        else:
            commits = []
            start_commit = mesa_repo.commit(start_rev)
            found = False
            for commit in mesa_repo.iter_commits(end_rev, max_count=8000):
                if commit == start_commit:
                    found = True
                    break
                commits.append(commit.hexsha)
            if not found:
                print "ERROR: " + start_rev + " not found in history of " + end_rev
                sys.exit(-1)
            revision = "mesa=" + str(commits[len(commits)/2])
        print revision
        sys.exit(0)

    # else choose random revision
    branch_commit = mesa_repo.tags["17.1-branchpoint"].commit.hexsha
    commits = []
    for commit in mesa_repo.iter_commits('origin/master', max_count=8000):
        if commit.hexsha == branch_commit:
            break
        commits.append(commit.hexsha)
    revision = "mesa=" + str(commits[int(random.random() * len(commits))])
    print revision


if __name__=="__main__":
    try:
        main()
    except SystemExit:
        # Uncomment to determine which version of argparse is throwing
        # us under the bus.

        #  Word of Wisdom: Don't call sys.exit
        #import traceback
        #for x in traceback.format_exception(*sys.exc_info()):
        #    print x
        raise
