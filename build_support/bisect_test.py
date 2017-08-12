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

import re
import os
import time
import xml.etree.ElementTree as ET
import ConfigParser

from . import RevisionSpecification
from . import Options
from . import ProjectMap
from . import Jenkins
from . import DependencyGraph
from . import ProjectInvoke
from . import BuildFailure


class NoConfigFile(Exception):
    pass


def get_conf_file(hardware, arch, project="piglit-test"):
    pm = ProjectMap()
    conf_dir = pm.source_root() + "/" + project + "/"
    if "glk" in hardware:
        conf_dir = pm.project_source_dir("prerelease") + "/" + project + "/"
    conf_file = conf_dir + "/" + hardware + arch + ".conf"
    if not os.path.exists(conf_file):
        conf_file = conf_dir + "/" + hardware + ".conf"

    if os.path.exists(conf_file):
        return conf_file

    if "gt" in hardware:
        # we haven't found a sku-specific conf, so strip the gtX
        # strings off of thef hardware and try again.
        return get_conf_file(hardware[:3], arch, project)

    raise NoConfigFile

class Bisector:
    def __init__(self, bisect_project, test,
                 commits, retest_path, bisect_dir):
        self.project = bisect_project
        self.test = test
        # remove inadvertent whitespace, which is easy to add when
        # triggering builds on jenkins
        self.test_name = test.test_name.strip()
        self.arch = test.arch
        self.hardware = test.hardware
        self.commits = commits
        self.last_failure = None
        self._retest_path=retest_path
        self._bisect_dir = bisect_dir

    def Bisect(self):
        if not self.commits:
            return
        current_build = len(self.commits) / 2
        repo_project = self.project
        if "piglit" in repo_project:
            repo_project = "piglit"
        if "crucible" in repo_project:
            repo_project = "crucible"
        if "vulkancts" in repo_project:
            repo_project = "vulkancts"
        rev = repo_project + "=" + self.commits[current_build].hexsha
        print "Range: " + self.commits[0].hexsha + " - " + self.commits[-1].hexsha + " (" + str(len(self.commits)) + ")"
        print "Building revision: " + rev

        o = Options(args=["ignore"])
        o.type = "developer"
        o.config = "debug"
        o.arch = self.arch
        o.hardware = self.hardware
        o.action = ["build", "test"]

        print "Bisector Bisect checking out: " + rev
        revspec = RevisionSpecification(from_cmd_line=[rev])
        revspec.checkout()
        revspec = RevisionSpecification()
        hashstr = revspec.to_cmd_line_param().replace(" ", "_")
        spec_xml = ProjectMap().build_spec()
        o.result_path = "/".join([self._bisect_dir, hashstr])
        o.retest_path = self._retest_path

        # if retest_path == result_path, then we don't have to build.
        # This will occur when bisect has reached the most recent
        # revision.  The newest revision was already
        # built/tested. before beginning the bisect.
        if (o.result_path != o.retest_path):
            global jen
            jen = Jenkins(result_path=o.result_path,
                          revspec=revspec)

            depGraph = DependencyGraph(self.test.project, o)
            try:
                jen.build_all(depGraph, "bisect", print_summary=False)
            except BuildFailure:
                print "BUILD FAILED - exception: " + rev
                if current_build + 1 == len(self.commits):
                    print "FIRST DETECTED FAILURE: " + rev
                    return rev
                self.last_failure = rev
                self.commits = self.commits[current_build+1:]
                return self.Bisect()

        if self.test.Passed(o.result_path, rev):
            if current_build == 0:
                print "LAST DETECTED SUCCESS: " + rev
                return self.last_failure
            self.commits = self.commits[:current_build]
            return self.Bisect()
        else:
            # test failed
            if current_build + 1 == len(self.commits):
                print "FIRST DETECTED FAILURE: " + rev
                return rev
            self.last_failure = rev
            self.commits = self.commits[current_build + 1:]
            return self.Bisect()


# needed to preserve case in the options
class CaseConfig(ConfigParser.SafeConfigParser):
    def optionxform(self, optionstr):
        return optionstr

