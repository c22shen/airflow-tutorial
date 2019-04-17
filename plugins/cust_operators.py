import logging
import pendulum
import os
from airflow.contrib.hooks.ssh_hook import SSHHook
from airflow.exceptions import AirflowException
from airflow.models import BaseOperator
from airflow.plugins_manager import AirflowPlugin
from airflow.utils.decorators import apply_defaults
from datetime import datetime
from airflow.operators.sensors import BaseSensorOperator
from coseco2cifpython import python_execute


log = logging.getLogger(__name__)

class MyFirstOperator(BaseOperator):

    @apply_defaults
    def __init__(self, *args, **kwargs):
        super(MyFirstOperator, self).__init__(*args, **kwargs)

    def execute(self, context):
        local_est_tz = pendulum.timezone("America/Toronto")
        execution_date = context.get('execution_date')
        execution_date_est = local_est_tz.convert(execution_date)
        now = pendulum.now()
        log.info("execution_date %s", execution_date)
        log.info('execution_date_est: %s', execution_date_est)
        log.info('now: %s', now)
        in_the_future = execution_date > now
        log.info('in_the_future: %s', in_the_future)

class FilesCleaningOperator(BaseOperator):

    @apply_defaults
    def __init__(self, *args, **kwargs):
        super(FilesCleaningOperator, self).__init__(*args, **kwargs)

    def execute(self, context):
        task_instance = context['task_instance']
        upstream_tasks = self.get_flat_relatives(upstream=True)
        upstream_task_ids = [task.task_id for task in upstream_tasks]
        
        # Remove output files
        generated_output_files_list = task_instance.xcom_pull(task_ids=upstream_task_ids, key='generated_output_files')
        generated_output_files = next((item for item in generated_output_files_list if item is not None), {})
        for output_file_name in generated_output_files.values():
            self.log.info("Starting to remove local file  %s", output_file_name)
            _silently_remove_file('./'+output_file_name)
        
        # Remove email files
        input_email_files_list = task_instance.xcom_pull(task_ids=upstream_task_ids, key='email_input_extract_file')
        
        for input_email_file in input_email_files_list:
            if isinstance(input_email_file, str):
                _silently_remove_file('./'+input_email_file)

        # Remove extract files
        input_extract_files_list = task_instance.xcom_pull(task_ids=upstream_task_ids, key='extract_input_extract_file')
        
        for input_extract_file in input_extract_files_list:
            if isinstance(input_extract_file, str):
                _silently_remove_file('./'+input_extract_file)

class SFTPUploadOperator(BaseOperator):

    @apply_defaults
    def __init__(self, 
                ssh_conn_id=None,
                *args,
                **kwargs):
        super(SFTPUploadOperator, self).__init__(*args, **kwargs)
        self.ssh_conn_id = ssh_conn_id

    def execute(self, context):
        task_instance = context['task_instance']
        
        upstream_tasks = self.get_flat_relatives(upstream=True)
        upstream_task_ids = [task.task_id for task in upstream_tasks]
        generated_output_files_list = task_instance.xcom_pull(task_ids=upstream_task_ids, key='generated_output_files')
        log.info('The generated_ouputfile list names are: %s', generated_output_files_list)
        log.info('The generated_ouputfile list names type are: %s', type(generated_output_files_list))
        
        generated_output_files = next((item for item in generated_output_files_list if item is not None), {})
        log.info('The generated_ouputfile names are: %s', generated_output_files)
        log.info('The generated_ouputfile names type are: %s', type(generated_output_files))
        output_transfer_msg = None
        try: 
            self.log.info("Trying ssh_conn_id to create SSHHook.")
            self.ssh_hook = SSHHook(ssh_conn_id=self.ssh_conn_id)                       
            with self.ssh_hook.get_conn() as ssh_client:
                sftp_client = ssh_client.open_sftp()
                for output_file_name in generated_output_files.values(): 
                    local_filepath = './' + output_file_name
                    remote_filepath = '/AI_Output/' + output_file_name
                    output_transfer_msg = "from {0} to {1}".format(local_filepath, remote_filepath)
                    self.log.info("Starting to transfer output file  %s", output_transfer_msg)
                    sftp_client.put(local_filepath, remote_filepath, confirm=True)
        except Exception as e: 
            raise AirflowException("Error while transferring {0}, error: {1}. Retrying..."
                                   .format(output_transfer_msg, str(e)))

