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
import multiprocessing
import os
import re
import socket
import subprocess
import sys
import time
import urllib2
import xml.etree.cElementTree as et
from . import Options
from . import ProjectMap
from . import run_batch_command
from . import rmtree
from . import Export
from . import GTest
from . import RepoSet
from . import PiglitTest
from . import ProjectInvoke
from . import Jenkins
from . import RevisionSpecification
from . import get_conf_file
from . import TestLister
from . import NoConfigFile


def mesa_version():
    br = ProjectMap().build_root()
    libdir = "x86_64-linux-gnu"
    if Options().arch == "m32":
        libdir = "i386-linux-gnu"
    wflinfo =  br + "/bin/wflinfo"
    env = { "LD_LIBRARY_PATH" : br + "/lib:" + br + "/lib/" + libdir + ":" + br + "/lib/dri:" + br + "/lib/piglit/lib",

                "LIBGL_DRIVERS_PATH" : br + "/lib/dri",
            "GBM_DRIVERS_PATH" : br + "/lib/dri"
    }
    (out, _) = run_batch_command([wflinfo,
                                 "--platform=gbm", "-a", "gl"],
                                 streamedOutput=False, env=env)
    for a_line in out.splitlines():
        if "OpenGL version string" not in a_line:
            continue
        tokens = a_line.split(":")
        assert len(tokens) == 2
        version_string = tokens[1].strip()
        version_tokens = version_string.split()
        assert len(version_tokens) >= 3
        return version_tokens[2]

def cpu_count():
    cpus = multiprocessing.cpu_count() + 1
    if cpus > 18:
        cpus = 18
    return cpus

def get_package_config_path():
    lib_dir = ""
    if Options().arch == "m32":
        lib_dir = "i386-linux-gnu"
    else:
        lib_dir = "x86_64-linux-gnu"

    build_root = ProjectMap().build_root()
    pkg_config_path = build_root + "/lib/" + lib_dir + "/pkgconfig:" + \
                      build_root + "/lib/pkgconfig:" + \
                      "/usr/lib/"+ lib_dir + "/pkgconfig:" + \
                      "/usr/lib/pkgconfig"
    return pkg_config_path

def delete_src_pyc(path):
    for dirpath, _, filenames in os.walk(path):
        for each_file in filenames:
            if each_file.endswith('.pyc'):
                if os.path.exists(os.path.join(dirpath, each_file)):
                    os.remove(os.path.join(dirpath, each_file))

def git_clean(src_dir):
    savedir = os.getcwd()
    os.chdir(src_dir)
    run_batch_command(["git", "clean", "-xfd"])
    run_batch_command(["git", "reset", "--hard", "HEAD"])
    os.chdir(savedir)

def check_gpu_hang(identify_test=True):
    # some systems have a gpu hang watchdog which reboots
    # machines, and others do not.   This method checks dmesg,
    # produces a failing test if a hang is found, and schedules a
    # reboot if the host is determined to be a jenkins builder
    # (user=jenkins)
    if os.name == "nt":
        return
    try:
        (out, _) = run_batch_command(["dmesg", "--time-format", "iso"],
                                     quiet=True,
                                     streamedOutput=False)
    except:
        return
    hang_text = ""
    for a_line in out.split('\n'):
        if "gpu hang" in a_line.lower():
            hang_text = a_line
            break
        if "*error* ring create req" in a_line.lower():
            hang_text = a_line
            break
        if "unable to purge gpu memory due lock contention" in a_line.lower():
            hang_text = a_line
            break
    if not hang_text:
        return False

    print "ERROR: gpu hang found: " + hang_text
    print "ERROR: system must be rebooted."

    # obtain the pid from the hang_text
    br = ProjectMap().build_root()
    m = re.search(r"\[([0-9]+)\]", hang_text)
    if m is not None and identify_test:
        pid = m.group(1)
        test_path = os.path.abspath(br + "/../test")
        test = TestLister(test_path, include_passes=True).TestForPid(pid)
        if test is not None:
            hang_text += "\nHanging Test:\n" + test
        
    hostname = socket.gethostname()
    Export().create_failing_test("gpu-hang-" + hostname,
                                 hang_text)
    test_path = os.path.abspath(br + "/../test/")
    if not os.path.exists(test_path):
        os.makedirs(test_path)
    try:
        run_batch_command(["sudo", "/usr/local/bin/copy_error_state.sh", test_path + "/card_error_" + hostname, "jenkins"])
    except:
        print "WARN: failed to capture error state"
    
    # trigger reboot
    if ('otc-gfx' in hostname):
        label = hostname[len('otc-gfxtest-'):]
        server = ProjectMap().build_spec().find("build_master").attrib["host"]
        url = "http://" + server + "/job/reboot_single/buildWithParameters?token=noauth&label=" + label
        print "opening: " + url
        urllib2.urlopen(url)
        print "sleeping to allow reboot job to be scheduled."
        time.sleep(120)
    return True
        