preferred_hardware = {"skl"    : 1,
                      "sklgt2" : 2,
                      "sklgt4e": 3,
                      "bdw"    : 4, 
                      "bdwgt3e": 5, 
                      "bdwgt2" : 6, 
                      "hsw"    : 7, 
                      "hswgt3e": 8, 
                      "hswgt2" : 9, 
                      "hswgt1" : 10,
                      "ivb"    : 11,
                      "ivbgt2" : 12,
                      "ivbgt1" : 13,
                      "snb"    : 14,
                      "snbgt2" : 15,
                      "snbgt1" : 16,
                      "byt"    : 17,
                      "bsw"    : 18,
                      "bxt"    : 19,
                      "kbl"    : 20,
                      "kblgt2" : 21,
                      "glk"    : 22,
                      "g965"   : 23,
                      "ilk"    : 24,
                      "g33"    : 25, 
                      "g45"    : 26 }

class PiglitTest:
    """Represents a single test.  Has the primary arch that will be
    tested, and a list of other arches that are expected to be caused by
    the same revision"""
    preferred_arches = ["m64", "m32"]

    def __init__(self, full_test_name, status, test_tag=None, retest_path=""):
        """full_test_name includes arch/platform.  status must be one
        of "pass", "fail", "crash" """
        self.command_line = ""
        self.pid = None
        if test_tag is not None:
            full_test_name = test_tag.attrib["name"]
            full_test_name = test_tag.attrib["classname"] + "." + full_test_name
            full_test_name = full_test_name.replace("=", ".")
            full_test_name = full_test_name.replace(":", ".")
            failnode = test_tag.find("./failure")
            if failnode is not None:
                # assume fail type is crash if the type attribute doesn't exist
                status = failnode.attrib.get("type", "crash")
            else:
                status = "crash"
            if status == "warn":
                # warn status is handled as pass in all cases
                status = "pass"

            system_out_node = test_tag.find("./system-out")
            if system_out_node is not None:
                self.command_line = system_out_node.text.splitlines()[0]

            system_err_node = test_tag.find("./system-err")
            if system_err_node is not None and system_err_node.text is not None:
                for a_line in system_err_node.text.splitlines():
                    m = re.match("pid: ([0-9]+)", a_line)
                    if m is not None:
                        self.pid = m.group(1)
                    else:
                        m = re.match("pid: \[([0-9]+)\]", a_line)
                        if m is not None:
                            self.pid = m.group(1)
                        
        self._retest_path = retest_path
        arch_hardware = full_test_name.split(".")[-1]
        arch = arch_hardware[-3:]
        hardware = arch_hardware[:-3]
        self.project = "piglit-test"
        if "piglit.deqp" in full_test_name.lower():
            self.project = "deqp-test"
        (first, second) = full_test_name.split(".")[0:2]
        if first == "piglit" and "-vk" in second:
            self.project = "vulkancts-test"
        if first == "piglit" and "-cts" in second:
            self.project = "cts-test"
        # only three sku's have sku-specific failures
        if "gt" in hardware and hardware != "ivbgt1" and hardware != "bdwgt3e" and hardware != "sklgt4e":
            hardware = hardware[:3]

        self.test_name = ".".join(full_test_name.split(".")[:-1])
        self.arch = arch
        self.hardware = hardware
        self.other_arches = []
        self.status = status
        self.bisected_revision = "unknown"


    def FailsPlatform(self, arch, hardware):
        if arch == self.arch and hardware == self.hardware:
            return True
        for (a,h) in self.other_arches:
            if arch == a and hardware == h:
                return True
        return False
        
    def AddTest(self, test):
        assert(test.test_name == self.test_name)
        if (test.status != self.status):
            print "WARNING: test status mismatch: " + self.test_name
            return

        primary_arch = self.arch
        primary_hw = self.hardware
        secondary_arch = test.arch
        secondary_hw = test.hardware

        swap_primary = False
        if self.arch == "m32" and test.arch == "m64":
            # m64 is preferred
            swap_primary = True

        if self.hardware not in preferred_hardware and test.hardware in preferred_hardware:
            # unknown platforms are not preferred
            swap_primary = True

        if ((self.hardware in preferred_hardware and test.hardware in preferred_hardware) and 
            preferred_hardware[self.hardware] > preferred_hardware[test.hardware]):
            # other platform has a higher precedence
            swap_primary = True

        if swap_primary:
            # else prefer faster platform
            primary_arch = test.arch
            primary_hw = test.hardware
            secondary_arch = self.arch
            secondary_hw = self.hardware
        
        self.other_arches.append((secondary_arch, secondary_hw))
        self.arch = primary_arch
        self.hardware = primary_hw

    def Print(self):
        print " ".join([self.project, self.test_name, self.arch, self.hardware,
                        self.status, str(self.other_arches)])

    def PrettyPrint(self, fh):
        fh.write("Project: " + self.project + "\n"
                 "Test: " + self.test_name + "\n"
                 "Status: " + self.status + "\n"
                 "Platform/arch:\n\t"+ self.hardware + "/" + self.arch)
        for arch, hw in self.other_arches:
            fh.write(", " + hw + "/" + arch)
        fh.write("\nCommand line: " + self.command_line + "\n\n")

    def Bisect(self, bisect_project, commits, bisect_dir):
        print "Bisecting for " + self.test_name
        b = Bisector(bisect_project, self, 
                     commits, self._retest_path, bisect_dir)
        self.bisected_revision = b.Bisect()
        if not self.bisected_revision:
            print "No bisection found for " + self.test_name
            return
        self.bisected_revision = self.bisected_revision.replace("=", " ")

    def GetConf(self, hardware=None, arch=None):
        if not hardware:
            hardware = self.hardware
        if not arch:
            arch = self.arch
        return get_conf_file(hardware, arch, project=self.project)
        
    def UpdateConf(self):
        if not self.bisected_revision:
            return
        full_list = [(self.arch, self.hardware)] + self.other_arches
        for arch, hardware in full_list:
            try:
                conf_file = self.GetConf(hardware=hardware, arch=arch)
            except NoConfigFile:
                continue
            c = CaseConfig(allow_no_value=True)
            c.optionxform = str
            c.read(conf_file)

            # remove test from whatever section it might be in, and
            # add it back to the right place
            c.remove_option("expected-failures", self.test_name)
            c.remove_option("expected-crashes", self.test_name)
            c.remove_option("fixed-tests", self.test_name)
            if self.status == "fail":
                c.set("expected-failures", self.test_name, self.bisected_revision)
            elif self.status == "crash":
                c.set("expected-crashes", self.test_name, self.bisected_revision)
            elif self.status == "pass" or self.status == "skip":
                if not c.has_section("fixed-tests"):
                    c.add_section("fixed-tests")
                c.set("fixed-tests", self.test_name, self.bisected_revision)
            else:
                print conf_file + ": removed " + self.test_name

            c.write(open(conf_file, "w"))

    def GetConfRevision(self):
        try:
            conf_file = self.GetConf()
        except NoConfigFile:
            return ''

        c = CaseConfig(allow_no_value=True)
        c.optionxform = str
        c.read(conf_file)
        for section in ["expected-failures", "expected-crashes", "fixed-tests"]:
            try:
                rev = c.get(section, self.test_name)
                if not rev:
                    rev = ""
                return rev
            except(ConfigParser.NoSectionError, ConfigParser.NoOptionError):
                pass
        return ""

    def Passed(self, result_path, rev):
        # returns true if the piglit test passed at the specified result_path
        base_name = self.project

        # not all result xmls are named by the project name.  Jenkins
        # results handling requires the filename to match piglit*xml,
        # so deqp-test names files "piglit-deqp.*.xml"
        if self.project == "deqp-test":
            base_name = "piglit-deqp"
        if self.project == "cts-test":
            base_name = "piglit-cts"
        if self.project == "vulkancts-test":
            base_name = "piglit-deqp-vk"
        test_result = "/".join([result_path, "test", base_name + "_" +
                                self.hardware + "_" + self.arch + ".xml"])
        iteration = 0
        while not os.path.exists(test_result):
            if iteration < 140:
                time.sleep(1)
                iteration = iteration + 1
                continue
            print "BUILD FAILED - no test results: " + test_result
            return False

        result = ET.parse(test_result)
        for testcase in result.findall("./testsuite/testcase"):
            testname = testcase.attrib["classname"] + "." + testcase.attrib["name"]
            #strip off the arch/platform and drop the special characters
            testname = ".".join(testname.split(".")[:-1])
            testname = re.sub('[=:]', ".", testname)
            if self.test_name != testname:
                continue
            if testcase.findall("failure") or testcase.findall("error"):
                print "TEST FAILED: " + rev
                return False

            if testcase.findall("skipped"):
                print "INFO: the target test was skipped"
            print "TEST PASSED: " + rev
            return True

        print "ERROR -- TEST NOT FOUND, treating as success: " + rev + " " + self.test_name
        return True

    def ForcePass(self, result_file):
        result = ET.parse(result_file)
        for testcase in result.findall("./testsuite/testcase"):
            testname = testcase.attrib["classname"] + "." + testcase.attrib["name"]
            #strip off the arch/platform and drop the special characters
            testname = ".".join(testname.split(".")[:-1])
            testname = re.sub('[=:]', ".", testname)
            if self.test_name != testname:
                continue
            etags = testcase.findall("failure")
            for tag in etags:
                testcase.remove(tag)
            etags = testcase.findall("error")
            for tag in etags:
                testcase.remove(tag)
            stdout = testcase.find("system-out")
            if stdout is None:
                stdout = ET.Element("system-out")
                testcase.append(stdout)
            if stdout.text:
                stdout.text = stdout.text + "WARN: stripping flaky test."
            else:
                print "WARN: no output tag for stripped flaky test: " + testname
            break
        result.write(result_file)


    def RetestInclude(self):
        test_name_components = []
        # drop the spec
        for comp in self.test_name.split(".")[1:]:
            # reverse the "api" -> "api_" substitution that
            # allows tests to be shown in jenkins.
            if comp == "api_":
                test_name_components.append("api")
            else:
                test_name_components.append(comp)
        test_name = ".".join(test_name_components)
        test_name_good_chars = re.sub('[_ !:=()]', ".", test_name)
        return ["--include-tests", test_name_good_chars]

