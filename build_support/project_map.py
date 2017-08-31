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

import sys, os
import xml.etree.cElementTree as et
import pdb

from . import Options

class ProjectMap:
    """provides convenient and consistent access to paths which are
    necessary to the builds"""

    def __init__(self):
        """locate the build specification document, to use as a reference
        point for all other paths"""
        root = os.path.dirname(os.path.abspath(sys.argv[0]))
        if "py.test" in sys.argv[0]:
            root = os.getcwd()
        while True:
            build_spec = root + "/build_specification.xml"
            if not os.path.exists(build_spec):
                if (os.path.dirname(root) == root):
                    # we are at "/"
                    assert(False)
                    return

                root = os.path.dirname(root)
                continue

            # else we have found the spec
            self._source_root = root
            break
        # cache the current_project, because it can't be recalculated
        # if the caller changes directories.
        self._current_project = None
        self._current_project = self.current_project()

    def source_root(self):
        """top directory, which contains the build_specification.xml"""
        return self._source_root

    def build_root(self):
        """chroot directory where all results are placed during a build"""
        br = "/tmp/build_root/" + Options().arch
        if not os.path.exists(br):
            os.makedirs(br)
        return br

    def project_build_dir(self, project=None):
        """location of the build.py for the project"""
        if project is None:
            project = self._current_project
        cb = self._source_root + "/" + project + "/"
        return cb

    def project_source_dir(self, project=None):
        """location of the git repo for the project"""
        if project == None:
            project = self.current_project()
        spec = self.build_spec()
        projects_tag = spec.find("projects")
        projects = projects_tag.findall("project")
        for a_project in projects:
            if project != a_project.attrib["name"]:
                continue
            if a_project.attrib.has_key("src_dir"):
                sdir = self._source_root + "/repos/" + a_project.attrib["src_dir"]
                assert(os.path.exists(sdir))
                return sdir

        sdir = self._source_root + "/repos/" + project
        assert(os.path.exists(sdir))
        return sdir

    def current_project(self):
        """name of the project which is invoking this method"""
        if self._current_project:
            return self._current_project
        build_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        return os.path.split(build_dir)[1]

    def output_dir(self):
        """logs / test xml go in this directory"""
        o = Options()
        if o.result_path:
            return os.path.abspath(o.result_path + "/test")
        return self._source_root + "/results"

    def build_spec(self):
        return et.parse(self.source_root() + "/build_specification.xml")
