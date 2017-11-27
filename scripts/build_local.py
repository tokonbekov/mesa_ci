#!/usr/bin/python

import argparse, sys, os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import build_support as bs

class CsvChoice(object):
    def __init__(self, *args):
        self.values = args
    def __len__(self):
        return self.values.__len__()
    def __iter__(self):
        return self.values.__iter__()

    def __contains__(self, choice):
        # If we were not passed a string, it isn't contained here
        if type(choice) != str:
            return False
        result = True
        for i in choice.split(','):
            result &= i in self.values
        return result

class CsvAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values.split(','))

def main():
    parser = argparse.ArgumentParser(description='Build projects locally.')

    # TODO: provide a pull action to update the repos
    parser.add_argument('--action', type=str, default=["build"],
                        choices=CsvChoice('fetch', 'build', 'clean', 'test'),
                        action=CsvAction,
                        help="Action to recurse with. 'build', 'clean' "\
                        "or 'test'. (default: %(default)s)")

    parser.add_argument('--project', dest='project', type=str, default="mesa",
                        help='project to build. (default: %(default)s)')
    parser.add_argument('--arch', dest='arch', type=str, 
                        default='m64', choices=['m64', 'm32'],
                        help='arch to build. (default: %(default)s)')
    parser.add_argument('--config', type=str, default="debug",
                        choices=['release', 'debug'],
                        help="Release or Debug build. (default: %(default)s)")

    parser.add_argument('--type', type=str, default="developer",
                        choices=['developer', 'percheckin', 
                                 'daily', 'release'],
                        help="category of tests to run. "\
                        "(default: %(default)s)")

    parser.add_argument('--branch', type=str, default="none",
                        help="Branch specification to build.  "\
                        "See build_specification.xml/branches")
    parser.add_argument('--env', type=str, default="",
                        help="If specified, overrides environment variable settings"
                        "EG: 'LIBGL_DEBUG=1 INTEL_DEBUG=perf'")
    parser.add_argument('--hardware', type=str, default='builder',
                        help="The hardware to be targeted for test "
                        "('builder', 'snbgt1', 'ivb', 'hsw', 'bdw'). "
                        "(default: %(default)s)")

    args = parser.parse_args()
    project = args.project

    if "fetch" in args.action:
        # fetch not supported by build.py scripts, which will parse argv
        bs.RepoSet().fetch()
    branch = args.branch
    if (branch != "none"):
        bs.BuildSpecification().checkout(branch)

    # some build_local params are not handled by the Options, which is
    # used by other modules
    o = bs.Options(["bogus"])
    vdict = vars(args)
    del vdict["project"]
    del vdict["branch"]
    if "fetch" in vdict["action"]:
        vdict["action"].remove("fetch")
    o.__dict__.update(vdict)
    sys.argv = ["bogus"] + o.to_list()

    if "clean" in args.action:
        bs.rmtree(bs.ProjectMap().build_root())

    graph = bs.DependencyGraph(project, o)
    ready = graph.ready_builds()
    pm = bs.ProjectMap()
    while ready:
        for bi in ready:
            graph.build_complete(bi)
            proj_build_dir = pm.project_build_dir(bi.project)
            script = proj_build_dir + "/build.py"
            if os.path.exists(script):
                bs.run_batch_command([sys.executable, 
                                      script] +  
                                     o.to_list())
        ready = graph.ready_builds()

main()
