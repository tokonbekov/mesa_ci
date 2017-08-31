import argparse
import datetime
import os
import sys
import tarfile
import time
from prettytable import PrettyTable
import xml.etree.cElementTree as et
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import build_support as bs

def strip_passes(root):
    for a_suite in root.findall("testsuite"):
        for a_test in a_suite.findall("testcase"):
            # strip suffix
            a_test.attrib["name"] = ".".join(a_test.attrib["name"].split(".")[:-1])
            fails = a_test.findall("failure") + a_test.findall("error")
            if not fails:
                # strip status if no fail tag
                a_test.attrib["status"] = "pass"
                # strip output for passes.  crucible junit does not
                # presently have system out/err
                sout = a_test.find("system-out")
                if sout is not None:
                    sout.text = " "
                serr = a_test.find("system-err")
                if serr is not None:
                    serr.text = " "

def create_revision_table():
    repo_set = bs.RepoSet()

    table_repo = []
    table_message = []
    table_sha = []

    for project in repo_set.projects():
        repo = repo_set.repo(project)
        commit = repo.commit()
        message = commit.message.splitlines()[0]
        sha = repo.git.rev_parse(commit.hexsha, short=True)

        table_repo.append(project)
        table_sha.append(sha)
        table_message.append(message)

    x = PrettyTable()
    x.add_column("Project", [ p for p in table_repo])
    x.add_column("sha", [ s for s in table_sha])
    x.add_column("Message", [ m for m in table_message ])

    x.align["Project"] = "l"
    x.align["Commit"] = "c"
    x.align["Message"] = "l"

    text_table = str(x)
    return text_table

def collate_tests(result_path, out_test_dir, make_tar=False):
    src_test_dir = result_path + "/test"
    print "collecting tests from " + src_test_dir
    i = 0
    while i < 10 and not os.path.exists(src_test_dir):
        i += 1
        print "sleeping, waiting for test directory: " + src_test_dir
        time.sleep(10)
    if not os.path.exists(src_test_dir):
        print "no test directory found: " + src_test_dir
        return

    cmd = ["cp", "-a", "-n",
           src_test_dir,
           out_test_dir]
    bs.run_batch_command(cmd)

    # Junit files must have a recent time stamp or else Jenkins will
    # not parse them.
    for a_file in os.listdir(out_test_dir + "/test"):
        os.utime(out_test_dir + "/test/" + a_file, None)

    revisions_path = bs.ProjectMap().source_root() + "/revisions.txt"
    with open(revisions_path, "w") as revs:
        revs.write(create_revision_table())

    if not make_tar:
        return

    # else generate a results.tgz that can be used with piglit summary
    save_dir = os.getcwd()
    os.chdir("/tmp/")
    tar = tarfile.open(out_test_dir + "/test/results.tar", "w:")
    shards = {}
    for a_file in os.listdir(out_test_dir + "/test"):
        if "piglit" not in a_file:
            continue
        if ":" in a_file:
            shard_base_name = "_".join(a_file.split("_")[:-1])
            if not shards.has_key(shard_base_name):
                shards[shard_base_name] = []
            shards[shard_base_name].append(a_file)
            continue
        t = et.parse(out_test_dir + "/test/" + a_file)
        r = t.getroot()
        strip_passes(r)
        t.write(a_file)
        # occasionally, t.write() finishes, but the file is not available
        t = None
        for _ in range(0,5):
            try:
                tar.add(a_file)
                break
            except:
                print "WARN: failed to add file: " + a_file
                time.sleep(10)
        os.unlink(a_file)
    for (shard, files) in shards.items():
        t = et.parse(out_test_dir + "/test/" + files[0])
        r = t.getroot()
        strip_passes(r)
        suite = r.find("testsuite")
        for shards in files[1:]:
            st = et.parse(out_test_dir + "/test/" + shards)
            sr = st.getroot()
            strip_passes(sr)
            for a_suite in sr.findall("testsuite"):
                for a_test in a_suite.findall("testcase"):
                    suite.append(a_test)
        shard_file = shard + ".xml"
        t.write(shard_file)
        # occasionally, t.write() finishes, but the file is not available
        t = None
        for _ in range(0,5):
            try:
                tar.add(shard_file)
                break
            except:
                print "WARN: failed to add file: " + shard_file
                time.sleep(10)
        os.unlink(shard_file)

    if os.path.exists(out_test_dir + "/test/logs"):
        save_dir = os.getcwd()
        os.chdir(out_test_dir + "/test")
        tar.add("logs")
        os.chdir(save_dir)

    tar.close()
    bs.run_batch_command(["xz", "-9", out_test_dir + "/test/results.tar"])
    os.chdir(save_dir)

    tl = bs.TestLister(out_test_dir + "/test")
    tests = tl.Tests()
    if tests:
        with open("test_summary.txt", "w") as fh:
            for atest in tests:
                atest.PrettyPrint(fh)
            fh.flush()
            # end users report that sometimes the summary is empty
            os.fsync(fh.fileno())
            fh.close()
        time.sleep(10)