class AutoBuilder(object):

    def __init__(self, o=None, configure_options=None, export=True,
                 opt_flags=""):
        self._options = o
        self._tests = None
        self._export = export
        self._opt_flags = opt_flags

        self._configure_options = configure_options
        if not configure_options:
            self._configure_options = []

        if not o:
            self._options = Options()

        self._project_map = ProjectMap()
        project = self._project_map.current_project()
        self._project = project

        self._src_dir = self._project_map.project_source_dir(project)
        self._build_root = self._project_map.build_root()
        self._build_dir = self._src_dir + "/build_" + self._options.arch

        self._env = {}
        self._options.update_env(self._env)

    def build(self):
        if not os.path.exists(self._build_root):
            os.makedirs(self._build_root)
        if not os.path.exists(self._build_dir):
            os.makedirs(self._build_dir)

        optflags = self._opt_flags
        if self._options.config != "debug":
            optflags = "-O2 -DNDEBUG"
            
        savedir = os.getcwd()
        pkg_config = get_package_config_path()
        os.chdir(self._build_dir)
        flags = []
        if self._options.arch == "m32":
            flags = ["CFLAGS=-m32 -msse -msse2 " + optflags,
                     "CXXFLAGS=-m32 -msse -msse2 " + optflags, 
                     "--enable-32-bit",
                     "--host=i686-pc-linux-gnu"]
        else:
            flags = ["CFLAGS=-m64 " + optflags,
                     "CXXFLAGS=-m64 " + optflags]

        os.chdir(self._src_dir)
        run_batch_command(["autoreconf", "--verbose", "--install", "-s"], env=self._env)
        os.chdir(self._build_dir)
        run_batch_command([self._src_dir + "/configure", 
                           "PKG_CONFIG_PATH=" + pkg_config, 
                           "CC=ccache gcc -" + self._options.arch, 
                           "CXX=ccache g++ -" + self._options.arch, 
                           "--prefix=" + self._build_root] + \
                          flags + self._configure_options, env=self._env)

        run_batch_command(["make",  "-j", 
                           str(cpu_count())], env=self._env)
        run_batch_command(["make",  "install"])

        os.chdir(savedir)

        if self._export:
            Export().export()

    def SetGtests(self, tests):
        self._tests = GTest(binary_dir = self._build_dir, executables=tests)

    def test(self):
        savedir = os.getcwd()
        os.chdir(self._build_dir)

        try:
            run_batch_command(["make",  "-k", "-j", 
                               str(cpu_count()),
                               "check"], env=self._env)
        except(subprocess.CalledProcessError):
            print "WARN: make check failed"
            os.chdir(savedir)
            # bug 91773
            # Export().create_failing_test(self._project +
            #                              "-make-check-failure", "")
        os.chdir(savedir)

        if self._tests:
            self._tests.run_tests()

        if self._export:
            Export().export()

    def clean(self):
        git_clean(self._src_dir)
        if self._build_dir != self._src_dir:
            rmtree(self._build_dir)
            assert(not os.path.exists(self._build_dir))

