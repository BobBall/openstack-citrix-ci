from ctxosci import node
from ctxosci import executor
from ctxosci import logserver


class GetDom0Logs(object):
    def __init__(self, env=None):
        env = env or dict()
        self.executor = executor.create_executor(env.get('executor'))
        self.node = node.Node(env)
        self.logserver = logserver.Logserver(env)
        self.target_dir = env.get('target_dir', 'TARGET_DIR')
        self.sources = env.get('sources', 'SOURCES')

    @classmethod
    def parameters(cls):
        return (
            ['executor']
            + node.Node.parameters()
            + ['sources']
            + logserver.Logserver.parameters()
            + ['target_dir']
        )

    def __call__(self):
        self.executor.pipe_run(
            self.node.run_on_dom0(
                "tar --ignore-failed-read -czf - {0}".format(
                    self.sources).split()
            ),
            self.logserver.run(
                'tar -xzf - -C {0}'.format(self.target_dir).split()
            )
        )


class CheckConnection(object):
    def __init__(self, env=None):
        env = env or dict()
        self.executor = executor.create_executor(env.get('executor'))
        self.node = node.Node(env)
        self.logserver = logserver.Logserver(env)

    @classmethod
    def parameters(cls):
        return (
            ['executor']
            + node.Node.parameters()
            + logserver.Logserver.parameters()
        )

    def __call__(self):
        checks = [
            (
                'Connection to Node',
                self.node.run(['true'])
            ),
            (
                'Connection from Node to dom0',
                self.node.run_on_dom0(['true'])
            ),
            (
                'Connection to Logserver',
                self.logserver.run(['true'])
            ),
        ]

        for message, args in checks:
            print message
            if 0 == self.executor.run(args):
                print "OK"
            else:
                print "FAIL, aborting"
                return 1

        return 0

