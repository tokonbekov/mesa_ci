#!/usr/bin/python

#import ConfigParser
import multiprocessing
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))
import build_support as bs

# needed to preserve case in the options
# class CaseConfig(ConfigParser.SafeConfigParser):
#     def optionxform(self, optionstr):
#         return optionstr

class GLCTSList(object):
    def __init__(self):
        self.pm = bs.ProjectMap()
        self.o = bs.Options()

    def tests(self, env=None):
        br = self.pm.build_root()
        libdir = "x86_64-linux-gnu"
        if self.o.arch == "m32":
            libdir = "i386-linux-gnu"
        env = {"MESA_GLES_VERSION_OVERRIDE" : "3.2",
               "LD_LIBRARY_PATH" : br + "/lib",
               "LIBGL_DRIVERS_PATH" : br + "/lib/dri",
               "MESA_GL_VERSION_OVERRIDE" : "4.6",
               "MESA_GLSL_VERSION_OVERRIDE" : "460"}
        self.o.update_env(env)

        savedir = os.getcwd()
        os.chdir(self.pm.build_root() + "/bin/gl/modules")
        bs.run_batch_command(["./glcts", "--deqp-runmode=xml-caselist"],
                             env=env)
        all_tests = bs.DeqpTrie()
        all_tests.add_xml("KHR-GL46-cases.xml")
        os.chdir(savedir)
        return all_tests

    def blacklist(self, all_tests):
        return all_tests

class GLCTSTester(object):
    def __init__(self):
        self.o = bs.Options()
        self.pm = bs.ProjectMap()

    def test(self):
        t = bs.DeqpTester()
        results = t.test(self.pm.build_root() + "/bin/gl/modules/glcts",
                         GLCTSList(),
                         env = {"MESA_GL_VERSION_OVERRIDE" : "4.6",
                                "MESA_GLSL_VERSION_OVERRIDE" : "460"})

        o = bs.Options()
        config = bs.get_conf_file(self.o.hardware, self.o.arch, project=self.pm.current_project())
        t.generate_results(results, bs.ConfigFilter(config, o))

    def build(self):
        pass
    def clean(self):
        pass

class SlowTimeout:
    def __init__(self):
        self.hardware = bs.Options().hardware

    def GetDuration(self):
        return 120

bs.build(GLCTSTester(), time_limit=SlowTimeout())
