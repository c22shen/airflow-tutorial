import logging
import pendulum
from airflow.contrib.hooks.ssh_hook import SSHHook
from airflow.exceptions import AirflowException
from airflow.models import BaseOperator
from airflow.plugins_manager import AirflowPlugin
from airflow.utils.decorators import apply_defaults
from datetime import datetime
from airflow.operators.sensors import BaseSensorOperator
from coseco2cifpython import python_execute


log = logging.getLogger(__name__)

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
        generated_output_files = task_instance.xcom_pull('client_conversion_task', key='generated_output_files')
        output_transfer_msg = None
        try: 
            self.log.info("Trying ssh_conn_id to create SSHHook.")
            self.ssh_hook = SSHHook(ssh_conn_id=self.ssh_conn_id)                       
            with self.ssh_hook.get_conn() as ssh_client:
                sftp_client = ssh_client.open_sftp()
                for output_file_name in generated_output_files.values(): 
                    local_filepath = './' + output_file_name
                    remote_filepath = '/AI_Output/' + output_file_name
                    output_transfer_msg = "from {1} to {0}".format(remote_filepath,
                                                    local_filepath)
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
        # This will be dynamic later, or not make it so complicated
        file_name = task_instance.xcom_pull('get_regular_file_sftpsensor', key='input_extract_file')
        log.info('The file name is: %s', file_name)
        generated_output_files = python_execute(file_name)
        task_instance.xcom_push('generated_output_files', generated_output_files)

class MyFirstSensor(BaseSensorOperator):

    @apply_defaults
    def __init__(self, *args, **kwargs):
        super(MyFirstSensor, self).__init__(*args, **kwargs)

    def poke(self, context):
        current_minute = datetime.now().minute
        execute_date = context.get('execution_date')

        log.info("Execution date is: (%s)", execute_date)
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
        execute_date = context.get('execution_date')
        # current_execution_date = execute_date.add(days=1)
        # current_execution_date_est = local_est_tz.convert(current_execution_date)
        self.log.info("Execution date is: (%s)", execute_date)
        # self.log.info("Today's date should be: (%s)", current_execution_date)
        # self.log.info("Today's date eastern should be: (%s)", current_execution_date_est)
        # self.log.info("Today's date eastern in proper format should be: (%s)", current_execution_date_est.strftime("%Y%m%d"))

        input_file_name = _construct_input_file_name(self.regular_or_urgent, self.extract_or_email, execute_date.strftime("%Y%m%d"))
        
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
                task_instance.xcom_push('input_extract_file', input_file_name)

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

class CustomPlugins(AirflowPlugin):
    name = "custom_plugin"
    operators = [SFTPUploadOperator, MyFirstSensor, FTPGetFileSensor, ClientConversionOperator]