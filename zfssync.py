#!/usr/bin/env python3

"""
A script to sync ZFS datasets from one host to another.

BSD 2-Clause License

Copyright (c) 2017, Stefan Bethke
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import argparse
import re
import shlex
import subprocess
import sys
import textwrap

from datetime import datetime
from fnmatch import fnmatch
from functools import total_ordering


localhost = 'localhost'
loglevel = 0
dontexecute = False


def log(level, msg):
    global loglevel
    if level <= loglevel:
        print(msg, file=sys.stderr, flush=True)


class ZfssyncException(Exception):
    pass


def shellQuote(cmd):
    return str.join(" ", list(map(lambda x : shlex.quote(x), cmd)))


def shellPopen(host, cmd, nosideeffect, stdout):
    global loglevel
    if host != localhost:
        cmd[0:0] = ['ssh', host]
    if loglevel >= 2:
        if dontexecute and not nosideeffect:
            log(2, "    would execute \"{}\"".format(shellQuote(cmd)))
        else:
            log(2, "    executing \"{}\"".format(shellQuote(cmd)))
    if dontexecute and not nosideeffect:
        return
    return subprocess.Popen(cmd, stdout=stdout, universal_newlines=True)


def shellGenerator(host, cmd, nosideeffect=True):
    popen = shellPopen(host, cmd, nosideeffect, stdout=subprocess.PIPE)
    if not popen:
        return
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line.strip()
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise ZfssyncException("Command \"{}\" exited {}".format(shellQuote(cmd), return_code))


def shellExec(host, cmd, nosideeffect=True):
    popen = shellPopen(host, cmd, nosideeffect, stdout=None)
    if not popen:
        return
    return_code = popen.wait()
    if return_code:
        raise ZfssyncException("Command \"{}\" exited {}".format(shellQuote(cmd), return_code))


def shellPipe(hosta, cmda, hostb, cmdb, nosideeffect=True):
    global loglevel
    if hosta != localhost:
        cmda[0:0] = ['ssh', hosta]
    if hostb != localhost:
        cmdb[0:0] = ['ssh', hostb]
    if loglevel >= 2:
        s = "{} | {}".format(shellQuote(cmda), shellQuote(cmdb))
        if dontexecute and not nosideeffect:
            log(2, "    would execute \"{}\"".format(s))
        else:
            log(2, "    executing \"{}\"".format(s))
    if dontexecute and not nosideeffect:
        return
    pa = subprocess.Popen(cmda, stdout=subprocess.PIPE)
    pb = subprocess.Popen(cmdb, stdin=pa.stdout)
    waiting = [ pa, pb ]
    while len(waiting) > 0:
        for p in waiting:
            try:
                p.wait(1)
            except subprocess.TimeoutExpired:
                continue
            waiting.remove(p)
            if p.returncode != 0:
                for pk in waiting:
                    pk.terminate()
                raise ZfssyncException("Command \"{}\" exited {}".format(shellQuote(p.args),
                    p.returncode))


class Zfspool:
    hostDatasets = {}
    hostSnapshots = {}
    pools = {}

    def __init__(self, name, host=localhost):
        self.host = host
        self.name = name
        self.datasets = None
        self.snapshots = None
        self.updateDatasets()
        self.updateSnapshots()

    def updateHost(self, host):
        l = []
        for line in shellGenerator(host, ['zfs', 'list', '-Honame']):
            l.append(line)
        self.hostDatasets[host] = l
        l = []
        for line in shellGenerator(host, ['zfs', 'list', '-tsnapshot', '-Honame']):
            l.append(line)
        self.hostSnapshots[host] = l

    def updateDatasets(self):
        if self.host not in self.hostDatasets:
            self.updateHost(self.host)
        self.datasets = []
        for i in self.hostDatasets[self.host]:
            if i.startswith(self.name):
                self.datasets.append(i)

    def updateSnapshots(self):
        if self.host not in self.hostSnapshots:
            self.updateHost(self.host)
        self.snapshots = []
        for i in self.hostSnapshots[self.host]:
            if i.startswith(self.name):
                self.snapshots.append(i)

    def __str__(self):
        return "{}:{}".format(self.host, self.name)


def getZfsPool(host, pool):
    """Factory function that returns a Zfspool object for a host and pool"""
    hostpool = "{}:{}".format(host, pool)
    if hostpool not in Zfspool.pools:
        Zfspool.pools[hostpool] = Zfspool(pool, host)
    return Zfspool.pools[hostpool]


@total_ordering
class ZfsDataset:
    specpattern = re.compile('^(?:(?P<host>[^:]+):)?(?P<dataset>(?P<pool>[^/]+)(?P<path>/.*)?)$')
    datasets = {}

    def __init__(self, pool, path):
        self.pool = pool
        self.path = path
        self.dataset = self.pool.name + self.path
        self.snapshots = []
        dsat = self.dataset + "@"
        for s in self.pool.snapshots:
            if s.startswith(dsat):
                self.snapshots.append(s)

    def __str__(self):
        return "{}:{}{}".format(self.pool.host, self.pool.name, self.path)

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        return str(self) == str(other)

    def __gt__(self, other):
        return str(self) > str(other)


def getZfsDataset(spec, pool=None):
    """Factory function that returns a dataset for the given spec"""
    m = ZfsDataset.specpattern.match(spec)
    if not m:
        raise ZfssyncException('Invalid dataset specification "{}"'.format(spec))
    if pool and m.group('host'):
        raise ZfssyncException('spec and pool both specify a host ("{}", "{}")'.format(pool, m.group('host')))
    if pool and m.group('pool') and pool.name != m.group('pool'):
        raise ZfssyncException('spec and pool specify different pools ("{}", "{}")'.format(pool.name, m.group('pool')))
    if not pool:
        host = m.group('host')
        if not host:
            host = localhost
        pool = getZfsPool(host, m.group('pool'))
    path = m.group('path')
    if not path:
        path = ""
    if spec not in ZfsDataset.datasets:
        ZfsDataset.datasets[spec] = ZfsDataset(pool, path)
    return ZfsDataset.datasets[spec]


class Source:
    def __init__(self, spec, glob=False, recursive=False):
        self.spec = getZfsDataset(spec)
        p = self.spec.pool
        self.datasets = set()
        if glob:
            for s in p.datasets:
                if fnmatch(s, self.spec.dataset):
                    self.datasets.add(getZfsDataset(s, p))
        else:
            if self.spec.dataset not in p.datasets:
                raise ZfssyncException("Can't add \"{}:{}\": no such dataset".format(
                    self.spec.pool.host, self.spec.dataset))
            self.datasets.add(self.spec)
        if recursive:
            for ds in set(self.datasets):
                for s in p.datasets:
                    if s.startswith(ds.dataset + '/'):
                        self.datasets.add(getZfsDataset(s, p))

    def __repr__(self):
        return "({} with {} datasets)".format(self.spec, len(self.datasets))


class Destination:
    def __init__(self, spec):
        self.destination = getZfsDataset(spec)

    def targetpath(self, dataset):
        return getZfsDataset("{}:{}{}".format(self.destination.pool.host,
                self.destination.pool.name,
                dataset.path))

    def createsnapshots(self, source, snapshot):
        """ Creates a new snapshot for each of the sources """
        for srcds in sorted(source.datasets):
            s = '{}@{}'.format(srcds.dataset, snapshot)
            if s in srcds.snapshots:
                return
            log(1, "snap: {}:{}".format(srcds.pool.host, s))
            shellExec(srcds.pool.host, ['zfs', 'snapshot', s], nosideeffect=False)
            srcds.snapshots.append(s)

    def relativesnapshots(self, srcds, dstds):
        """ Find the newest snapshot on destination and check it is present
            in source.
        """
        if len(srcds.snapshots) < 1:
            raise ZfssyncException('Need at least one snapshot for source "{}"'.format(srcds))
        if len(dstds.snapshots) < 1:
            return None
        latestDstSnapId = dstds.snapshots[-1][len(dstds.dataset)+1:]
        latestSrcSnap = "{}@{}".format(srcds.dataset, latestDstSnapId)
        if latestSrcSnap not in srcds.snapshots:
            raise ZfssyncException("Latest destination snapshot \"{}\" is not in source \"{}\"".format(latestDstSnapId, srcds))
        return latestDstSnapId

    def sync(self, srcds):
        dstds = self.targetpath(srcds)
        startSnapId = self.relativesnapshots(srcds, dstds)
        endSnap = srcds.snapshots[-1]
        endSnapId = endSnap[len(srcds.dataset)+1:]
        startcmd = []
        if startSnapId:
            if endSnapId == startSnapId:
                log(1, "sync: {} -> {}: datasets are in sync".format(srcds, dstds))
                return
            startcmd = ['-I',  startSnapId]
            log(1, "sync: {} -> {}: syncing snapshots from {} to {}".format(srcds, dstds, startSnapId, endSnapId))
        else:
            log(1, "sync: {} -> {}: syncing all snapshots up to {}".format(srcds, dstds, endSnapId))
        shellPipe(srcds.pool.host, ['zfs', 'send', '-p'] + startcmd + [endSnap],
                dstds.pool.host, ['zfs', 'recv', '-F', dstds.dataset], nosideeffect=False)

    def __repr__(self):
        return "{}".format(self.destination)


def zfssync(sources, destination, snapshot=False, continueOnError=False):
    if snapshot:
        snapshot = datetime.utcnow().strftime('%Y%m%d%H%M')
        for s in sources:
            try:
                destination.createsnapshots(s, snapshot)
            except ZfssyncException as e:
                log(0, "Error snapshotting {}: {}".format(s, e))
                if continueOnError:
                    continue
                else:
                    return 1
    for source in sources:
        for srcds in sorted(source.datasets):
            try:
                destination.sync(srcds)
            except ZfssyncException as e:
                log(0, "Error syncing {}: {}".format(srcds, e))
                if continueOnError:
                    continue
                else:
                    return 1
    return 0


def main(argv):
    global dontexecute, loglevel

    epilog=textwrap.dedent('''\
    source and destination specify source and destination datasets,
    respectively.  They take the form [host:]pool[/child...]

    If a specification has no host, or the host "localhost", ZFS commands will
    be run locally.  If a host is specified, the commands will be run through
    ssh.  You need to configure your ssh client to log in to the target machines
    as root, without requiring a password.

    When --glob is enabled, each source specification is treated as a shell glob
    pattern that is matched against all datasets in the specified pool.  Note
    that the pool name itself is not subject to globbing, and that the pattern
    is matched against the entire path, not just single filenames.

    When --recursive is enabled, all children of the sources specified are
    included as well.

    The snapshot created with --snapshot is named with the current date in time,
    as %Y%m%d%H%M.  If a snapshot of that name exists already, it is ignored.
    ''')
    parser = argparse.ArgumentParser(description='Sync one or more ZFS datasets from one pool to another',
            epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-c', '--continue', dest='cont', action='store_true',
                    help='when encountering an error, continue with the next dataset')
    parser.add_argument('-g', '--glob', dest='glob', action='store_true',
                    help='interpret sources as glob patterns')
    parser.add_argument('-n', '--notreally', dest='notreally', action='store_true',
                    help='print what would be done, but do not do it')
    parser.add_argument('-r', '--recursive', dest='recursive', action='store_true',
                    help='also include child datasets of those specified')
    parser.add_argument('-s', '--snapshot', dest='create', action='store_true',
                    help='create a new snapshot on each source dataset')
    parser.add_argument('-v', '--verbose', dest='verbosity', action='count', default=0,
                    help='verbosity, repeat for more')

    parser.add_argument('sources', metavar='source', type=str, nargs='+',
                    help='a source dataset to be synced')
    parser.add_argument('destination', metavar='destination', type=str, nargs=1,
                    help='the destination to sync the datasets to')

    try:
        args = parser.parse_args()
        loglevel = args.verbosity
        dontexecute = args.notreally

        destination = Destination(args.destination[0])
        sources = []
        for s in args.sources:
            try:
                sources.append(Source(s, recursive=args.recursive, glob=args.glob))
            except ZfssyncException as e:
                log(0, "Error adding source {}: {}".format(s, e))
                if args.cont:
                    continue
                else:
                    sys.exit(1)
        r = zfssync(sources, destination, snapshot=args.create,
                continueOnError=args.cont)
        sys.exit(r)

    except ZfssyncException as e:
        log(0, "Error: {}".format(e))
        sys.exit(1)

if __name__ == "__main__":
    main(sys.argv)
