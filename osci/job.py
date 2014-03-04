import datetime
import logging
import time

import paramiko

from osci import constants
from osci.config import Configuration
from osci import instructions
from osci import utils
from osci import environment
from osci import db


class SQLLiteral(object):
    def __init__(self, literal_value):
        self.literal_value = literal_value


class Test(db.Base):
    __tablename__ = 'test'

    __table_args__ = (
        db.UniqueConstraint('project_name', 'change_num'),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column('project_name', db.String(50))
    change_num = db.Column('change_num', db.String(10))
    change_ref = db.Column('change_ref', db.String(50))
    state = db.Column('state', db.Integer())
    created = db.Column('created', db.DateTime())
    commit_id = db.Column('commit_id', db.String(50))
    node_id = db.Column('node_id', db.Integer())
    node_ip = db.Column('node_ip', db.String(50))
    result = db.Column('result', db.String(50))
    logs_url = db.Column('logs_url', db.String(200))
    report_url = db.Column('report_url', db.String(200))
    updated = db.Column('updated', db.DateTime())
    test_started = db.Column('test_started', db.DateTime())
    test_stopped = db.Column('test_stopped', db.DateTime())
    failed = db.Column('failed', db.Text())


    log = logging.getLogger('citrix.test')

    NULL = SQLLiteral('NULL')
    CURRENT_TIMESTAMP = SQLLiteral('CURRENT_TIMESTAMP')

    def __init__(self, change_num=None, change_ref=None, project_name=None, commit_id=None):
        self.db = None
        self.project_name = project_name
        self.change_num = change_num
        self.change_ref = change_ref
        self.state = constants.QUEUED
        self.created = datetime.datetime.now()
        self.commit_id = commit_id
        self.node_id = None
        self.node_ip = None
        self.result = None
        self.logs_url = None
        self.report_url = None

    @property
    def queued(self):
        return self.state == constants.QUEUED

    @classmethod
    def fromRecord(cls, record):
        retVal = Test()
        i = 1
        retVal.project_name = record[i]; i += 1
        retVal.change_num = record[i]; i += 1
        retVal.change_ref = record[i]; i += 1
        retVal.state = record[i]; i += 1
        retVal.created = record[i]; i += 1
        retVal.commit_id = record[i]; i += 1
        retVal.node_id = record[i]; i += 1
        retVal.node_ip = record[i]; i += 1
        retVal.result = record[i]; i += 1
        retVal.logs_url = record[i]; i += 1
        retVal.report_url = record[i]; i += 1
        retVal.updated = record[i]; i += 1
        retVal.test_started = record[i]; i += 1
        retVal.test_stopped = record[i]; i += 1

        return retVal

    @classmethod
    def getAllWhere(cls, db, **kwargs):
        session = db.get_session()
        result = (
            session
                .query(cls)
                .filter_by(**kwargs)
                .order_by(cls.updated).all()
        )
        session.close()
        return result

    @classmethod
    def retrieve(cls, db, project_name, change_num):
        sql = 'SELECT * FROM test WHERE'+\
              ' project_name="%s"'+\
              ' AND change_num="%s"'
        results = db.query(sql%(project_name, change_num))
        if len(results) == 0:
            return None

        test = Test.fromRecord(results[0])
        test.db = db

        return test

    def update(self, **kwargs):
        if self.state == constants.RUNNING and kwargs.get('state', constants.RUNNING) != constants.RUNNING:
            kwargs['test_stopped'] = self.CURRENT_TIMESTAMP

        if kwargs.get('state', None) == constants.RUNNING:
            kwargs['test_started'] = self.CURRENT_TIMESTAMP
            kwargs['test_stopped'] = self.NULL

        self.update_database_record(**kwargs)

    def update_database_record(self, **kwargs):
        sql = 'UPDATE test SET updated=CURRENT_TIMESTAMP,'
        for key in sorted(kwargs.keys()):
            value = kwargs[key]
            if value in [self.NULL, self.CURRENT_TIMESTAMP]:
                sql += ' %s=%s,'%(key, value.literal_value)
            else:
                sql += ' %s="%s",'%(key, value)
            setattr(self, key, value)

        assert sql[-1:] == ","
        sql = sql[:-1] # Strip off the last ,
        sql += ' WHERE project_name="%s" AND change_num="%s"'%(self.project_name, self.change_num)
        self.db.execute(sql)

    def delete(self):
        SQL = 'DELETE FROM test WHERE project_name="%s" AND change_num="%s"'
        self.db.execute(SQL%(self.project_name, self.change_num))

    def runTest(self, nodepool):
        if self.node_id:
            nodepool.deleteNode(self.node_id)
            self.update(node_id=0)

        node_id, node_ip = nodepool.getNode()

        if not node_id:
            return
        self.log.info("Running test for %s on %s/%s"%(self, node_id, node_ip))

        if not utils.testSSH(node_ip, Configuration().NODE_USERNAME, Configuration().NODE_KEY):
            self.log.error('Failed to get SSH object for node %s/%s.  Deleting node.'%(node_id, node_ip))
            nodepool.deleteNode(node_id)
            self.update(node_id=0)
            return

        self.update(node_id=node_id, node_ip=node_ip, result='')

        cmd = 'echo %s >> run_tests_env' % ' '.join(instructions.check_out_testrunner())
        utils.execute_command('ssh -q -o BatchMode=yes -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i %s %s@%s %s'%(
                Configuration().NODE_KEY, Configuration().NODE_USERNAME, node_ip, cmd))
        cmd = 'echo "%s %s" >> run_tests_env' % (
            ' '.join(environment.get_environment(self.change_ref)),
            ' '.join(instructions.execute_test_runner()))
        utils.execute_command('ssh -q -o BatchMode=yes -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i %s %s@%s %s'%(
                Configuration().NODE_KEY, Configuration().NODE_USERNAME, node_ip, cmd))
        # For some reason invoking this immediately fails...
        time.sleep(5)
        utils.execute_command('ssh$-q$-o$BatchMode=yes$-o$UserKnownHostsFile=/dev/null$-o$StrictHostKeyChecking=no$-i$%s$%s@%s$nohup bash /home/jenkins/run_tests_env < /dev/null > run_tests.log 2>&1 &'%(
                Configuration().NODE_KEY, Configuration().NODE_USERNAME, node_ip), '$')
        self.update(state=constants.RUNNING)

    def isRunning(self):
        if not self.node_ip:
            self.log.error('Checking job %s is running but no node IP address'%self)
            return False
        updated = time.mktime(self.updated.timetuple())

        if (time.time() - updated < 300):
            # Allow 5 minutes for the gate PID to exist
            return True

        # Absolute maximum running time of 2 hours.  Note that if by happy chance the tests have finished
        # this result will be over-written by retrieveResults
        if (time.time() - updated > Configuration().get_int('MAX_RUNNING_TIME')):
            self.log.error('Timed out job %s (Running for %d seconds)'%(self, time.time()-updated))
            self.update(result='Aborted: Timed out')
            return False

        try:
            success = utils.execute_command('ssh -q -o BatchMode=yes -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i %s %s@%s ps -p `cat /home/jenkins/run_tests.pid`'%(
                    Configuration().NODE_KEY, Configuration().NODE_USERNAME, self.node_ip), silent=True)
            self.log.info('Gate-is-running on job %s (%s) returned: %s'%(
                          self, self.node_ip, success))
            return success
        except Exception, e:
            self.update(result='Aborted: Exception checking for pid')
            self.log.exception(e)
            return False

    def retrieveResults(self, dest_path):
        if not self.node_ip:
            self.log.error('Attempting to retrieve results for %s but no node IP address'%self)
            return "Aborted: No IP"
        try:
            code, stdout, stderr = utils.execute_command('ssh -q -o BatchMode=yes -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i %s %s@%s cat result.txt'%(
                    Configuration().NODE_KEY, Configuration().NODE_USERNAME, self.node_ip), silent=True,
                                                   return_streams=True)
            self.log.info('Result: %s (Err: %s)'%(stdout, stderr))
            self.log.info('Downloading logs for %s'%self)
            utils.copy_logs(['/home/jenkins/workspace/testing/logs/*', '/home/jenkins/run_test*'], dest_path,
                      self.node_ip, Configuration().NODE_USERNAME,
                      Configuration().NODE_KEY,
                      upload=False)

            if code != 0:
                # This node is broken somehow... Mark it as aborted
                if self.result and self.result.startswith('Aborted: '):
                    return self.result
                return "Aborted: No result found"

            return stdout.splitlines()[0]
        except Exception, e:
            self.log.exception(e)
            return "Aborted: Failed to copy logs"

    def __repr__(self):
        return "%(project_name)s/%(change_num)s state:%(state)s" %self

    def __getitem__(self, item):
        return getattr(self, item)