class CrucibleTest:
    """Represents a single test.  Has the primary arch that will be
    tested, and a list of other arches that are expected to be caused by
    the same revision"""

    def __init__(self, full_test_name, status, test_tag=None, retest_path=""):
        self.project = "crucible-test"
        self.pid = None
        self.test_tag = test_tag
        if test_tag is not None:
            full_test_name = test_tag.attrib["name"]
            status = test_tag.attrib["status"]
            if status == "lost":
                status = "crash"

        # drop the hw/arch from the test name
        self.test_name = ".".join(full_test_name.split(".")[:-1])
        self.status = status
        self._retest_path = retest_path

        hwarch = full_test_name.split(".")[-1]
        self.hardware = hwarch[:-3]
        self.arch = hwarch[-3:]

        self.other_arches = []

        self.bisected_revision = "unknown"

    def FailsPlatform(self, arch, hardware):
        if arch == self.arch and hardware == self.hardware:
            return self.status != "pass"
        if (arch, hardware) in self.other_arches:
            return self.status != "pass"
        return False
        
    def AddTest(self, test):
        assert(test.test_name == self.test_name)
        if test.status != self.status:
            print "WARN: skipping mismatched status for test: " + test.test_name

        primary_arch = self.arch
        primary_hw = self.hardware
        secondary_arch = test.arch
        secondary_hw = test.hardware
        if self.arch == "m32" and test.arch == "m64":
            # m64 is preferred
            primary_arch = test.arch
            primary_hw = test.hardware
            secondary_arch = self.arch
            secondary_hw = self.hardware
        elif ((self.hardware not in preferred_hardware and test.hardware in preferred_hardware) or
              # or if other test has more preferred hardware
              (preferred_hardware[self.hardware] > preferred_hardware[test.hardware])):
            # else prefer faster platform
            primary_arch = test.arch
            primary_hw = test.hardware
            secondary_arch = self.arch
            secondary_hw = self.hardware

        self.other_arches.append((secondary_arch, secondary_hw))
        self.arch = primary_arch
        self.hardware = primary_hw

    def Print(self):
        print " ".join(["crucible-test", self.test_name, self.arch, self.hardware,
                        self.status, str(self.other_arches)])

    def PrettyPrint(self, fh):
        fh.write("Project: " + self.project + "\n"
                 "Test: " + self.test_name + "\n"
                 "Status: " + self.status + "\n"
                 "Platform/arch:\n\t"+ self.hardware + "/" + self.arch)
        for arch, hw in self.other_arches:
            fh.write(", " + hw + "/" + arch)
        fh.write("\n\n")

    def Bisect(self, bisect_project, commits, bisect_dir):
        print "Bisecting for " + self.test_name
        b = Bisector(bisect_project, self, 
                     commits, self._retest_path, bisect_dir)
        self.bisected_revision = b.Bisect()
        if not self.bisected_revision:
            print "No bisection found for " + self.test_name
            return
        self.bisected_revision = self.bisected_revision.replace("=", " ")

    def GetConf(self, hardware=None, arch=None):
        if not hardware:
            hardware = self.hardware
        if not arch:
            arch = self.arch
        return get_conf_file(hardware, arch, project="crucible-test")
        
    def UpdateConf(self):
        full_list = [(self.arch, self.hardware)] + self.other_arches
        for arch, hardware in full_list:
            try:
                conf_file = self.GetConf(hardware=hardware, arch=arch)
            except NoConfigFile:
                continue
            c = CaseConfig(allow_no_value=True)
            c.optionxform = str
            c.read(conf_file)
            if not c.has_section("expected-failures"):
                c.add_section("expected-failures")
            if not c.has_section("expected-crashes"):
                c.add_section("expected-crashes")
            if not c.has_section("fixed-tests"):
                c.add_section("fixed-tests")

            # remove test from whatever section it might be in, and
            # add it back to the right place
            c.remove_option("expected-failures", self.test_name)
            c.remove_option("expected-crashes", self.test_name)
            c.remove_option("fixed-tests", self.test_name)
            if self.status == "fail":
                c.set("expected-failures", self.test_name, self.bisected_revision)
            elif self.status == "crash":
                c.set("expected-crashes", self.test_name, self.bisected_revision)
            elif self.status == "pass":
                c.set("fixed-tests", self.test_name, self.bisected_revision)
            elif self.status == "skip":
                c.set("fixed-tests", self.test_name, self.bisected_revision)
            else:
                print "Error, unexpected status: " + self.status
                assert(False)

            c.write(open(conf_file, "w"))

    def GetConfRevision(self):
        try:
            conf_file = self.GetConf()
        except NoConfigFile:
            return ''

        c = CaseConfig(allow_no_value=True)
        c.optionxform = str
        c.read(conf_file)
        for section in ["expected-failures", "expected-crashes", "fixed-tests"]:
            try:
                rev = c.get(section, self.test_name)
                if not rev:
                    rev = ""
                return rev
            except(ConfigParser.NoSectionError, ConfigParser.NoOptionError):
                pass
        return ""

    def Passed(self, result_path, rev):
        # returns true if the crucible test passed at the specified result_path
        test_result = "/".join([result_path, "test", "piglit-crucible_" +
                                self.hardware + "_" + self.arch + ".xml"])
        iteration = 0
        while not os.path.exists(test_result):
            if iteration < 140:
                time.sleep(1)
                iteration = iteration + 1
                continue
            print "BUILD FAILED - no test results: " + test_result
            return False

        result = ET.parse(test_result)
        for testcase in result.findall("./testsuite/testcase"):
            testname = testcase.attrib["name"]
            #strip off the arch/platform
            testname = ".".join(testname.split(".")[:-1])
            if self.test_name != testname:
                continue
            if testcase.findall("failure") or testcase.findall("error"):
                print "TEST FAILED: " + rev
                return False

            if testcase.findall("skipped"):
                print "INFO: the target test was skipped"
            print "TEST PASSED: " + rev
            return True

        print "ERROR -- TEST NOT FOUND, treating as success: " + rev + " " + self.test_name
        return True

    def ForcePass(self, result_file):
        pass

    def RetestInclude(self):
        return [self.test_name]