class CMakeBuilder(object):
    def __init__(self, extra_definitions=None, compiler="gcc", install=True):
        self._options = Options()
        self._project_map = ProjectMap()
        self._compiler = compiler
        self._install = install

        if not extra_definitions:
            extra_definitions = []
        self._extra_definitions = extra_definitions

        project = self._project_map.current_project()

        self._src_dir = self._project_map.project_source_dir(project)
        self._build_root = self._project_map.build_root()
        self._build_dir = self._src_dir + "/build_" + self._options.arch

    def build(self):

        if not os.path.exists(self._build_dir):
            os.makedirs(self._build_dir)

        pkg_config = get_package_config_path()
        savedir = os.getcwd()
        os.chdir(self._build_dir)

        cflag = "-m32"
        cxxflag = "-m32"
        if self._options.arch == "m64":
            cflag = "-m64"
            cxxflag = "-m64"
        env={"PKG_CONFIG_PATH" : pkg_config,
             "CC":"ccache gcc",
             "CXX":"ccache g++",
             "CFLAGS":cflag,
             "CXXFLAGS":cxxflag}
        if self._compiler == "clang":
            env={"PKG_CONFIG_PATH" : pkg_config,
                 "CC":"clang",
                 "CXX":"clang++",
                 "CFLAGS":cflag,
                 "CXXFLAGS":cxxflag}
        self._options.update_env(env)
        run_batch_command(["cmake", "-GNinja", self._src_dir, 
                           "-DCMAKE_INSTALL_PREFIX:PATH=" + self._build_root] \
                          + self._extra_definitions, env=env)

        run_batch_command(["ninja", "-j" + str(cpu_count())], env=env)
        if self._install:
            print "Installing: output suppressed"
            run_batch_command(["ninja", "install"], streamedOutput=False, quiet=True)

        os.chdir(savedir)

        Export().export()

    def clean(self):
        git_clean(self._src_dir)
        rmtree(self._build_dir)
        assert(not os.path.exists(self._build_dir))
        
    def test(self):
        savedir = os.getcwd()
        os.chdir(self._build_dir)

        env = {}
        self._options.update_env(env)

        # get test names
        command = ["ctest", "-V", "-N"]
        (out, _) = run_batch_command(command, streamedOutput=False, quiet=True, env=env)

        os.chdir(savedir)

        out = out.splitlines()
        for aline in out:
            # execute each command reported by ctest
            match = re.match(".*Test command: (.*)", aline)
            if not match:
                continue
            (bin_dir, exe) = os.path.split(match.group(1))
            #bs.GTest(bin_dir, exe, working_dir=bin_dir).run_tests()

class MesonBuilder(object):

    def __init__(self, extra_definitions=None, compiler="gcc", install=True):
        self._options = Options()
        self._project_map = ProjectMap()
        self._compiler = compiler
        self._install = install
        self._extra_definitions = extra_definitions or []

        project = self._project_map.current_project()

        self._src_dir = self._project_map.project_source_dir(project)
        self._build_root = self._project_map.build_root()
        self._build_dir = os.path.join(self._src_dir, "build_" + self._options.arch)

    def build(self):
        if not os.path.exists(self._src_dir + "/meson.build"):
            return
        env = {
            'PKG_CONFIG_PATH': get_package_config_path(),
            'CC': 'gcc' if self._compiler != 'clang' else 'clang',
            'CXX': 'g++' if self._compiler != 'clang' else 'clang++',
            'CFLAGS': '-m64' if self._options.arch == 'm64' else '-m32',
            'CXXFLAGS': '-m64' if self._options.arch == 'm64' else '-m32',
        }
        self._options.update_env(env)

        returnto = os.getcwd()
        os.chdir(self._src_dir)

        run_batch_command(['meson', self._build_dir, '--prefix', self._build_root] +
                          self._extra_definitions, env=env)
        run_batch_command(['ninja', '-C', self._build_dir])
        if self._install:
            print "Installing: output suppressed"
            run_batch_command(['ninja', '-C', self._build_dir, 'install'],
                              streamedOutput=False, quiet=True)

        os.chdir(returnto)

        Export().export()

    def test(self):
        return

    def clean(self):
        git_clean(self._src_dir)
        rmtree(self._build_dir)
        assert not os.path.exists(self._build_dir)

