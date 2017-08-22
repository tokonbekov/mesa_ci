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

import os
import urllib
import urllib2
import ast
import time
import sys
import signal
import git
import xml.sax.saxutils

if __name__=="__main__":
    sys.path.append(os.path.dirname(os.path.abspath(sys.argv[0])))

from . import ProjectInvoke, DependencyGraph
from . import ProjectMap
from . import RepoSet
from . import run_batch_command

triggered_builds = []

def abort_builds(ignore, _):
    jen = Jenkins(None, None)
    print "Aborting builds"
    for an_invoke in triggered_builds:
        jen.abort(an_invoke)
    raise BuildAborted()

class AlreadyBuilt(Exception):
    def __init__(self, invoke):
        Exception.__init__(self)
        self.invoke = invoke

    def __str__(self):
        return "Already Built: " + str(self.invoke)

class BuildInProgress(Exception):
    def __init__(self, invoke, revision):
        Exception.__init__(self)
        self.invoke = invoke
        self.revision = revision
    def __str__(self):
        return "Error: build in progress.  Remove the following file to " \
            "rebuild: " + self.invoke.info_file()

class BuildFailure(Exception):
    def __init__(self, invoke, url):
        Exception.__init__(self)
        self.invoke = invoke
        self.url = url

    def __str__(self):
        return "Error: build failure: " + str(self.invoke) + "\nError: " + \
            self.url

class BuildAborted(Exception):
    def __init__(self):
        Exception.__init__(self)

    def __str__(self):
        return "Error: build aborted from jenkins"

class BuildStatus():
    def __init__(self, invoke, url, status):
        self.invoke = invoke
        self.url = url
        self.status = status