def main():
    # reuse the options from the gasket
    o = bs.Options([sys.argv[0]])
    description="builds a component on jenkins"
    parser= argparse.ArgumentParser(description=description,
                                    parents=[o._parser],
                                    conflict_handler="resolve")
    parser.add_argument('--project', dest='project', type=str, default="",
                        help='Project to build. Default project is specified '\
                        'for the branch in build_specification.xml')

    parser.add_argument('--branch', type=str, default="mesa_master",
                        help="Branch specification to build.  "\
                        "See build_specification.xml/branches")

    parser.add_argument('--revision', type=str, default="",
                        help="specific set of revisions to build.")

    parser.add_argument('--rebuild', type=str, default="false",
                        choices=['true', 'false'],
                        help="specific set of revisions to build."
                        "(default: %(default)s)")
    parser.add_argument("--tar", help="generate tar for email notification",
                        action="store_true")

    args = parser.parse_args()
    projects = []
    if args.project:
        projects = args.project.split(",")
    branch = args.branch
    revision = args.revision
    rebuild = args.rebuild

    # some build_local params are not handled by the Options, which is
    # used by other modules.  This code strips out incompatible args
    o = bs.Options(["bogus"])
    vdict = vars(args)
    del vdict["project"]
    del vdict["branch"]
    del vdict["revision"]
    del vdict["rebuild"]
    o.__dict__.update(vdict)
    sys.argv = ["bogus"] + o.to_list()

    bspec = bs.BuildSpecification()

    pm = bs.ProjectMap()
    bs.rmtree(pm.source_root() + "/test_summary.txt")
    bs.rmtree(pm.source_root() + "results/test/results.tgz")

    # start with the specified branch, then layer any revision spec on
    # top of it
    bspec.checkout(branch)
    revspec = None
    if (revision):
        revspec = bs.RevisionSpecification.from_cmd_line_param(revision.split())
        revspec.checkout()

    revspec = bs.RevisionSpecification()
    print "Building revision: " + revspec.to_cmd_line_param()

    hashstr = revspec.to_cmd_line_param().replace(" ", "_")

    # create a result_path that is unique for this set of builds
    spec_xml = pm.build_spec()
    results_dir = spec_xml.find("build_master").attrib["results_dir"]
    result_path = "/".join([results_dir, branch, hashstr, o.type])
    o.result_path = result_path

    if rebuild == "true" and os.path.exists(result_path):
        print "Removing existing results."
        mvdir = os.path.normpath(result_path + "/../" + datetime.datetime.now().isoformat())
        os.rename(result_path, mvdir)

    if not projects:
        branchspec = bspec.branch_specification(branch)
        projects = [branchspec.project]

    # use a global, so signal handler can abort builds when scheduler
    # is interrupted
    global jen

    jen = bs.Jenkins(result_path=result_path,
                     revspec=revspec)

    depGraph = bs.DependencyGraph(projects, o)

    out_test_dir = pm.output_dir()
    if os.path.exists(out_test_dir):
        bs.rmtree(out_test_dir)
    os.makedirs(out_test_dir)

    # to collate all logs in the scheduler
    out_log_dir = pm.output_dir()
    if os.path.exists(out_log_dir):
        bs.rmtree(out_log_dir)
    os.makedirs(out_log_dir)

    # Add a revisions.xml file
    if not os.path.exists(result_path):
        os.makedirs(result_path)
    revspec.to_elementtree().write(os.path.join(result_path, 'revisions.xml'))

    # use a global, so signal handler can abort builds when scheduler
    # is interrupted
    try:
        jen.build_all(depGraph, branch=branch)
    finally:
        collate_tests(result_path, out_test_dir, make_tar=args.tar)

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