class ClientConversionOperator(BaseOperator):

    @apply_defaults
    def __init__(self, *args, **kwargs):
        super(ClientConversionOperator, self).__init__(*args, **kwargs)

    def execute(self, context):
        log.info("Client Conversion Initiation")
        task_instance = context['task_instance']
        
        upstream_tasks = self.get_flat_relatives(upstream=True)
        upstream_task_ids = [task.task_id for task in upstream_tasks]


        # This will be dynamic later, or not make it so complicated
        file_names = task_instance.xcom_pull(task_ids=upstream_task_ids, key='extract_input_extract_file')
        log.info('The file names are: %s', file_names)
        file_name =  next((item for item in file_names if item is not None), '')
        generated_output_files = python_execute(file_name)
        task_instance.xcom_push('generated_output_files', generated_output_files)

class MyFirstSensor(BaseSensorOperator):

    @apply_defaults
    def __init__(self, *args, **kwargs):
        super(MyFirstSensor, self).__init__(*args, **kwargs)

    def poke(self, context):
        current_minute = datetime.now().minute
        execution_date = context.get('execution_date')

        log.info("Execution date is: (%s)", execution_date)
        if current_minute % 3 != 0:
            log.info("Current minute (%s) not is divisible by 3, sensor will retry.", current_minute)
            return False
        local_est_tz = pendulum.timezone("America/Toronto")
        execution_date = context.get('execution_date')
        execution_date_est = local_est_tz.convert(execution_date)
        log.info("execution time est is %s",  execution_date_est)
        log.info("Current minute (%s) is divisible by 3, sensor finishing.", current_minute)
        task_instance = context['task_instance']
        task_instance.xcom_push('sensors_minute', current_minute)
        return True


class UrgentOrRegular(object):
    REGULAR= 'regular'
    URGENT = 'urgent'

class ExtractOrEmail(object):
    EMAIL= 'email'
    EXTRACT = 'extract'

class FTPGetFileSensor(BaseSensorOperator):

    @apply_defaults
    def __init__(self, 
                ssh_conn_id=None,
                regular_or_urgent=UrgentOrRegular.REGULAR,
                extract_or_email=ExtractOrEmail.EXTRACT,
                *args, 
                **kwargs):
        super(FTPGetFileSensor, self).__init__(*args, **kwargs)
        self.ssh_conn_id = ssh_conn_id
        self.regular_or_urgent= regular_or_urgent
        self.extract_or_email = extract_or_email
    
    def poke(self, context):
        # local_est_tz = pendulum.timezone("America/Toronto")
        input_transfer_msg = None
        local_est_tz = pendulum.timezone("America/Toronto")
        now = pendulum.now()
        execution_date = context.get('execution_date')
        next_execution_date = context.get('next_execution_date')
        self.log.info("next Execution date is: (%s)", next_execution_date)
        execution_date = next_execution_date
        if execution_date > now: 
            execution_date = now
        execution_date_est = local_est_tz.convert(execution_date)
        # current_execution_date = execute_date.add(days=1)
        self.log.info("Execution date eastern is: (%s)", execution_date_est)

        input_file_name = _construct_input_file_name(self.regular_or_urgent, self.extract_or_email, execution_date_est.strftime("%Y%m%d"))
        
        self.log.info("input file name is: (%s)", input_file_name)
        try: 
            self.log.info("Trying ssh_conn_id to create SSHHook.")
            self.ssh_hook = SSHHook(ssh_conn_id=self.ssh_conn_id)           
            local_filepath = './' + input_file_name
            remote_filepath = '/' + input_file_name
            
            with self.ssh_hook.get_conn() as ssh_client:
                sftp_client = ssh_client.open_sftp()
                input_transfer_msg = "from {0} to {1}".format(remote_filepath,
                                                    local_filepath)
                self.log.info("Starting to transfer extract file  %s", input_transfer_msg)
                sftp_client.get(remote_filepath, local_filepath)

                task_instance = context['task_instance']
                task_instance.xcom_push(self.extract_or_email + '_input_extract_file', input_file_name)

                return True
        except Exception as e: 
            self.log.error("Error while transferring {0}, error: {1}. Retrying..."
                                   .format(input_transfer_msg, str(e)))
            return False

def _construct_input_file_name(file_urgency_level, file_type, currentExecutionDate):
    extract_or_email_file_string = ''

    if file_type == ExtractOrEmail.EMAIL:
       extract_or_email_file_string='.AlternativeEmail'

    return 'ECMExtract.DB2Data'+ currentExecutionDate + '.' + file_urgency_level + extract_or_email_file_string + '.csv'

def _silently_remove_file(file_path):
    try:
        os.remove(file_path)
    except OSError:
        pass

class CustomPlugins(AirflowPlugin):
    name = "custom_plugin"
    operators = [SFTPUploadOperator, MyFirstSensor, FTPGetFileSensor, ClientConversionOperator, MyFirstOperator, FilesCleaningOperator]