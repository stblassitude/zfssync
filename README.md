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
  -c, --continue   when encountering an error, continue with the next dataset
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

### Copying locally or remotely

`zfssync` can only take one destination, but it can take multiple sources.  It
also works with both local ZFS datasets and remote datasets.  This enables a
number of scenarios to copy collections of datasets:

* locally from one pool to another; for example, when creating a new pool to
  replace an old one
* from the local machine to a cold-standby box
* to a backup server
* from one server to another, by running `zfssync` on a third host, for example
  from the jump server or a management station, crossing from one DMZ to another

You can run zfssync on any machine with Python 3 installed (probably not Windows
though), and the local machine does not have to have ZFS available, as long as
all datasets are remote.


## Examples

Sync all datasets from the local `data` pool to the pool `backups` on
`backupserver`. A new snapshot will be created for each dataset.  The datasets
will be created as children of `backups/webserver/data`.

```sh
$ zfssync -rs data backupserver:backups/webserver/data
```

Sync all newco websites from the webserver to the local system.

```sh
$ zfssync -gs webserver:www/*newco* www/production
```


## Error Message

The following error message indicate invalid parameters to `zfssync`, or a
problem in the ZFS datasets.

* `Command "zfs `...`" exited 1`

  The command could not be executed successfully.  Check stderr output for
  clues.

* `Invalid dataset specification "`_dataset_`"`

  `zfssync` could not parse the dataset specification given.

* `Can't add "`_specification_`": no such dataset`

  The given _specification_ does not resolve to an existing dataset.

* `Need at least one snapshot for source "`_dataset_`"`

  The source dataset has no snapshots. Create a snapshot manually, or pass
  `--snapshot`.

* `Error snapshotting `_dataset_

  Unable to create a snapshot for _dataset_. Check stderr output for clues.

* `Error syncing `_dataset_

  An error occurred during the send/receive process. Check stderr output for
  clues.

### Internal errors

The following error messages should not appear; if they do, it's likely a
programming error.

* `spec and pool both specify a host ("`_hosta_`", "`_hostb_`")`
* `spec and pool specify different pools ("`_poola_`", "`_poolb_`")`

## Warnings

**WARNING**: The script has no provision to stop concurrent execution; you will
need to check yourself that only one instance is running at a time.
**Concurrent modification of ZFS datasets will likely lead to data loss and
general confusion.**

**WARNING**: The zfs receive command includes the `-F` flag, which **will
destroy any data** that is already there.  This means that this script has
**major foot-shooting** potential.  Be extremely careful with the direction
of data transfer, and the destination specification! Use `--notreally` to
preview the operation.

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

## Changelog

### Unreleased

* Improve error handling and documentation
* Add option `--continue` to continue processing sources even after an error
  occurred.

### Release 1.0.0 (2017-07-30)

This is the initial release.

## License, Contributing

Copyright (c) 2017 Stefan Bethke.  See [LICENSE](LICENSE) or the source code for the
2-clause BSD license details.

Have suggestions or improvements? Please feel free to open an issue or a pull
request.
