import unittest
import  mock

from osci import commands
from osci import executor
from osci import instructions
from osci import environment
from osci import gerrit


COMMON_SSH_OPTS=(
    '-q -o BatchMode=yes -o UserKnownHostsFile=/dev/null'
    ' -o StrictHostKeyChecking=no')
SSH_TO_LOGSERVER=(
    'ssh {SSH_OPTIONS} LOGSERVER_USERNAME@LOGSERVER_HOST'.format(
        SSH_OPTIONS=COMMON_SSH_OPTS).split())
SCP=(
    'scp {SSH_OPTIONS}'.format(
        SSH_OPTIONS=COMMON_SSH_OPTS).split())
SSH_TO_NODE=(
    'ssh {SSH_OPTIONS} NODE_USERNAME@NODE_HOST'.format(
        SSH_OPTIONS=COMMON_SSH_OPTS).split())
SSH_TO_DOMZERO_FROM_NODE=(
    'sudo -u domzero ssh {SSH_OPTIONS} root@192.168.33.2'.format(
        SSH_OPTIONS=COMMON_SSH_OPTS).split()
)


class TestGetDom0Logs(unittest.TestCase):
    def test_executed_commands(self):
        cmd = commands.GetDom0Logs()

        cmd()
        print executor.fake_pipe(
            SSH_TO_NODE
            + SSH_TO_DOMZERO_FROM_NODE
            + "tar --ignore-failed-read -czf - SOURCES".split(),
            SSH_TO_LOGSERVER
            +'tar -xzf - -C TARGET_DIR'.split()
        )

        self.maxDiff = 4096
        self.assertEquals(
            executor.fake_pipe(
                SSH_TO_NODE
                + SSH_TO_DOMZERO_FROM_NODE
                + "tar --ignore-failed-read -czf - SOURCES".split(),
                SSH_TO_LOGSERVER
                +'tar -xzf - -C TARGET_DIR'.split()
            ),
            cmd.executor.executed_commands[0])

    def test_sars_escaped(self):
        cmd = commands.GetDom0Logs()
        cmd.sources = '*'

        cmd()

        self.maxDiff = 1024
        self.assertEquals(
            executor.fake_pipe(
                SSH_TO_NODE
                + SSH_TO_DOMZERO_FROM_NODE
                + r"tar --ignore-failed-read -czf - \*".split(),
                SSH_TO_LOGSERVER
                +'tar -xzf - -C TARGET_DIR'.split()
            ),
            cmd.executor.executed_commands[0])

    def test_executor_factory(self):
        cmd = commands.GetDom0Logs(dict(executor='print'))
        self.assertEquals('PrintExecutor', cmd.executor.__class__.__name__)

    def test_target_dir(self):
        cmd = commands.GetDom0Logs(dict(target_dir='target'))
        self.assertEquals('target', cmd.target_dir)

    def test_sources(self):
        cmd = commands.GetDom0Logs(dict(sources='t'))
        self.assertEquals('t', cmd.sources)

    def test_a_node_parameter_included(self):
        self.assertIn('node_username', commands.GetDom0Logs.parameters())

    def test_a_logserver_parameter_included(self):
        self.assertIn('logserver_host', commands.GetDom0Logs.parameters())

    def test_executor_parameter_included(self):
        self.assertIn('executor', commands.GetDom0Logs.parameters())

    def test_targetdir_parameter_included(self):
        self.assertIn('target_dir', commands.GetDom0Logs.parameters())

    def test_sources_parameter_included(self):
        self.assertIn('sources', commands.GetDom0Logs.parameters())


class TestRunTests(unittest.TestCase):
    def test_parameters(self):
        cmd = commands.RunTests
        self.assertEquals(
            ['executor', 'node_username', 'node_host', 'change_ref'],
            cmd.parameters()
        )

    def test_changeref_parsing(self):
        cmd = commands.RunTests(dict(change_ref='ref'))
        self.assertEquals('ref', cmd.change_ref)

    def test_create_executor(self):
        cmd = commands.RunTests(dict(executor='print'))
        self.assertEquals('PrintExecutor', cmd.executor.__class__.__name__)

    def test_default_executor(self):
        cmd = commands.RunTests()
        self.assertEquals('FakeExecutor', cmd.executor.__class__.__name__)

    def test_node_created(self):
        cmd = commands.RunTests()
        self.assertIsNotNone(cmd.node)

    def test_execution(self):
        cmd = commands.RunTests(dict(change_ref='CHANGE'))
        cmd()

        self.maxDiff = 4096

        self.assertEquals(
            [
                SCP + ['tempest_exclusion_list', 'NODE_USERNAME@NODE_HOST:/tmp/tempest_exclusion_list'],
                SSH_TO_NODE + instructions.check_out_testrunner(),
                SSH_TO_NODE
                + environment.get_environment('CHANGE')
                + instructions.execute_test_runner()
            ],
            cmd.executor.executed_commands
        )