class Jenkins:
    """Manages invocation and status of builds on CI server
    """
    status_colors = {
                'success':'#66FF33',    # light green
                'failure':'#CD5555',     # light red
                'aborted':'#FFA54F',  # light orange
                'prebuilt':'#FFFFFF',   # white
                'unstable':'#F7FE2E',   # yellow
                'unknown':'#EE82EE'}    # purple

    def __init__(self, revspec, result_path):
        if os.environ.has_key("http_proxy"):
            del os.environ["http_proxy"]
        
        spec = ProjectMap().build_spec()
        self._server = spec.find("build_master").attrib["host"]

        # list of buildinvoke objects that have been triggered
        self._jobs = []

        self._revspec = revspec
        self._result_path = result_path
        self._time = str(time.time())

    def job_url(self, invoke):
        if "win" in invoke.options.hardware:
            return "http://" + self._server + "/job/WinLeeroy"
        return "http://" + self._server + "/job/Leeroy"

    # this function is common to jenkins.py
    def _reliable_url_open(self, url):
        # We use a loop to open the url because of DE3123
        failcount = 0
        while True:
            try:
                f = urllib2.urlopen(url)
                return f
            except (urllib2.HTTPError, urllib2.URLError):
                print "failure urllib2.urlopen(\"{0}\")".format(url)
                failcount += 1
                if failcount == 5:
                    raise
                time.sleep(5)

    def write_failure_log(self, project_invoke):
        log_dir = ProjectMap().output_dir()
        job_url = project_invoke.get_info("url")
        run_batch_command(["wget", "-O", log_dir + project_invoke.to_short_string() + ".log",
                           job_url + "/consoleText"])

    def build(self, project_invoke, branch="", extra_arg=None):
        status = project_invoke.get_info("status", block=False)
        if status == "building":
            job_url = project_invoke.get_info("url")
            live_build = True
            if not job_url:
                print "No URL, checking trigger time"
                trigger_time = project_invoke.get_info("trigger_time")
                if trigger_time:
                    trigger_time = float(trigger_time)
                    if time.time() - trigger_time > 600:
                        # a build was cancelled in the queue
                        print "build was triggered but never built: " + str(trigger_time)
                        live_build = False
            try:
                f = urllib2.urlopen(job_url + "/api/python")
                abuild_page = ast.literal_eval(f.read())
                if abuild_page["result"]:
                    # there is a build result, probably cancelled
                    print "found dead build with status: " + abuild_page["result"]
                    print "url: " + job_url
                    print "rebuilding."
                    live_build = False
            except:
                pass
            if live_build:
                raise BuildInProgress(project_invoke, self._revspec)
            # else the build is dead, we should rebuild it.

        if status == "failure":
            # raise BuildFailure(project_invoke, self._revision)
            # for now, let's attempt to rebuild failure projects
            self.write_failure_log(project_invoke)

        project_invoke.set_info("status", "building")
        project_invoke.set_info("url", "")
        self._jobs.append(project_invoke)

        # use the current build_support branch on the component builds
        r = git.Repo(ProjectMap().source_root())
        bs_branch = r.commit().hexsha
        url = "{0}/buildWithParameters?token=noauth&{1}&branch={2}&build_support_branch={3}".format(
            self.job_url(project_invoke),
            self._jenkins_params(project_invoke),
            branch,
            bs_branch
        )
        if extra_arg:
            url = url + "&extra_arg=" + urllib2.quote(extra_arg)

        f = self._reliable_url_open(url)
        f.read()
        return True

    def reboot_builder(self, builder):
        self._job_url = "http://" + self._server + "/job/Leeroy"
        url = "http://{0}/job/reboot_single/buildWithParameters?token=noauth&label={1}".format(
            self._server,
            builder)

        f = self._reliable_url_open(url)
        f.read()
        return True

    def abort(self, project_invoke):
        if project_invoke.get_info("status") != "building":
            return
        build_link = self.get_build_link(project_invoke, block=False)
        if not build_link:
            return False
        data = urllib.urlencode({'token': 'noauth'})
        build_link = build_link + "stop/"

        try:
            f = urllib2.urlopen(build_link, data=data)
            f.read()
        except (urllib2.HTTPError, urllib2.URLError):
            # stopping build on abort typically fails for at least one build
            pass
        project_invoke.set_info("status", "aborted")
        return True
            
        
    def _jenkins_params(self, invoke):
        p = []
        o = invoke.options
        p.append("project=" + invoke.project)
        p.append("arch=" + o.arch)
        p.append("config=" + o.config)
        p.append("type=" + o.type)
        p.append("revision=" + \
                 urllib2.quote(invoke.revision_spec.to_cmd_line_param()))
        p.append("result_path=" + o.result_path)
        p.append("hardware=" + o.hardware)
        p.append("hash=" + invoke.hash(self._time))
        p.append("shard=" + o.shard)
        if o.retest_path:
            p.append("extra_arg=--retest_path=" + o.retest_path)
        if o.env:
            p.append("env=" + urllib2.quote(o.env))

        label = o.hardware
        p.append("label=" + label)

        return "&".join(p)

    def print_builds(self):
        if not self._jobs:
            return
        print "The following builds are executing on the build system:"
        for a_job in self._jobs:
            job_url = a_job.get_info("url")
            if not job_url:
                job_url = "enqueued"
            print "\t" + a_job.to_short_string() + " : " + job_url

    def wait_for_build(self):
        if not self._jobs:
            return None

        # iterate _jobs, searching for matching job on jenkins.
        # Return any job that is complete.  Raise error if matching
        # job failure.
        first_round = True
        while True:
            # moderate the rate of polling, but do not add any latency
            # to the first attempt to find a finished build.
            if not first_round:
                time.sleep(5)
            first_round = False

            for i in range(len(self._jobs)):
                a_job = self._jobs[i]
                # get the url from the build_info file, if possible
                job_url = a_job.get_info("url")

                abuild_page = None
                if not job_url:
                    abuild_page = self.get_matching_build(a_job)
                    if not abuild_page:
                        # job not yet scheduled
                        continue
                    # cache the url in the build_info, so we don't
                    # have to keep searching for it.
                    job_url = abuild_page["url"]
                    a_job.set_info("url", job_url)
                    print job_url + " found for " + a_job.to_short_string()

                if not abuild_page:
                    try:
                        f = urllib2.urlopen(job_url + "/api/python")
                    except:
                        continue
                    abuild_page = ast.literal_eval(f.read())

                if not abuild_page["result"]:
                    # build not complete yet
                    continue

                end_time = a_job.get_info("end_time")
                
                if not end_time or (time.time() - end_time < 10):
                    # build will temporarily report success until
                    # warnings and test results are parsed.  This
                    # takes just a few seconds.  Re-read the status
                    # page to ensure we have the final status.  Only
                    # incur delays if the build finished less than 10
                    # seconds ago.
                    time.sleep(10 )
                try:
                    f = urllib2.urlopen(job_url + "/api/python")
                except:
                    continue
                abuild_page = ast.literal_eval(f.read())

                a_job.set_info("collect_time", time.time())
                if (abuild_page["result"] == "SUCCESS" or 
                    abuild_page["result"] == "UNSTABLE"):

                    return BuildStatus(self._jobs.pop(i), 
                                       abuild_page["url"], 
                                       abuild_page["result"].lower())
                self._jobs.pop(i)
                raise BuildFailure(a_job, abuild_page["url"])

    def get_matching_build(self, project_invoke):
        job_url = self.job_url(project_invoke)
        f = None
        try:
            f = urllib2.urlopen(job_url + "/api/python")
        except:
            return None

        job_page = ast.literal_eval(f.read())
        max_job = job_page["nextBuildNumber"]
        # check last 100 builds
        for abuild_number in range(max_job-1, max_job - 401, -1):
            try:
                f = urllib2.urlopen(job_url + "/" + 
                                    str(abuild_number) + "/api/python")
            except:
                continue
            abuild_page = ast.literal_eval(f.read())
            if not self.match_project_invoke(project_invoke, abuild_page):
                # not the matching build for the job that we are looking for
                continue
            return abuild_page

        # see if there are newer builds that haven't shown up in the history
        while True:
            try:
                max_job += 1
                url = job_url + "/" + str(max_job) + "/api/python"
                f = urllib2.urlopen(url)
                abuild_page = ast.literal_eval(f.read())
                if self.match_project_invoke(project_invoke, abuild_page):
                    return abuild_page
            except:
                # got a 404, build doesn't exist
                return None
                

    def match_project_invoke(self, project_invoke, build_dict):
        """true if the dict matches the invoke"""

        # get build_params
        build_params = []
        for an_action in build_dict["actions"]:
            if an_action.has_key("parameters"):
                build_params = an_action["parameters"]
                break
        if not build_params:
            print "WARN: build without params when searching for: " + project_invoke.to_short_string()
            return False
        hash_str = ""
        for a_param in build_params:
            if a_param["name"] == "hash":
                hash_str = a_param["value"]
                break
        return hash_str == project_invoke.hash(self._time)

    def get_build_link(self, project_invoke, block=True):
        # first check to see if the url is already known
        url = project_invoke.get_info("url")
        if url:
            return url
        while True:
            build_page = self.get_matching_build(project_invoke)
            if build_page:
                url = build_page["url"]
                project_invoke.set_info("url", url)
                return url
            if not block:
                return None
            time.sleep(1)

    def build_all(self, depGraph, branch="mesa_master", print_summary=True):
        signal.signal(signal.SIGINT, abort_builds)
        signal.signal(signal.SIGABRT, abort_builds)
        signal.signal(signal.SIGTERM, abort_builds)

        triggered_builds = []
        ready_for_build = depGraph.ready_builds()
        assert(ready_for_build)
        build_type = ready_for_build[0].options.type
        completed_builds = []
        failure_builds = []
        success = True
        pm = ProjectMap()
        summary_xml = pm.source_root() + "/summary.xml"
        if os.path.exists(summary_xml):
            os.remove(summary_xml)

        while success:
            self.print_builds()
            builds_in_round = 0
            for an_invoke in ready_for_build:
                status = an_invoke.get_info("status", block=False)

                if status == "success" or status == "unstable":
                    # don't rebuild if we have a good build, or just
                    # because some tests failure
                    completed_builds.append(an_invoke)
                    depGraph.build_complete(an_invoke)
                    builds_in_round += 1
                    print "Already built: " + an_invoke.to_short_string()
                    continue

                proj_build_dir = pm.project_build_dir(an_invoke.project)
                script = proj_build_dir + "/build.py"
                if not os.path.exists(script):
                    depGraph.build_complete(an_invoke)
                    builds_in_round += 1
                    continue

                try:
                    print "Starting: " + an_invoke.to_short_string()
                    self.build(an_invoke, branch=branch)
                    an_invoke.set_info("trigger_time", time.time())
                    triggered_builds.append(an_invoke)
                except(BuildInProgress) as e:
                    print e
                    success = False
                    break

            if not success:
                break

            if builds_in_round:
                ready_for_build = depGraph.ready_builds(triggered_builds)
                continue

            finished = None
            try:
                finished = self.wait_for_build()
                if finished:
                    builds_in_round += 1
            except(BuildFailure) as failure:
                failure.invoke.set_info("status", "failure")
                print "Build failure: " + failure.url
                print "Build failure: " + str(failure.invoke)
                failure_builds.append(failure.invoke)
                builds_in_round += 1

            if finished:
                finished.invoke.set_info("status", finished.status)
                print "Build finished: " + finished.invoke.to_short_string() + " " + finished.url

                completed_builds.append(finished.invoke)
                depGraph.build_complete(finished.invoke)

            elif not builds_in_round:
                # nothing was built, there was no failure, and no
                # builds are ready => the last project is built

                #stub_test_results(out_test_dir, o.hardware)
                # CleanServer(o).clean()
                if print_summary:
                    write_summary(pm.source_root(), 
                                  failure_builds + completed_builds, 
                                  self)
                if failure_builds:
                    raise BuildFailure(failure_builds[0], "")

                return triggered_builds

            ready_for_build = depGraph.ready_builds(triggered_builds)

        return triggered_builds
        