class DeqpTest:
    """Represents a single test.  Has the primary arch that will be
    tested, and a list of other arches that are expected to be caused by
    the same revision"""

    def __init__(self, full_test_name, status, test_tag=None, retest_path=""):
        # TODO(majanes) figure out how to connect test to project
        self.pid = None
        self.test_tag = test_tag
        if test_tag is not None:
            full_test_name = test_tag.attrib["classname"] + "." + test_tag.attrib["name"]
            status = test_tag.attrib["status"]
            system_err_node = test_tag.find("./system-err")
            if system_err_node is not None and system_err_node.text is not None:
                for a_line in system_err_node.text.splitlines():
                    m = re.match("pid: ([0-9]+)", a_line)
                    if m is not None:
                        self.pid = m.group(1)

        # drop the hw/arch from the test name
        self.test_name = ".".join(full_test_name.split(".")[:-1])
        self.status = status
        self._retest_path = retest_path
        self.project = "glescts-test"
        if "dEQP-VK" in self.test_name:
            self.project = "vulkancts-test"
        if "dEQP-GL" in self.test_name:
            self.project = "deqp-test"
        if "dEQP-EGL" in self.test_name:
            self.project = "deqp-test"

        hwarch = full_test_name.split(".")[-1]
        self.hardware = hwarch[:-3]
        self.arch = hwarch[-3:]

        self.other_arches = []

        self.bisected_revision = "unknown"

    def FailsPlatform(self, arch, hardware):
        if arch == self.arch and hardware == self.hardware:
            return self.status != "pass" and self.status != "skip"
        if (arch, hardware) in self.other_arches:
            return self.status != "pass" and self.status != "skip"
        return False
        
    def AddTest(self, test):
        assert(test.test_name == self.test_name)
        if test.status != self.status:
            print "WARN: skipping mismatched status for test: " + test.test_name

        primary_arch = self.arch
        primary_hw = self.hardware
        secondary_arch = test.arch
        secondary_hw = test.hardware
        if self.arch == "m32" and test.arch == "m64":
            # m64 is preferred
            primary_arch = test.arch
            primary_hw = test.hardware
            secondary_arch = self.arch
            secondary_hw = self.hardware
        elif ((self.hardware not in preferred_hardware and test.hardware in preferred_hardware) or
              # or if other test has more preferred hardware
              (preferred_hardware[self.hardware] > preferred_hardware[test.hardware])):
            # else prefer faster platform
            primary_arch = test.arch
            primary_hw = test.hardware
            secondary_arch = self.arch
            secondary_hw = self.hardware

        self.other_arches.append((secondary_arch, secondary_hw))
        self.arch = primary_arch
        self.hardware = primary_hw

    def Print(self):
        print " ".join([self.project, self.test_name, self.arch, self.hardware,
                        self.status, str(self.other_arches)])

    def PrettyPrint(self, fh):
        fh.write("Project: " + self.project + "\n"
                 "Test: " + self.test_name + "\n"
                 "Status: " + self.status + "\n"
                 "Platform/arch:\n\t"+ self.hardware + "/" + self.arch)
        for arch, hw in self.other_arches:
            fh.write(", " + hw + "/" + arch)
        fh.write("\n\n")

    def Bisect(self, bisect_project, commits, bisect_dir):
        print "Bisecting for " + self.test_name
        b = Bisector(bisect_project, self, 
                     commits, self._retest_path, bisect_dir)
        self.bisected_revision = b.Bisect()
        if not self.bisected_revision:
            print "No bisection found for " + self.test_name
            return
        self.bisected_revision = self.bisected_revision.replace("=", " ")

    def GetConf(self, hardware=None, arch=None):
        if not hardware:
            hardware = self.hardware
        if not arch:
            arch = self.arch
        return get_conf_file(hardware, arch, project=self.project)
        
    def UpdateConf(self):
        full_list = [(self.arch, self.hardware)] + self.other_arches
        for arch, hardware in full_list:
            try:
                conf_file = self.GetConf(hardware=hardware, arch=arch)
            except NoConfigFile:
                continue
            c = CaseConfig(allow_no_value=True)
            c.optionxform = str
            c.read(conf_file)
            if not c.has_section("expected-failures"):
                c.add_section("expected-failures")
            if not c.has_section("expected-crashes"):
                c.add_section("expected-crashes")
            if not c.has_section("fixed-tests"):
                c.add_section("fixed-tests")

            # remove test from whatever section it might be in, and
            # add it back to the right place
            c.remove_option("expected-failures", self.test_name)
            c.remove_option("expected-crashes", self.test_name)
            c.remove_option("fixed-tests", self.test_name)
            if self.status == "fail":
                c.set("expected-failures", self.test_name, self.bisected_revision)
            elif self.status == "crash":
                c.set("expected-crashes", self.test_name, self.bisected_revision)
            elif self.status == "pass" or self.status == "skip":
                c.set("fixed-tests", self.test_name, self.bisected_revision)
            else:
                assert(False)

            c.write(open(conf_file, "w"))

    def GetConfRevision(self):
        try:
            conf_file = self.GetConf()
        except NoConfigFile:
            return ''

        c = CaseConfig(allow_no_value=True)
        c.optionxform = str
        c.read(conf_file)
        for section in ["expected-failures", "expected-crashes", "fixed-tests"]:
            try:
                rev = c.get(section, self.test_name)
                if not rev:
                    rev = ""
                return rev
            except(ConfigParser.NoSectionError, ConfigParser.NoOptionError):
                pass
        return ""

    def Passed(self, result_path, rev):
        # returns true if the dEQP test passed at the specified result_path
        base_name = "piglit-glescts-test_"
        if self.project == "deqp-test":
            base_name = "piglit-deqp-test_"
        if self.project == "vulkancts-test":
            base_name = "piglit-vulkancts-test_"

        test_result = "/".join([result_path, "test", base_name +
                                self.hardware + "_" + self.arch + "_0.xml"])
        iteration = 0
        while not os.path.exists(test_result):
            if iteration < 140:
                time.sleep(1)
                iteration = iteration + 1
                continue
            print "BUILD FAILED - no test results: " + test_result
            return False

        result = ET.parse(test_result)
        for testcase in result.findall("./testsuite/testcase"):
            full_test_name = testcase.attrib["classname"] + "." + testcase.attrib["name"]
            # drop the hw/arch from the test name
            testname = ".".join(full_test_name.split(".")[:-1])
            if self.test_name != testname:
                continue
            if testcase.findall("failure") or testcase.findall("error"):
                print "TEST FAILED: " + rev
                return False

            if testcase.findall("skipped"):
                print "INFO: the target test was skipped"
            print "TEST PASSED: " + rev
            return True

        print "ERROR -- TEST NOT FOUND, treating as success: " + rev + " " + self.test_name
        return True

    def ForcePass(self, result_file):
        assert(False)

    def RetestInclude(self):
        return [self.test_name]
    
