from os.path import exists
from os import stat
from subprocess import CalledProcessError, check_call

from .util.condor import build_submit_description, condor_submit
from .base.external import ExternalBaseManager

SUBMIT_PARAM_PREFIX = "submit_"


## TODO:
##  - user_log_sizes and state_cache never expire
##    elements never expire. This is a small memory
##    whole that should be fixed.
class CondorQueueManager(ExternalBaseManager):
    """
    Job manager backend that plugs into Condor.
    """
    manager_type = "queued_condor"

    def __init__(self, name, app, **kwds):
        super(CondorQueueManager, self).__init__(name, app, **kwds)
        submission_params = {}
        for key, value in kwds.iteritems():
            key = key.lower()
            if key.startswith(SUBMIT_PARAM_PREFIX):
                condor_key = key[len(SUBMIT_PARAM_PREFIX):]
                submission_params[condor_key] = value
        self.submission_params = submission_params
        self.user_log_sizes = {}
        self.state_cache = {}

    def launch(self, job_id, command_line):
        self._check_execution_with_tool_file(job_id, command_line)
        job_file_path = self._setup_job_file(job_id, command_line)
        log_path = self.__condor_user_log(job_id)
        open(log_path, 'w')  # Touch log file
        build_submit_params = dict(
            executable=job_file_path,
            output=self._stdout_path(job_id),
            error=self._stderr_path(job_id),
            user_log=log_path,
            query_params=self.submission_params,
        )
        submit_file_contents = build_submit_description(**build_submit_params)
        submit_file = self._write_job_file(job_id, "job.condor.submit", submit_file_contents)
        external_id, message = condor_submit(submit_file)
        if not external_id:
            raise Exception(message)
        self._register_external_id(job_id, external_id)

    def __condor_user_log(self, job_id):
        return self._job_file(job_id, 'job_condor.log')

    def _kill_external(self, external_id):
        try:
            check_call(('condor_rm', external_id))
        except CalledProcessError:
            pass

    def get_status(self, job_id):
        external_id = self._external_id(job_id)
        if not external_id:
            raise Exception("Failed to obtain external_id for job_id %s, cannot determine status." % job_id)
        log_path = self.__condor_user_log(job_id)
        if not exists(log_path):
            return 'complete'
        if external_id not in self.user_log_sizes:
            self.user_log_sizes[external_id] = -1
            self.state_cache[external_id] = 'queued'
        log_size = stat(log_path).st_size
        if log_size == self.user_log_sizes[external_id]:
            return self.state_cache[external_id]
        return self.__get_state_from_log(external_id, log_path)

    def __get_state_from_log(self, external_id, log_file):
        log_job_id = external_id.zfill(3)
        state = 'queued'
        with open(log_file, 'r') as fh:
            for line in fh:
                if '001 (' + log_job_id + '.' in line:
                    state = 'running'
                if '004 (' + log_job_id + '.' in line:
                    state = 'running'
                if '007 (' + log_job_id + '.' in line:
                    state = 'running'
                if '005 (' + log_job_id + '.' in line:
                    state = 'complete'
                if '009 (' + log_job_id + '.' in line:
                    state = 'complete'
            log_size = fh.tell()
        self.user_log_sizes[external_id] = log_size
        self.state_cache[external_id] = state
        return state