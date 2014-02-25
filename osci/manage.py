import logging
import optparse
import time

from prettytable import PrettyTable
from pygerrit.client import GerritClient
from pygerrit.error import GerritError
from pygerrit.events import ErrorEvent, PatchsetCreatedEvent, CommentAddedEvent
from threading import Event

from osci.config import Configuration
from osci.testqueue import TestQueue
from osci import constants
from osci.test import Test


def is_event_matching_criteria(event):
    if isinstance(event, CommentAddedEvent):
        comment = event.comment
        if not Configuration.RECHECK_REGEXP.match(comment):
            return False
        logging.debug("Comment matched: %s", comment)
    elif not isinstance(event, PatchsetCreatedEvent):
        return False
    if event.change.branch == "master":
        if is_project_configured(event.change.project):
            logging.info("Event %s is matching event criteria", event)
            return True
    return False

def is_project_configured(submitted_project):
    return submitted_project in Configuration.PROJECT_CONFIG

def queue_event(queue, event):
    logging.info("patchset values : %s", event)
    if is_project_configured(event.change.project):
        queue.addTest(event.patchset.ref,
                      event.change.project,
                      event.patchset.revision)

def check_for_change_ref(option, opt_str, value, parser):
    if not parser.values.change_ref:
        msg = "can't use %s, Please provide --change_ref/-c before %s"
        raise optparse.OptionValueError(msg%(opt_str, opt_str))
    setattr(parser.values, option.dest, value)

def get_parser():
    usage = "usage: %prog [options]"

    parser = optparse.OptionParser(usage=usage)
    parser.add_option('-v', '--verbose', dest='verbose', action='store_true',
                      default=False, help='enable verbose (debug) logging')
    parser.add_option('-c', '--change-ref', dest='change_ref', action="store",
                      type="string", help="One time job on a change-ref")
    parser.add_option('-x', '--commit-id', dest='commitid',
                      action="callback", callback=check_for_change_ref,
                      type="string", help="One time job on a change-id")
    parser.add_option('-j', '--project', dest='project', action="callback",
                      callback=check_for_change_ref, type="string",
                      help="project of the change-ref provided")
    parser.add_option('--list', dest='list',
                      action='store_true', default=False,
                      help="List the tests recorded by the system")
    parser.add_option('--states', dest='states',
                      action='store', default=None,
                      help="(Use with --list): States to list")
    parser.add_option('--failures', dest='failures',
                      action='store_true', default=False,
                      help="List the failures recorded by the system")
    parser.add_option('--recent', dest='recent',
                      action='store', default=None,
                      help="List jobs less than this many hours old")
    parser.add_option('--show', dest='show',
                      action='store_true', default=False,
                      help="Show details for a specific test")

    return parser