def generate_color_key(ljen):
    out_key = r'<field name="Key" titlecolor="black" value="" ' \
              r'detailcolor="" href="" /><table><tr>'

    for status in sorted(ljen.status_colors):
        out_key += '<td value="" bgcolor="' + ljen.status_colors[status] + \
                   '" fontcolor="black" fontattribute="normal" ' \
                   'align="center" width="200"/>'

    out_key += r'</tr>'
    out_key += r'<tr>'
    for status in sorted(ljen.status_colors):
        out_key += '<td value="' + status + \
                   '" bgcolor="" fontcolor="black" fontattribute="normal" '\
                   'align="center" width="200"/>'

    out_key += r'</tr></table>'
    return out_key

def generate_summary_row(build, ljen, header=False):
    if header:
        options_dict = {}
        bg_color = '#C6E2FF'
        font_attr = 'bold'
        link = ''
    else:
        font_attr = 'normal'
        bg_color = ljen.status_colors.get(build.get_info("status"), 
                                          ljen.status_colors['unknown'])
        options_dict = vars(build.options)
        link = ljen.get_build_link(build, block=False)
        options_dict['project'] = build.project
        #options_dict['platform'] = build.platform
        duration = hours_minutes_seconds(build.get_info("collect_time"), 
                                         build.get_info("trigger_time"))
        options_dict['duration'] = duration
                                   
        if not link:
            bg_color = ljen.status_colors['prebuilt']  
    out_row = r'<tr>'
    for afield in ['project', 'arch', 'hardware',
                   'type', 'config', 'duration']:
        add_url = ''
        if afield == 'project' and link:
            add_url = 'href="' + link + '"'

        out_row += '<td value="' + options_dict.get(afield, afield) + \
                   '" bgcolor="' + bg_color + \
                   '" fontcolor="black" fontattribute="' + \
                   font_attr + '" align="center" ' + add_url + \
                   ' width="200"/>'

    out_row += r'</tr>'
    return out_row

