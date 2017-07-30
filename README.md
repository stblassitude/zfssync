# zfssync

This Python 3 script makes syncing a ZFS dataset from one machine to another
easier.  It is intended to be called from a shell script or another Python
script.

## Usage

```
usage: zfssync.py [-h] [-g] [-n] [-r] [-s] [-v]
                  source [source ...] destination

Sync one or more ZFS datasets from one pool to another

positional arguments:
  source           a source dataset to be synced
  destination      the destination to sync the datasets to

optional arguments:
  -h, --help       show this help message and exit
  -g, --glob       interpret sources as glob patterns
  -n, --notreally  print what would be done, but do not do it
  -r, --recursive  also include child datasets of those specified
  -s, --snapshot   create a new snapshot on each source dataset
  -v, --verbose    verbosity, repeat for more

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

When --recursive is enabled, all children of the sources specified are included
as well.

The snapshot created with --snapshot is named with the current date in time,
as %Y%m%d%H%M.  If a snapshot of that name exists already, it is ignored.
```

## Warnings

**WARNING**: The script has no provision to stop concurrent execution; you will
need to check yourself that only one instance is running at a time.
**Concurrent modification of ZFS datasets will likely lead to data loss and
general confusion.**

**WARNING**: The zfs receive command includes the `-F` flag, which **will
destroy any data** that is already there.  This means that this script has
**major foot-shooting** potential.  Be extremely careful with the direction
of data transfer, and the destination specification!

## Commands Executed

The ZFS commands executed that change data are, depending on the existence of
source and destination datasets and snapshots:

* Create a new snapshot:
```
zfs snapshot pool/dataset@201707301234
```

* Copy over a dataset that does not yet exist on the destination, or has no snapshots:
```
zfs send sourcepool/dataset@201707301234 | ssh host zfs recv -F destpool/dataset
```

* Copy over a dataset that has at least one snapshot:
```
zfs send -I 201707290000 sourcepool/dataset@201707301234 | \
ssh host zfs recv -F destpool/dataset
```

In addition, the script executes `zfs list` on all systems to learn about
existing datasets and snapshots.

## Examples

Sync all datasets from the local `data` pool to the pool `backups` on
`backupserver`. A new snapshot will be created for each dataset.  The datasets
will be created as children of `backups/webserver/data`.

```sh
$ zfssync -rs data backupserver:backups/webserver/data
```

Sync all newco websites from the local host to the test server.

```sh
$ zfssync -gs www/*newco* test-www:www
```


## License, Contributing

Copyright (c) 2017 Stefan Bethke.  See [LICENSE](LICENSE) or the source code for the
2-clause BSD license details.

Have suggestions or improvements? Please feel free to open an issue or a pull
request.