class PiglitTester(object):
    def __init__(self, _suite="quick", device_override=None, piglit_test=None):
        self.device_override = device_override
        self._piglit_test = None
        if piglit_test:
            # drop the hw/arch suffix
            self._piglit_test = ".".join(piglit_test.split(".")[:-1])

        o = Options()
        self.suite = _suite

        # in bisect or single_test, a test may be in either the cpu or gpu suite.
        # use the quick suite, which is more comprehensive
        if o.retest_path:
            self.suite = "quick"
        if piglit_test:
            self.suite = "quick"

        pm = ProjectMap()
        self.build_root = pm.build_root()
        libdir = "x86_64-linux-gnu"
        if o.arch == "m32":
            libdir = "i386-linux-gnu"
        self.env = { "LD_LIBRARY_PATH" : self.build_root + "/lib:" + \
                     self.build_root + "/lib/" + libdir + ":" + \
                     self.build_root + "/lib/dri:" + \
                     self.build_root + "/lib/piglit/lib",

                     "LIBGL_DRIVERS_PATH" : self.build_root + "/lib/dri",
                     "GBM_DRIVERS_PATH" : self.build_root + "/lib/dri",
                     # fixes dxt subimage tests that fail due to a
                     # combination of unreasonable tolerances and possibly
                     # bugs in debian's s2tc library.  Recommended by nroberts
                     "S2TC_DITHER_MODE" : "NONE",

                     # In the event of a piglit related bug, we want the backtrace
                     "PIGLIT_DEBUG": "1",

                     # Set the path to include buildroot/bin so fast skipping works
                     'PATH': '{}:{}'.format(os.path.join(self.build_root, 'bin'),
                                            os.environ['PATH'])
        }
        if "hsw" in o.hardware or "byt" in o.hardware or "ivb" in o.hardware:
            self.env["MESA_GLES_VERSION_OVERRIDE"] = "3.1"

    def test(self):
        pm = ProjectMap()
        o = Options()

        mv = mesa_version()
        if o.hardware == "bxt" or o.hardware == "kbl":
            if "11.0" in mv:
                print "WARNING: bxt not supported by stable mesa"
                return

        if o.hardware == "sklgt4e":
            if "12" in mv:
                print "WARNING: sklgt4e not supported by mesa 12"
                return

        if o.hardware == "glk":
            if "12" in mv or "13.0" in mv:
                print "WARNING: glk not supported by stable mesa"
                return

        dev_ids = { "byt" : "0x0F32",
                    "g45" : "0x2E22",
                    "g965" : "0x29A2",
                    "ilk" : "0x0042",
                    "ivbgt2" : "0x0162",
                    "snbgt2" : "0x0122",
                    "hswgt3" : "0x042A",
                    "bdwgt2" : "0x161E",
                    "chv" : "0x22B0",
                    "sklgt3" : "0x192B",
                    "bsw" : "0x22B1",
        }
        if self.device_override:
            self.env["INTEL_DEVID_OVERRIDE"] = dev_ids[self.device_override]

        o.update_env(self.env)

        out_dir = self.build_root + "/test/" + o.hardware

        hardware = o.hardware
        if self.device_override:
            hardware = self.device_override

        try:
            conf_file = get_conf_file(hardware, o.arch)
        except NoConfigFile:
            print >>sys.stderr, 'No config file found for hardware: {0} arch: {1}'.format(
                hardware, o.arch)
            sys.exit(1)
        
        suffix = o.hardware
        hardware = o.hardware
        if self.device_override:
            suffix = self.device_override
            hardware = self.device_override
        cmd = [self.build_root + "/bin/piglit",
               "run",
               "-o",
               "-p", "gbm",
               "-b", "junit",
               "--junit_suffix", "." + suffix + o.arch,

               # intermittently fails snb?
               "--exclude-tests", "timestamp-get",
               "--exclude-tests", "glsl-routing",

               # fails intermittently
               "--exclude-tests", "ext_timer_query",
               "--exclude-tests", "arb_timer_query",

               # crashes intermittently, or at least Dylan's tracking
               # reports "Incomplete run"
               # TODO: write bug
               "--exclude-tests", "spec.khr_debug.object-label_gl",

               # fails intermittently on bdw, byt, and bsw
               # Bug 91017
               "--exclude-tests", "arb_framebuffer_no_attachments.arb_framebuffer_no_attachments-atomic",
               
               # fails intermittently on g45, fails reliably on all
               # others.  Test introduced Oct 2014
               "--exclude-tests", "vs-float-main-return"]

        if os.path.exists(conf_file):
            cmd = cmd + ["--config", conf_file]


        # intermittent on at least snbgt1
        exclude_tests = ["glsl-1_10.execution.vs-vec2-main-return"]

        if o.arch == "m32":
            exclude_tests += ["opengl.1_2.tex3d-maxsize",
                              "shaders.glsl-max-varyings"]

            # https://bugs.freedesktop.org/show_bug.cgi?id=93542
            # It's not worth bisecting m32 piglit just for this test.
            exclude_tests += ["spec.arb_tessellation_shader.execution.tess_with_geometry",
                              "spec.arb_tessellation_shader.execution.quads"]

        # broken egl tests require X, and intermittently pass when run concurrently
        exclude_tests += ["spec.egl.1_4.eglquerysurface.egl",
                          "spec.egl_ext_client_extensions.conformance",
                          "spec.egl_khr_create_context",
                          "spec.egl_khr_get_all_proc_addresses",
                          "spec.egl_khr_surfaceless_context",
                          "spec.egl_mesa_configless_context",
                          "spec.egl_nok_swap_region",
                          "spec.egl_nok_texture_from_pixmap.basic",
                          "spec.egl.1_4.eglterminate.then.unbind.context",
                          "spec.egl_chromium_sync_control.conformance",
                          "spec.egl.1_4.largest.possible.eglcreatepbuffersurface",
                          "spec.egl.1_4.eglcreatepbuffersurface",
                          "spec.egl_khr_fence_sync.conformance",
                          "spec.egl_khr_gl_colorspace",
                          # https://bugs.freedesktop.org/show_bug.cgi?id=99265
                          "spec.egl_khr_gl_image.egl_khr_gl_renderbuffer_image-clear-shared-image.gl_depth_component24",
                          "spec.egl_khr_gl_image.egl_khr_gl_renderbuffer_image-clear-shared-image.gl_rgba"]

        # https://bugs.freedesktop.org/show_bug.cgi?id=97577
        exclude_tests += ["spec.ext_shader_samples_identical.glsl-es-3_10.compiler.all-functions_vert",
                          "spec.oes_shader_io_blocks.compiler.layout-location-aliasing_vert",
                          # flaky:
                          "spec.arb_shader_clock.execution.clock2x32"]
        
        # bogus test
        exclude_tests += ["arb_shader_image_load_store.execution.coherency-extra"]

        # Bug 95008
        exclude_tests += ["arb_sync.clientwaitsync-timeout"]

        # Bug 95009, 95012
        if "snb" in hardware:
            exclude_tests += ["amd_shader_trinary_minmax.execution.built-in-functions.gs-mid3",
                              "glsl-1_50.execution.built-in-functions.gs-op"]
        
        # Bug 94490
        if "ivbgt1" in hardware or "hsw" in hardware:
            exclude_tests += ["arb_buffer_storage.bufferstorage-persistent read"]

        # bug 96907
        exclude_tests += ["arb_gpu_shader5.arb_gpu_shader5-emitstreamvertex_nodraw"]

        if "hsw" in hardware:
            exclude_tests += [
                'ext_framebuffer_multisample.accuracy',
                'spec.arb_gpu_shader_fp64.execution.vs-double-uniform-array-direct-indirect-non-uniform-control-flow',
                'spec.arb_gpu_shader_fp64.execution.fs-double-uniform-array-direct-indirect-non-uniform-control-flow',
            ]



        if "snb" in hardware:
            # hangs snb
            exclude_tests = exclude_tests + ["triangle_strip_adjacency"]
            
        if "g965" in hardware:
            # intermittent GPU hang on g965
            exclude_tests = exclude_tests + ["arb_shader_texture_lod.execution.tex-miplevel-selection",
                                             # bug 92108
                                             "ext_framebuffer_object.fbo-maxsize",
                                             # Jason changed the status of this test, which used to crash.
                                             # g965 aperture size breaks this test. 
                                             "opengl.1_2.tex3d-maxsize",
                                             # fdo Bug 89398
                                             "glsl-1_20.execution.clipping.fixed-clip-enables",
                                             "glsl-1_10.execution.clipping.clip-plane-transformation pos_clipvert",
                                             # no bug yet (no bisection)
                                             "ext_framebuffer_multisample.enable-flag",
                                             # flaky
                                             "ext_framebuffer_multisample.accuracy",
                                             # bug 102594
                                             "nv_conditional_render.drawpixels",
                                             "nv_conditional_render.copypixels",
                                             "nv_conditional_render.clear",
                                             "nv_conditional_render.vertex_array"]

        if "bdw" in hardware:
            exclude_tests = exclude_tests + ["arb_shader_image_load_store.execution.basic-imagestore-from-uniform"]
            # TODO: write bug for
            exclude_tests = exclude_tests + ["variable-indexing.vs-output-array-vec4-index-wr-before-gs"]

        if "bdwgt3e" in hardware:
            exclude_tests += ["spec.arb_shader_clock.execution"]

        # kbl is same as skl, as a starting point
        if "skl" in hardware or "kbl" in hardware:
            # hard hangs skl
            exclude_tests = exclude_tests + ["ext_framebuffer_multisample.no-color"]
            # intermittent, TODO bug
            exclude_tests = exclude_tests + ["arb_tessellation_shader.execution.vs-tes-vertex"]

        if "skl" in hardware:
            # 93355
            exclude_tests = exclude_tests + ["ext_framebuffer_multisample.accuracy",
                                             # TODO: bug
                                             "arb_buffer_storage.bufferstorage-persistent",
                                             # bug 99509
                                             "arb_shader_image_load_store.qualifiers"]
            
        if "ivb" in hardware or "bxt" in hardware:
            # bug 96907
            exclude_tests += ["arb_gpu_shader5.arb_gpu_shader5-emitstreamvertex_nodraw"]

        if "ivb" in hardware:
            # flaky
            exclude_tests += ["arb_shader_image_load_store.invalid"]

        if "g33" in hardware:
            # flaky: piglit.spec.!opengl 1_1.getteximage-formats
            exclude_tests += ["opengl.1_1.getteximage-formats"]

        if "bxt" in hardware:
            exclude_tests += ["arb_compute_shader.execution.simple-barrier-atomics"]

        if "byt" in hardware:
            exclude_tests += ["ext_framebuffer_multisample.accuracy"]

        exclude_cmd = []
        for test in exclude_tests:
            fixed_test = test.replace('_', '.')
            fixed_test = fixed_test.replace(' ', '.')
            exclude_cmd = exclude_cmd + ["--exclude-tests", fixed_test]

        include_tests = []
        if o.retest_path:
            # only test items which previously failed
            include_tests = TestLister(o.retest_path + "/test/").RetestIncludes("piglit-test")
            if not include_tests:
                # we were supposed to retest failures, but there were none
                return

        if self._piglit_test:
            # support for running a single test
            include_tests = ["--include-tests", self._piglit_test]
            
        concurrency_options = ["-c"]
        if "DEQP_DETECT_GPU_HANG" in self.env:
            concurrency_options = ["-1", "-v"]
            
        streamedOutput = True
        if o.retest_path:
            streamedOutput = False
        (out, err) = run_batch_command(cmd + exclude_cmd + include_tests +
                                       concurrency_options + [self.suite, out_dir ],
                                       env=self.env,
                                       expected_return_code=None,
                                       streamedOutput=streamedOutput)
        if err and "There are no tests scheduled to run" in err:
            open(out_dir + "/results.xml", "w").write("<testsuites/>")

        single_out_dir = self.build_root + "/../test"
        if not os.path.exists(single_out_dir):
            os.makedirs(single_out_dir)

        final_file = single_out_dir + "_".join(["/" + pm.current_project(),
                                                hardware,
                                                o.arch]) + ".xml"
        if os.path.exists(out_dir + "/results.xml"):
            # obtain the set of revisions on master which are not on
            # the current branches.  This set represents the revisions
            # that should cause tests to be disregared.
            revisions = RepoSet().branch_missing_revisions()
            print "INFO: filtering tests from " + out_dir + "/results.xml"
            # Uniquely name all test files in one directory, for
            # jenkins
            self.filter_tests(revisions,
                              out_dir + "/results.xml",
                              final_file)

        if "bsw" == hardware:
            # run piglit again, to eliminate intermittent failures
            tl = TestLister(final_file)
            retests = tl.RetestIncludes("piglit-test")
            if retests:
                second_out_dir = out_dir + "/retest"
                print "WARN: retesting piglit to " + second_out_dir
                (out, err) = run_batch_command(cmd + exclude_cmd + retests +
                                               concurrency_options + [self.suite, second_out_dir ],
                                               env=self.env,
                                               expected_return_code=None,
                                               streamedOutput=streamedOutput)
                second_results = TestLister(second_out_dir + "/results.xml")
                for a_test in tl.TestsNotIn(second_results):
                    print "stripping flaky test: " + a_test.test_name
                    a_test.ForcePass(final_file)
                rmtree(second_out_dir)

        # create a copy of the test xml in the source root, where
        # jenkins can access it.
        cmd = ["cp", "-a", "-n",
               self.build_root + "/../test", pm.source_root()]
        run_batch_command(cmd)

        check_gpu_hang()
        Export().export_tests()

    def filter_tests(self, revisions, infile, outfile):
        """this functionality has been duplicated in deqp-test/build.py.  If
        it needs to change, then either change it everywhere or refactor out
        the duplication."""
        t = et.parse(infile)
        r = t.getroot()
        for a_suite in t.findall("testsuite"):
            # remove skipped tests, which uses ram on jenkins when
            # displaying and provides no value.  
            for a_skip in a_suite.findall("testcase/skipped/.."):
                if a_skip.attrib["status"] in ["crash", "fail"]:
                    continue
                a_suite.remove(a_skip)

            # for each failure, see if there is an entry in the config
            # file with a revision that was missed by a branch
            for afail in a_suite.findall("testcase/failure/..") + a_suite.findall("testcase/error/.."):
                piglit_test = PiglitTest("foo", "foo", afail)
                regression_revision = piglit_test.GetConfRevision()
                abbreviated_revisions = [a_rev[:6] for a_rev in revisions]
                for abbrev_rev in abbreviated_revisions:
                    if abbrev_rev in regression_revision:
                        print "stripping: " + piglit_test.test_name + " " + regression_revision
                        a_suite.remove(afail)
                        # a test may match more than one revision
                        # encoded in a comment
                        break

            # strip unneeded output from passing tests
            for apass in a_suite.findall("testcase"):
                if apass.attrib["status"] != "pass":
                    continue
                if apass.find("failure") is not None:
                    continue
                out_tag = apass.find("system-out")
                if out_tag is not None:
                    apass.remove(out_tag)
                err_tag = apass.find("system-err")
                if err_tag is not None and err_tag.text is not None:
                    found = False
                    for a_line in err_tag.text.splitlines():
                        m = re.match("pid: ([0-9]+)", a_line)
                        if m is not None:
                            found = True
                            err_tag.text = a_line
                            break
                    if not found:
                        apass.remove(err_tag)
                
        t.write(outfile)

    def build(self):
        pass

    def clean(self):
        pass