class TestLister:
    """reads xml files and generates a set of PiglitTest objects"""
    def __init__(self, bad_dir, include_passes=False):
        self._include_passes = include_passes
        self._tests = {}
        # each test map is keyed by test name, value is PiglitTest
        self._tests["piglit-test"] = {}
        self._tests["deqp-test"] = {}
        self._tests["cts-test"] = {}
        self._tests["crucible-test"] = {}
        self._tests["vulkancts-test"] = {}
        self._tests["glescts-test"] = {}

        test_files = []
        if os.path.isfile(bad_dir):
            self._retest_path = os.path.abspath(bad_dir + "/../..")
            self._add_tests(bad_dir)
            return

        self._retest_path = os.path.abspath(bad_dir + "/..")
        # sometimes the test directory is not available, so wait for it.
        count = 0
        while not os.path.exists(bad_dir):
            print "sleeping, waiting for " + bad_dir
            print " ".join(os.listdir(self._retest_path))
            time.sleep(10)
            count += 1
            if count > 10:
                break
        if not os.path.exists(bad_dir):
            return
        test_files = [bad_dir + "/" + f for f in os.listdir(bad_dir)]
        for a_file in test_files:
            if ("piglit-test" not in a_file and
                "piglit-vulkancts-test" not in a_file and
                "piglit-cpu-test" not in a_file and
                "piglit-cts" not in a_file and
                "piglit-crucible" not in a_file and
                "piglit-deqp" not in a_file and
                "piglit-glescts" not in a_file):
                continue
            self._add_tests(a_file)

    def _add_tests(self, test_path):
        t = ET.parse(test_path)
        r = t.getroot()

        testclass = PiglitTest
        if "crucible" in os.path.basename(test_path):
            testclass = CrucibleTest
        if "glescts" in os.path.basename(test_path):
            testclass = DeqpTest
        if "vulkancts" in os.path.basename(test_path):
            testclass = DeqpTest
        if "deqp" in os.path.basename(test_path):
            testclass = DeqpTest

        tags = r.findall(".//failure/..") + r.findall(".//error/..")
        if self._include_passes:
            tags = r.findall(".//testcase")
        for afail in tags:
            test = testclass(full_test_name="unknown", 
                             status="unknown",
                             test_tag=afail,
                             retest_path=self._retest_path)

            project = test.project
            name = test.test_name
            if name not in self._tests[project]:
                self._tests[project][name] = test
                continue
            self._tests[project][name].AddTest(test)

    def Print(self):
        for project in self._tests.values():
            for test in project.values():
                test.Print()

    def Tests(self, project=None):
        tests = []
        projects = self._tests.values()
        if project:
            projects = [ self._tests[project] ]
        for project in projects:
            tests = tests + project.values()
        return tests

    def TestsNotIn(self, other_test_list):
        out_list = []
        for (project, tests) in self._tests.items():
            for (name, test) in tests.items():
                if name not in other_test_list._tests[project]:
                    out_list.append(test)
                    continue
                other_test = other_test_list._tests[project][name]
                if other_test.arch != test.arch or other_test.hardware != test.hardware:
                    # didn't get the same primary failure.  It's likely
                    # that the test was marked as fixed for only one
                    # platform
                    out_list.append(test)
                    continue
        return out_list

    def RetestIncludes(self, project):
        # return a list of --include-tests parameters that allows
        # failures to be retested
        include_tests = []
        for atest in self.Tests(project=project):
            include_tests = include_tests + atest.RetestInclude()
        return include_tests

    def TestForPid(self, pid):
        for atest in self.Tests():
            if atest.pid == pid:
                return atest.test_name
            

