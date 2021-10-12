# tox-pyenv-install

Plugin that allows [tox](https://tox.readthedocs.org/en/latest/)
to [find python executables](https://testrun.org/tox/latest/plugins.html#tox.hookspecs.tox_get_python_executable) 
for python versions that have been installed with 
[pyenv](https://github.com/pyenv/pyenv) and optionally 
to install a exact or the latest patch of a python version using
[`pyenv install`](https://github.com/pyenv/pyenv/blob/master/COMMANDS.md#pyenv-install).

TL;DR: see [full `tox.ini` example](#full-example-tox-configuration) to enable.

## Intro
The automatic installation of requested versions can be enabled using the tox `[testenv]` section configuration option 
[`tox_pyenv_install_auto_install`](#auto-install-python-versions-using-testenv-section-option) 
or the cli flag [`--tox-pyenv-install-auto-install`](#auto-install-python-versions-using-cli-argument).

To resolve the latest installable patch version of a
minor python version like `3.5` the install candidates of 
[`pyenv install -l`](https://github.com/pyenv/pyenv/blob/master/COMMANDS.md#pyenv-install)
are parsed.\
Optionally instead of installing the latest patch version of a minor version 
(like `3.5.10` for searched python minor version `3.5`)
the latest (but earlier) already installed patch version (e.g. `3.5.9`) can be used 
by using the tox `[testenv]` section configuration option 
[`tox_pyenv_install_auto_install_always_latest_patch`](#always-install-latest-patch-version-for-a-minor-version-using-testenv-section-option) 
or the cli flag [`--tox-pyenv-install-auto-install-always-latest-patch`](#always-install-latest-patch-version-for-a-minor-version-using-cli-argument).

To search installed python versions the plugin searches in the `versions` directory of
the pyenv root folder as stated using
[`pyenv root`](https://github.com/pyenv/pyenv/blob/master/COMMANDS.md#pyenv-root).

Moreover the `pyenv` executable is searched using the command `which` (or `where` for Windows systems)
and therefore has to be available in the `PATH` environment variable.

Use `tox -v[v]` to increase verbosity and to show log output of `tox-env-plugin`.

## Allowed python version string formats
`tox-pyenv-install` can parse python version strings in the formats that are used by `pyenv`.\
Those formats include:
- exact notions of a python version like `3.10.0`
- dev versions like `3.11-dev`
- different implementations versions like `anaconda3-5.3.1`, `pypy-5.7.1` or `mambaforge-pypy3`

Moreover some of `tox` default version notation formats are supported.
Those formats include:
- minor python version specifier like `py35` (for CPython 3.5) or `py310` (for CPython 3.10)

Additionally to specifying exact versions 
like `pyenv` uses them, shorthand formats are added:
- for minor versions like `3.5` or `3.10` (without specifing the patch version)

In case of specifying a minor version (using `tox`s or the shorthand format) the
`tox-pyenv-install` plugin resolves the latest available or installed patch
version as described in the intro above.

## Configuration options and CLI arguments
CLI arguments have precedence over options defined in the `tox.ini` `[testenv]` section.

### Auto install python versions
The auto installation of python versions is disabled by default.\
Use the `tox.ini` `[testenv]` section option or the cli argument to enable it.\
**_Important note_**: When installing versions, pyenv builds python versions from source.
Therefore [build tools aswell as commonly used libraries or headers for building python are required,
as stated in the pyenv wiki](https://github.com/pyenv/pyenv/wiki#suggested-build-environment).

#### Auto install python versions using testenv section option
Option: `tox_pyenv_install_auto_install`\
Default: `False`\
Example `tox.ini`:
```
[tox]
envlist =
    py35,
    3.9,
    3.5.9
    
[testenv]
tox_pyenv_install_auto_install=True

deps =
    pyparsing
commands =
    pytest
```

#### Auto install python versions using CLI argument
Argument: `--tox-pyenv-install-auto-install`\
Default: not set\
Example `tox` call: `tox --tox-pyenv-install-auto-install`

### Always install latest patch version for a minor version

The auto installation of python versions installs the latest patch
version (like `3.9.10`) of a minor version (like `3.9`) by default.\
Use the `tox.ini` `[testenv]` section option or the cli argument to disable it.

#### Always install latest patch version for a minor version using testenv section option
Option: `tox_pyenv_install_auto_install_always_latest_patch`\
Default: `True`\
Depends: `tox_pyenv_install_auto_install` or `--tox-pyenv-install-auto-install`\
Example `tox.ini`:
```
envlist =
    py35,
    3.9,
    3.5.9
    
[testenv]
tox_pyenv_install_auto_install=True
tox_pyenv_install_auto_install_always_latest_patch=False

deps =
    pyparsing
commands =
    pytest
```

#### Always install latest patch version for a minor version using CLI argument
Argument: `--tox-pyenv-install-auto-install-always-latest-patch`\
Depends: `--tox-pyenv-install-auto-install` or `tox_pyenv_install_auto_install` in `tox.ini`\
Default: set\
Example `tox` call: `tox --tox-pyenv-install-auto-install --tox-pyenv-install-auto-install-always-latest-patch`


### Force tox using tox-pyenv-install for python executable resolution

The plugin allows tox to resolve the searched python executables in case `tox-pyenv-install` can't find or install 
the requested version.\
Use the `tox.ini` `[testenv]` section option or the cli argument to disable fallback to `tox`s resolve strategy.

### Force tox using tox-pyenv-install for python executable resolution using testenv section option
Option: `tox_pyenv_install_no_fallback`\
Default: `False`\
Example `tox.ini`:
```
[tox]
envlist =
    py310,
    3.9,

[testenv]
tox_pyenv_install_no_fallback=True

deps =
    pyparsing
commands =
    pytest
```

### Force tox using tox-pyenv-install for python executable resolution using CLI argument
Argument: `--tox-pyenv-install-no-fallback`\
Default: not set\
Example `tox` call: `tox --tox-pyenv-install-no-fallback`


## Full example tox configuration
`tox.ini` file:
```
[tox]
envlist =
    py310,
    py38,
    py35,
    3.9,
    pypi
    py27,
    py34,
    3.5.9,
    3.11-dev

[testenv]

; auto install
tox_pyenv_install_auto_install=True

; prefer already installed patch versions of minor python versions
; instead of downloading latest patch version for said minor python version
tox_pyenv_install_auto_install_always_latest_patch=False

; only use pyenv to resolve python executables, 
; don't use tox built in resolution strategies
tox_pyenv_install_no_fallback=True

deps =
    pyparsing

commands =
    python -m aenum.test
```

# Based on [`tox-pyenv`](https://pypi.python.org/pypi/tox-pyenv)
This plugin is a fork of [`tox-pyenv`](https://pypi.python.org/pypi/tox-pyenv) and modifies and extends it.\
The original feature to locate python executables works differently:
In difference to [`tox-pyenv`](https://pypi.python.org/pypi/tox-pyenv) 
this plugin `tox-pyenv-install` does not use `pyenv which` to locate python executables
installed using `pyenv`, but instead searches for python versions in the `versions` directory 
of `pyenv`s root directory.

Credits of the original plugin:\
Version:       1.1.0\
By:            Sam Stavinoha <smlstvnh@gmail.com>\
License: Apache License, Version 2.0