def main():
    parser = get_parser()
    (options, _) = parser.parse_args()
    if options.change_ref and (not options.project or not options.commitid):
        parser.error('Can only use --change_ref with --project')

    level = logging.DEBUG if options.verbose else logging.INFO
    logging.basicConfig(
        format=u'%(asctime)s %(levelname)s %(name)s %(message)s',
        level=level)

    # Lower the warning levels of a number of loggers
    for logger_name in ['paramiko.transport', 'paramiko.transport.sftp',
                        'requests.packages.urllib3.connectionpool']:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    queue = TestQueue(Configuration.MYSQL_URL, Configuration.MYSQL_USERNAME,
                      Configuration.MYSQL_PASSWORD, Configuration.MYSQL_DB)


    if options.show:
        table = PrettyTable()
        table.add_column('Key', ['Project name', 'Change num', 'Change ref',
                                 'state', 'created', 'Commit id', 'Node id',
                                 'Node ip', 'Result', 'Logs', 'Report',
                                 'Updated', 'Gerrit URL'])
        test = Test.getAllWhere(queue.db, change_ref=options.change_ref,
                                project_name=options.project)[0]
        url = 'https://review.openstack.org/%s'%test.change_num
        table.add_column('Value',
                         [test.project_name, test.change_num, test.change_ref,
                          constants.STATES[test.state], test.created,
                          test.commit_id, test.node_id, test.node_ip,
                          test.result, test.logs_url, test.report_url,
                          test.updated, url])
        table.align = 'l'
        print table
        return


    if options.change_ref:
        # Execute tests and vote
        if options.project not in Configuration.PROJECT_CONFIG:
            logging.info("Project specified does not match criteria")
            return
        queue.addTest(options.change_ref, options.project, options.commitid)

    if options.list:
        table = PrettyTable(["Project", "Change", "State", "IP", "Result",
                             "Age (hours)", "Duration"])
        table.align = 'l'
        now = time.time()
        all_tests = Test.getAllWhere(queue.db)
        state_dict = {}
        result_dict = {}
        if options.states and len(options.states) > 0:
            states = options.states.split(',')
        else:
            states = None
        for test in all_tests:
            updated = time.mktime(test.updated.timetuple())
            age_hours = (now - updated) / 3600
            if options.recent:
                if age_hours > int(options.recent):
                    continue
            state_count = state_dict.get(constants.STATES[test.state], 0)+1
            state_dict[constants.STATES[test.state]] = state_count
            result_count = result_dict.get(test.result, 0)+1
            result_dict[test.result] = result_count

            if states and constants.STATES[test.state] not in states:
                continue
            if test.node_id:
                node_ip = test.node_ip
            else:
                node_ip = '(%s)'%test.node_ip
            age = '%.02f' % (age_hours)
            duration = '-'

            if test.test_started and test.test_stopped:
                started = time.mktime(test.test_started.timetuple())
                stopped = time.mktime(test.test_stopped.timetuple())
                if started < stopped:
                    duration = "%.02f"%((stopped - started)/3600)
            table.add_row([test.project_name, test.change_ref,
                           constants.STATES[test.state], node_ip, test.result,
                           age, duration])
        print state_dict
        print result_dict
        print table
        return

    if options.failures:
        table = PrettyTable(["Project", "Change", "State", "Result", "Age",
                             "Duration", "URL"])
        table.align = 'l'
        now = time.time()
        all_tests = Test.getAllWhere(queue.db)
        for test in all_tests:
            if not test.result or (test.result != 'Failed' and
                                   test.result.find('Aborted') != 0):
                continue
            updated = time.mktime(test.updated.timetuple())
            age_hours = (now - updated) / 3600
            if options.recent:
                if age_hours > int(options.recent):
                    continue
            if test.node_id:
                node_ip = test.node_ip
            else:
                node_ip = '(%s)'%test.node_ip
            age = '%.02f' % (age_hours)
            duration = '-'

            if test.test_started and test.test_stopped:
                started = time.mktime(test.test_started.timetuple())
                stopped = time.mktime(test.test_stopped.timetuple())
                duration = "%.02f"%((stopped - started)/3600)
            table.add_row([test.project_name, test.change_num,
                           constants.STATES[test.state], test.result, age,
                           duration, test.logs_url])
        print table
        return

    # Starting the loop for listening to Gerrit events
    try:
        logging.info("Connecting to gerrit host %s",
                     Configuration.GERRIT_HOST)
        logging.info("Connecting to gerrit username %s",
                     Configuration.GERRIT_USERNAME)
        logging.info("Connecting to gerrit port %d",
                     Configuration.GERRIT_PORT)
        gerrit = GerritClient(host=Configuration.GERRIT_HOST,
                              username=Configuration.GERRIT_USERNAME,
                              port=Configuration.GERRIT_PORT)
        logging.info("Connected to Gerrit version [%s]",
                     gerrit.gerrit_version())
        gerrit.start_event_stream()
    except GerritError as err:
        logging.error("Gerrit error: %s", err)
        return 1

    errors = Event()
    try:
        while True:
            event = gerrit.get_event(block=False)
            while event:
                logging.debug("Event: %s", event)

                if is_event_matching_criteria(event):
                    queue_event(queue, event)

                if isinstance(event, ErrorEvent):
                    logging.error(event.error)
                    errors.set()
                event = gerrit.get_event(block=False)
            try:
                queue.postResults()
                queue.processResults()
                queue.triggerJobs()
            except Exception, e:
                logging.exception(e)
                # Ignore exception and try again; keeps the app polling
            time.sleep(Configuration.POLL)
    except KeyboardInterrupt:
        logging.info("Terminated by user")
    finally:
        logging.debug("Stopping event stream...")
        gerrit.stop_event_stream()

    if errors.isSet():
        logging.error("Exited with error")
        return 1