def hours_minutes_seconds(finish_time, start_time):
    if not finish_time or not start_time:
        return ""
    duration = finish_time - start_time
    seconds = int(duration % 60)
    minutes = int((duration / 60) % 60)
    hours = int(duration / 3600)
    return "%02d:%02d:%02d" % (hours, minutes, seconds)

def refresh_status(build):
    build_page = None
    url = build.get_info("url")
    if not url:
        return
    for _ in range(0,10):
        try:
            f = urllib2.urlopen(url + "/api/python")
            build_page = ast.literal_eval(f.read())
            break
        except:
            print "Retrying read of build page: " + url
            time.sleep(1)
            continue

    if not build_page:
        return
    if not build_page["result"]:
        return
    build.set_info("status",  build_page["result"].lower())

def write_summary(out_dir, completed_builds, ljen, failure=False):
    if completed_builds and type(completed_builds[0]) == type(""):
        # we have been passed a list of invoke strings instead of
        # objects.  Convert them
        invoke_builds = [ProjectInvoke(from_string=buildstr) for buildstr in completed_builds]
        completed_builds = invoke_builds
    repo_set = RepoSet()

    git_log = {}
    for project in ljen._revspec._revisions:
        message = repo_set.repo(project).commit().message.splitlines()[0]
        # allow for special chars in message.
        git_log[project] = xml.sax.saxutils.quoteattr(message) 

    build_status = 'success'
    if failure:
        build_status = 'failure'
    outf = open(os.path.join(out_dir, "summary.xml"), "w")
    outf.write("""\
<section name="" fontcolor="">
    <field name="Git revisions"/>
    <table>
        <tr>
            <td value="commit" bgcolor="#C6E2FF" fontcolor="black" fontattribute="bold" align="center"  width="200"/>
            <td value="description" bgcolor="#C6E2FF" fontcolor="black" fontattribute="bold" align="center"  width="200"/>
        </tr>""")
    for (project, rev) in ljen._revspec._revisions.items():
        outf.write("""\
        <tr>
            <td value="{project}={revision}" bgcolor="#66FF33" fontcolor="black" fontattribute="normal" align="center"  width="200"/>
            <td value={log} bgcolor="#66FF33" fontcolor="black" fontattribute="normal" align="center"  width="200"/>
        </tr>""".format(project=project, revision=rev, log=git_log[project].encode('utf-8')))
    outf.write("""\
    </table>
    <field name="Build """ + build_status + '" titlecolor="'+ ljen.status_colors.get(build_status) + """" value="" detailcolor="" href="" />
    <table sorttable="yes">""")
    outf.write(generate_summary_row(None, ljen, header=True))
    for build in completed_builds:
        refresh_status(build)
        outf.write(generate_summary_row(build, ljen))
    outf.write("""\
    </table>
    <br />""")
    outf.write(generate_color_key(ljen))
    long_pole_row_txt = """
<tr>
    <td value="{project}" bgcolor="{color}" fontcolor="black" fontattribute="bold" align="center" width="200" href="{url}"/>
    <td value="{duration}" bgcolor="{color}" fontcolor="black" fontattribute="bold" align="center" width="200"/>
    <td value="{waiting}" bgcolor="{color}" fontcolor="black" fontattribute="bold" align="center" width="200"/>
    <td value="{building}" bgcolor="{color}" fontcolor="black" fontattribute="bold" align="center" width="200"/>
    <td value="{finishing}" bgcolor="{color}" fontcolor="black" fontattribute="bold" align="center" width="200"/>
</tr> """
    outf.write("""\
<br/>
<field name="Long Pole Builds" titlecolor="black" value="" detailcolor="" href="" />
<table sorttable="yes">""" + \
               long_pole_row_txt.format(project="project", 
                                        duration="total duration", 
                                        waiting="waiting for machine", 
                                        building="building", 
                                        finishing="summarizing results", 
                                        color="#C6E2FF",
                                        url=""))

    long_pole_builds = DependencyGraph.long_pole(completed_builds[-1])
    long_pole_builds.reverse()
    for a_build in long_pole_builds:
        link = ljen.get_build_link(a_build, block=False)
        duration=hours_minutes_seconds(a_build.get_info("collect_time"), 
                                       a_build.get_info("trigger_time"))
        waiting = hours_minutes_seconds(a_build.get_info("start_time"), 
                                        a_build.get_info("trigger_time"))
        building = hours_minutes_seconds(a_build.get_info("end_time"), 
                                         a_build.get_info("start_time"))
        finishing = hours_minutes_seconds(a_build.get_info("collect_time"), 
                                          a_build.get_info("end_time"))
        outf.write(long_pole_row_txt.format(project=a_build.project, 
                                            duration=duration, 
                                            waiting=waiting, 
                                            building=building, 
                                            finishing=finishing, 
                                            url=link,
                                            color="#66FF33"))

    outf.write("""\
</table>
<br/>
    <field name="Build link to accept changed tests" 
    titlecolor="black" 
    value="generate patch" 
    detailcolor="" 
    href="http://{server}/job/accept_failed_tests/parambuild/?result_path={result_path}" />
<br/>
<br/>
    <field name="Build link to bisect changed tests"
    titlecolor="black" 
    value="generate patch" 
    detailcolor="" 
    href="http://{server}/job/bisect_failures/parambuild/?result_path={result_path}" />
<br/>
    <field name="Test Results" titlecolor="black" value="" detailcolor="" href="" />
</section>""".format(result_path=ljen._result_path, server=ljen._server))
    outf.close()


