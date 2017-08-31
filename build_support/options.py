# Copyright (C) Intel Corp.  2014.  All Rights Reserved.

# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:

# The above copyright notice and this permission notice (including the
# next paragraph) shall be included in all copies or substantial
# portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE COPYRIGHT OWNER(S) AND/OR ITS SUPPLIERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

#  **********************************************************************/
#  * Authors:
#  *   Mark Janes <mark.a.janes@intel.com>
#  **********************************************************************/

"""handles command-line options to build.py, and makes them available to build routines"""
import argparse, os, sys
import xml.etree.cElementTree as et

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

class Options(object):
    def __init__(self, args=None, from_xml=None):
        self.prog = None
        self.component_dir = None

        description = "argument parser for mesa jenkins build wrapper"
        self._parser = argparse.ArgumentParser(description=description)

        self._parser.add_argument('--action', type=str, default=["build"],
                                  choices=CsvChoice('build', 'clean', 'test'),
                                  action=CsvAction,
                                  help="Action to recurse with. 'build', "
                                  "'clean' or 'test'. (default: %(default)s)")
        self._parser.add_argument('--config', type=str, default="debug", 
                                  choices=['release', 'debug'],
                                  help="Release or Debug build. (default: "
                                  "%(default)s)")
        self._parser.add_argument('--type', type=str, default="developer",
                                  choices=['developer', 'percheckin', 
                                           'daily', 'release'],
                                  help="The source of the build trigger. "
                                  "(default: %(default)s)")
        self._parser.add_argument('--arch', type=str, 
                                  default='m64', choices=['m64', 'm32'],
                                  help="The architecture for the target "
                                  "build. (default: %(default)s)")
        self._parser.add_argument('--hardware', type=str, default='builder',
                                  help="The hardware to be targeted for test "
                                  "('builder', 'snbgt1', 'ivb', 'hsw', 'bdw'). "
                                  "(default: %(default)s)")
        self._parser.add_argument('--result_path', type=str, default='',
                                  help="The location on the build master "
                                  "for placing and fetching built binaries.")
        self._parser.add_argument('--retest_path', type=str, default='',
                                  help="If specified, test actions only invoke "
                                  "failing tests at this result_path.")
        self._parser.add_argument('--shard', type=str, default="0",
                                  help="If specified, a fraction of tests will be executed.  "
                                  "EG: --shard=3:5 will divide the tests into 5 equal groups and "
                                  "execute the tess in the third group.")
        self._parser.add_argument('--env', type=str, default="",
                                  help="If specified, overrides environment variable settings"
                                  "EG: 'LIBGL_DEBUG=1 INTEL_DEBUG=perf'")

        if None != from_xml:
            self.from_xml(from_xml)
            return
        
        self.update_arg0(sys.argv[0])
        if args is not None:
            self.update_arg0(args[0])
            args = args[1:]

        # list out the members, so pylint doesn't get confused
        self.action = []
        self.arch = ""
        self.hardware = ""
        self.config = ""
        self.type = ""
        self.result_path = ""
        self.retest_path = ""
        self.shard = ""
        self.env = ""
        # Parse the args and explode it into the Options class
        self.__dict__.update(vars(self._parser.parse_args(args)))

    def to_string(self):
        return " ".join(self.to_list())

    def to_list(self):
        arglist = []
        arglist += ["--action", ','.join(self.action)]
        arglist += ["--arch", self.arch]
        arglist += ["--hardware", self.hardware]
        arglist += ["--config", self.config]
        arglist += ["--type", self.type]
        if self.result_path != "":
            arglist += ["--result_path", self.result_path]
        if self.retest_path != "":
            arglist += ["--retest_path", self.retest_path]
        if self.shard != "0":
            arglist += ["--shard", self.shard]
        if self.env:
            arglist += ["--env", self.env]
        return arglist

    def to_elementtree(self):
        tag = et.Element("Options")
        tag.set("action", ",".join(self.action))
        tag.set("arch", self.arch)
        tag.set("config", self.config)
        tag.set("hardware", self.hardware)
        tag.set("result_path", self.result_path)
        tag.set("retest_path", self.retest_path)
        tag.set("type", self.type)
        tag.set("shard", self.shard)
        tag.set("env", self.env)
        return tag

    def from_xml(self, xml):
        if type(xml) == str:
            xml = et.fromstring(xml)
        assert(xml.tag == "Options")
        self.action = xml.attrib["action"].split(",")
        self.arch = xml.attrib["arch"]
        self.config = xml.attrib["config"]
        self.hardware = xml.attrib["hardware"]
        self.result_path = xml.attrib["result_path"]
        self.retest_path = xml.attrib["retest_path"]
        self.type = xml.attrib["type"]
        self.shard = xml.attrib["shard"]
        self.env = xml.attrib["env"]

    def update_arg0(self, arg0=None):
        # We should really do better for this:
        self.prog = arg0
        self.component_dir = os.path.dirname(os.path.abspath(arg0))

    def update_env(self, env):
        if not self.env:
            return
        for avar in self.env.split(" "):
            if not avar:
                continue
            (varname, varval) = avar.split("=", 1)
            env[varname] = varval

class CustomOptions(object):
    def __init__(self, description="no description"):
        self._options = Options([sys.argv[0]])
        self._parser = argparse.ArgumentParser(description=description, 
                                               parents=[self._options._parser], 
                                               conflict_handler="resolve")
        self.extra_args = []
    def add_argument(self, arg, type=str, default="",
                     help="No help provided"):
        self._parser.add_argument(arg, type=type, default=default, help=help)
        self.extra_args.append(arg[2:])

    def parse_args(self):
        args = self._parser.parse_args()

        # record args in self, so they can be accessed
        vdict = vars(args)
        self.__dict__.update(vdict)

        # remove the extra args, and make a standard options object
        # that can be normally parsed.
        fixed_dict = vars(args)
        for extra in self.extra_args:
            del fixed_dict[extra]
        self._options.__dict__.update(fixed_dict)

        # update argv with the standard options.
        sys.argv = [sys.argv[0]] + self._options.to_list()
        
    