def retest_failures(old_build_path, new_build_path):
    # generate a list of the projects that have to be tested
    test_projects = []
    tl = TestLister(old_build_path + "/test")
    for atest in tl.Tests():
        if atest.project not in test_projects:
            test_projects.append(atest.project)

    if not test_projects:
        print "ERROR: no failures to retest"
        return False

    # generate a list of build invokes for the retests
    spec_xml = ProjectMap().build_spec()
    spec_projects = spec_xml.find("projects")
    project_tags = {}
    for aproject_tag in spec_projects.findall("project"):
        project_tags[aproject_tag.attrib["name"]] = aproject_tag

    dg = DependencyGraph([], Options(args=["ignore"]))
    for atest in test_projects:
        project_tag = project_tags[atest]

        arches = ["m64"]
        if "bisect_arch" in project_tag.attrib:
            arches = project_tag.attrib["bisect_arch"].split(",")

        platforms = project_tag.attrib["bisect_hardware"].split(",")
        for arch in arches:
            for hardware in platforms:
                o = Options(args=["ignore"])
                o.type = "developer"
                o.config = "debug"
                o.arch = arch
                o.hardware = hardware
                o.action = ["build", "test"]
                o.result_path = new_build_path
                o.retest_path = old_build_path
                dg.add_to_graph(ProjectInvoke(project = atest, options = o))

    Jenkins(RevisionSpecification(), new_build_path).build_all(dg, print_summary=False)
    return True