class TestWatchGerrit(unittest.TestCase):
    def test_fake_gerrit_is_used(self):
        cmd = commands.WatchGerrit()
        self.assertEquals('FakeClient', cmd.gerrit_client.__class__.__name__)

    @mock.patch('osci.gerrit.get_client')
    def test_gerrit_client_factory_called(self, get_client):
        get_client.return_value = 'Client'
        cmd = commands.WatchGerrit()
        self.assertEquals('Client', cmd.gerrit_client)

    def test_event_target(self):
        cmd = commands.WatchGerrit(dict(event_target='fake'))
        self.assertEquals('FakeTarget', cmd.event_target.__class__.__name__)

    @mock.patch('osci.db.DB')
    def test_database_created(self, dbclass):
        dbclass.return_value = 'dbimpl'
        cmd = commands.WatchGerrit(dict(event_target='fake', dburl='someurl'))
        dbclass.assert_called_once_with('someurl')
        self.assertEquals('dbimpl', cmd.database)

    @mock.patch('osci.db.DB')
    def test_queue_created(self, dbclass):
        dbclass.return_value = 'dbimpl'
        cmd = commands.WatchGerrit(dict(event_target='fake', dburl='someurl'))
        dbclass.assert_called_once_with('someurl')
        self.assertEquals('dbimpl', cmd.database)

        self.assertIsNotNone(cmd.queue)
        self.assertEquals('dbimpl', cmd.queue.db)

    def test_passing_gerrit_parameters(self):
        cmd = commands.WatchGerrit(dict(
            gerrit_host='GHOST',
            gerrit_port='29418',
            gerrit_username='GUSER',
        ))

        self.assertEquals('GHOST', cmd.gerrit_client.host)
        self.assertEquals(29418, cmd.gerrit_client.port)
        self.assertEquals('GUSER', cmd.gerrit_client.user)

    def test_get_event(self):
        cmd = commands.WatchGerrit()
        cmd.gerrit_client.fake_insert_event('EVENT')
        self.assertEquals('EVENT', cmd.get_event())

    def test_filtered_event_removes_non_matching(self):
        cmd = commands.WatchGerrit()
        cmd.event_filter = gerrit.DummyFilter(False)
        cmd.gerrit_client.fake_insert_event('EVENT')
        self.assertEquals(None, cmd.get_filtered_event())

    def test_filter_event_if_no_event_available(self):
        cmd = commands.WatchGerrit()
        cmd.event_filter = gerrit.DummyFilter(False)
        self.assertEquals(None, cmd.get_filtered_event())

    def test_parameters(self):
        cmd = commands.WatchGerrit()
        self.assertEquals(
            [
                'gerrit_client', 'gerrit_host', 'event_target',
                'gerrit_port', 'gerrit_username', 'dburl',
                'comment_re', 'projects'
            ],
            cmd.parameters()
        )

    def test_consume_event(self):
        cmd = commands.WatchGerrit(dict(event_target='fake'))
        cmd.consume_event('EVENT')

        self.assertEquals(
            ['EVENT'], cmd.event_target.fake_events
        )

class TestWatchGerritMainLoop(unittest.TestCase):
    def setUp(self):
        self.cmd = cmd = commands.WatchGerrit()
        self.patchers = [
            mock.patch.object(cmd, 'sleep'),
            mock.patch.object(cmd, 'do_event_handling'),
            mock.patch.object(cmd, 'event_seen_recently'),
            mock.patch.object(cmd, '_retry_connect'),
            ]
        [patcher.start() for patcher in self.patchers]
        cmd._retry_connect = mock.Mock()
        cmd._retry_connect.side_effect = [True, False]

    def test_call_connects(self):
        cmd = self.cmd
        cmd.event_seen_recently.return_value = False
        cmd()
        self.assertEquals(1,
                          len(cmd.gerrit_client.fake_connect_calls))
        self.assertEquals(1,
                          len(cmd.gerrit_client.fake_disconnect_calls))

    def test_call_runs_main(self):
        cmd = self.cmd
        cmd.event_seen_recently.side_effect = [True, False]
        cmd()
        cmd.do_event_handling.assert_called_once_with()

    def test_call_reconnects(self):
        cmd = self.cmd
        cmd.event_seen_recently.return_value = False
        cmd._retry_connect.side_effect = [True, True, False]
        cmd()
        self.assertEquals(2,
                          len(cmd.gerrit_client.fake_connect_calls))
        self.assertEquals(2,
                          len(cmd.gerrit_client.fake_disconnect_calls))

    def tearDown(self):
        [patcher.stop() for patcher in self.patchers]


class TestSleep(unittest.TestCase):
    @mock.patch('time.sleep')
    def test_sleep_called(self, sleep):
        cmd = commands.WatchGerrit(dict(sleep_timeout=3))
        cmd.sleep()
        sleep.assert_called_once_with(3)


class TestEventHandling(unittest.TestCase):
    def setUp(self):
        self.cmd = cmd = commands.WatchGerrit()
        self.patchers = [
            mock.patch.object(cmd, 'get_filtered_event'),
            mock.patch.object(cmd, 'consume_event'),
            ]
        [patcher.start() for patcher in self.patchers]

    def test_event_handling(self):
        cmd = self.cmd
        cmd.get_filtered_event.side_effect = ['EVENT', None]

        cmd.do_event_handling()

        cmd.consume_event.assert_called_once_with('EVENT')
        cmd.get_filtered_event.assert_has_calls([mock.call(), mock.call()])

    def test_event_handling_no_event(self):
        cmd = self.cmd
        cmd.get_filtered_event.return_value = None
        cmd.do_event_handling()
        self.assertEquals([], cmd.consume_event.mock_calls)

    def tearDown(self):
        [patcher.stop() for patcher in self.patchers]
