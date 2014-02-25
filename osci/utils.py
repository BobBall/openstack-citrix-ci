import paramiko
import logging
import socket
import os
import fnmatch
from stat import S_ISREG
import subprocess
import errno

from osci.config import Configuration


def mkdir_recursive(target, target_dir):
    try:
        target.chdir(target_dir)
    except:
        mkdir_recursive(target, os.path.dirname(target_dir))
        target.mkdir(target_dir)

def copy_logs(source_masks, target_dir, host, username, key, upload=True):
    logger = logging.getLogger('citrix.copy_logs')
    transport = paramiko.Transport((host, 22))
    try:
        transport.connect(username=username, pkey=key)
    except socket.error, e:
        logger.exception(e)
        return
    sftp = paramiko.SFTPClient.from_transport(transport)

    if upload:
        source = os
        target = sftp
        sftp_method = sftp.put
    else:
        source = sftp
        target = os
        sftp_method = sftp.get
        
    mkdir_recursive(target, target_dir)

    existing_files = target.listdir(target_dir)
    for filename in existing_files:
        target.remove(os.path.join(target_dir, filename))

    for source_mask in source_masks:
        try:
            source_dir = os.path.dirname(source_mask)
            source_glob = os.path.basename(source_mask)
            for filename in source.listdir(source_dir):
                if not fnmatch.fnmatch(filename, source_glob):
                    continue
                source_file = os.path.join(source_dir, filename)
                if S_ISREG(source.stat(source_file).st_mode):
                    logger.info('Copying %s to %s', source_file, target_dir)
                    try:
                        sftp_method(os.path.join(source_dir, filename),
                                    os.path.join(target_dir, filename))
                    except IOError, e:
                        logger.exception(e)
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise e
            logger.exception(e)
            # Ignore this exception to try again on the next directory
    sftp.close()

def execute_command(command, delimiter=' ', silent=False, return_streams=False):
    command_as_array = command.split(delimiter)
    if not silent:
        logging.debug("Executing command: %s", command_as_array) 
    p = subprocess.Popen(command_as_array, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, errors = p.communicate()
    if p.returncode != 0:
        if not silent:
            logging.error("Error: Could not execute command. "+\
                          "Failed with code %d and errors: %s",
                          p.returncode, errors)
    if not silent:
        logging.debug("Output:%s", output)
    
    if return_streams:
        return p.returncode, output, errors
    return p.returncode == 0


def getSSHObject(ip, username, key_filename):
    if ip is None:
        raise Exception('Seriously?  The host must have an IP address')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
    key = paramiko.RSAKey.from_private_key_file(key_filename)
    try:
        ssh.connect(ip, username=username, pkey=key)
        return ssh
    except Exception, e:
        logging.error('Unable to connect to %s using %s and key %s',
                      ip, username, key_filename)
        logging.exception(e)
        return None

def vote(commitid, vote_num, message):
    #ssh -p 29418 review.example.com gerrit review -m '"Test failed on MegaTestSystem <http://megatestsystem.org/tests/1234>"'
    # --verified=-1 c0ff33
    logging.info("Going to vote commitid %s, vote %s, message %s",
                 commitid, vote_num, message)
    if not Configuration.VOTE_NEGATIVE and vote_num == "-1":
        logging.error("Did not vote -1 for commitid %s, vote %s",
                      commitid, vote_num)
        vote_num = "0"
        message += "\n\nNegative vote suppressed"
    vote_cmd = "ssh$-q$-o$BatchMode=yes$-o$UserKnownHostsFile=/dev/null$-o$StrictHostKeyChecking=no$-p$%d$%s@%s$gerrit$review"%(Configuration.GERRIT_PORT, Configuration.GERRIT_USERNAME, Configuration.GERRIT_HOST)
    vote_cmd = vote_cmd + "$-m$'" + message + "'"
    if Configuration.VOTE_SERVICE_ACCOUNT:
        vote_cmd = vote_cmd + "$--verified=" + vote_num
    vote_cmd = vote_cmd + "$" + commitid
    is_executed = execute_command(vote_cmd, '$')
    if not is_executed:
        logging.error("Error: Could not vote. Voting failed for change %s ", commitid)
    else:
        logging.info("Successfully voted %s for change %s", vote_num, commitid)

