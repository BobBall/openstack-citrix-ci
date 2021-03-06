import textwrap


def get_environment(change_ref):
    return textwrap.dedent("""
    ZUUL_URL=https://review.openstack.org
    ZUUL_REF=%s
    PYTHONUNBUFFERED=true
    DEVSTACK_GATE_TEMPEST=1
    DEVSTACK_GATE_TEMPEST_FULL=1
    DEVSTACK_GATE_VIRT_DRIVER=xenapi
    DEVSTACK_GATE_TIMEOUT=180
    APPLIANCE_NAME=devstack
    ENABLED_SERVICES=g-api,g-reg,key,n-api,n-crt,n-obj,n-cpu,n-sch,horizon,mysql,rabbit,sysstat,dstat,pidstat,s-proxy,s-account,s-container,s-object,n-cond
    """ % change_ref).split()
