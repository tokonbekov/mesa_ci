import os, time, sys, shutil, hashlib, argparse, shutil
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import build_support as bs

def collate_tests(result_path, out_test_dir):
    src_test_dir = result_path + "/test"
    print "collecting tests from " + src_test_dir
    if not os.path.exists(src_test_dir):
        time.sleep(10)
    if not os.path.exists(src_test_dir):
        print "no test directory found: " + src_test_dir
        return
        
    cmd = ["cp", "-a", "-n",
           src_test_dir,
           out_test_dir]
    bs.run_batch_command(cmd)

def main():

    # reuse the options from the gasket
    o = bs.Options([sys.argv[0]])
    description="builds a component on jenkins"
    parser= argparse.ArgumentParser(description=description, 
                                    parents=[o._parser], 
                                    conflict_handler="resolve")

    parser.add_argument('--branch', type=str, default="mesa_master",
                        help="Branch specification to build.  "\
                        "See build_specification.xml/branches")

    parser.add_argument('--revision', type=str, default="",
                        help="specific set of revisions to build.")

    parser.add_argument('--test', type=str, default=None,
                        help="Name of test to execute.  Arch/hardware suffix "\
                        "will override those options")

    args = parser.parse_args()
    branch = args.branch
    revision = args.revision
    test = args.test

    # some build_local params are not handled by the Options, which is
    # used by other modules.  This code strips out incompatible args
    o = bs.Options(["bogus"])
    vdict = vars(args)
    del vdict["branch"]
    del vdict["revision"]
    del vdict["test"]

    # override hardware/arch with suffix if available
    if not test:
        print "ERROR: --test argument required"
        sys.exit(-1)
        
    test_suffix = test.split(".")[-1]
    if test_suffix[-3:] in ["m32", "m64"]:
        vdict["arch"] = test_suffix[-3:]
        vdict["hardware"] = test_suffix[:-3]
    else:
        if vdict["hardware"] == "builder":
            # can't run tests on a builder
            vdict["hardware"] = "bdwgt2"
        # set the suffix in the way that piglit-test expects, eg "ilkm32"
        test = test + "." + vdict["hardware"] + vdict["arch"]
        
    o.__dict__.update(vdict)
    sys.argv = ["bogus"] + o.to_list()

    # check out the branch, refined by any manually-specfied revisions
    bspec = bs.BuildSpecification()
    bspec.checkout(branch)
    if (revision):
        revspec = bs.RevisionSpecification.from_cmd_line_param(revision.split())
        revspec.checkout()

    revspec = bs.RevisionSpecification()
    print "Building revision: " + revspec.to_cmd_line_param()

    # create a result_path that is unique for this set of builds
    spec_xml = bs.ProjectMap().build_spec()
    results_dir = spec_xml.find("build_master").attrib["results_dir"]
    result_path = "/".join([results_dir, branch,
                            revspec.to_cmd_line_param().replace(" ", "_"), "single_test"])
    o.result_path = result_path

    # allow re-execution of tests (if different test was specified)
    bs.rmtree(result_path + "/test")

    depGraph = bs.DependencyGraph("piglit-test", o)
    bi = bs.ProjectInvoke(project="piglit-test", 
                          options=o)

    # remove the test build, because we want to build it directly
    depGraph.build_complete(bi)
    bi.set_info("status", "single-test-rebuild")

    jen = bs.Jenkins(result_path=result_path,
                     revspec=revspec)
    jen.build_all(depGraph)
    jen.build(bi, extra_arg="--piglit_test=" + test)
    jen.wait_for_build()
    time.sleep(10)

    pm = bs.ProjectMap()
    out_test_dir = pm.output_dir()
    if os.path.exists(out_test_dir):
        bs.rmtree(out_test_dir)
    os.makedirs(out_test_dir)
    collate_tests(result_path, out_test_dir)

if __name__=="__main__":
    main();