# mostly this is necessary because cts has no make install
class CtsBuilder(CMakeBuilder):
    def __init__(self, suite):
        self._suite = suite
        assert(suite == "gl" or suite == "es")
        arch = Options().arch
        extra_definitions=["-DCMAKE_INCLUDE_PATH=/tmp/build_root/" + arch + "/include",
                           "-DCMAKE_LIBRARY_PATH=/tmp/build_root/" + arch + "/lib"]
        if suite == "gl":
            extra_definitions.append("-DDEQP_TARGET=x11_egl")
        else:
            extra_definitions.append("-DDEQP_TARGET=x11")
        CMakeBuilder.__init__(self, extra_definitions=extra_definitions)
            
    def test(self):
        pass

    def clean(self):
        git_clean(self._src_dir)

    def build(self):
        pm = ProjectMap()
        if not os.path.exists(self._build_dir):
            os.makedirs(self._build_dir)

        savedir = os.getcwd()
        os.chdir(self._build_dir)

        cflag = "-m32"
        cxxflag = "-m32"
        if self._options.arch == "m64":
            cflag = "-m64"
            cxxflag = "-m64"
        env = {"CC":"ccache gcc",
               "CXX":"ccache g++",
               "CFLAGS":cflag,
               "CXXFLAGS":cxxflag,
               "PKG_CONFIG_PATH":get_package_config_path()}
        self._options.update_env(env)
        
        run_batch_command(["cmake", "-GNinja", self._src_dir] + self._extra_definitions,
                             env=env)

        run_batch_command(["ninja","-j" + str(cpu_count())], env=env)

        install_dir = pm.build_root() + "/bin/" + self._suite
        binary_dir = self._build_dir + "/cts"
        if self._suite == "gl":
            binary_dir = self._build_dir + "/external/openglcts/modules"
        run_batch_command(["mkdir", "-p", install_dir])
        run_batch_command(["cp", "-a", binary_dir,
                              install_dir])

        os.chdir(savedir)

        Export().export()
