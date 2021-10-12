"""tox-pyenv-install

Plugin for the tox_get_python_executable using tox's plugin system:

    https://testrun.org/tox/latest/plugins.html#tox.hookspecs.tox_get_python_executable


"""

# __about__
__title__ = 'tox-pyenv-install'
__summary__ = ('tox plugin that uses pyenv '
               'to search and install '
               'python executables.'
               'based on tox-pyenv v1.1.0'
               '(https://github.com/samstav/tox-pyenv) '
               'by Sam Stavinoha <smlstvnh@gmail.com>')
__url__ = 'https://github.com/pojx/tox-pyenv'
__version__ = '0.0.1'
__author__ = 'pojx'
__email__ = 'pojx16@gmail.com'
__keywords__ = ['tox', 'pyenv', 'python']
__license__ = 'Apache License, Version 2.0'

# __about__


import logging
import os
import py
import re
import subprocess
from enum import Enum
from sys import stdout
from tox import hookimpl as tox_hookimpl

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.WARNING)
handler = logging.StreamHandler(stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(name)-12s %(message)s')
handler.setFormatter(formatter)
LOG.addHandler(handler)


class ToxPyenvException(Exception):
    """Base class for exceptions from this plugin."""


class UnknownVersionStringFormat(ToxPyenvException):
    """Unknown format of a python version string."""


class PyenvMissing(ToxPyenvException, RuntimeError):
    """The pyenv program is not installed."""


class PyenvWhichFailed(ToxPyenvException):
    """Calling `pyenv which` failed."""


class PyenvInstallFailed(ToxPyenvException):
    """Calling `pyenv install` failed."""


class PyEnvListInstallCandidatesFailed(ToxPyenvException):
    """Calling `pyenv install -l` failed."""


class PyEnvRootPathFailed(ToxPyenvException):
    """Calling `pyenv root` failed."""


class PyEnvListInstalledFailed(ToxPyenvException):
    """Searching installed python versions in pyenv root failed."""


class PyEnvPluginFailed(ToxPyenvException):
    """tox-pyenv plugin failed."""


class PyVersionDetailLevel(Enum):
    MAJOR = 1
    MINOR = 2
    PATCH = 3


class PyImplementation(Enum):
    CPython = 1
    Other = 2


class PyVersion:
    patch_py_version_re = re.compile(r'^(.*?)(\d+)\.(\d+)\.(\d+)$')  # groups: implementation, major, minor, patch
    minor_py_version_re = re.compile(r'^(.*?)(\d+?)\.(\d+)$')  # groups: implementation, major, minor
    alt_py_version_re = re.compile(r'^(.*?)(\d+?)\.(\d+)[-_\.](.+?)$')  # groups: implementation, major, minor
    tox_py_version_re = re.compile(r'^(?:py|python)(\d)(\d+)$')  # groups: major, minor

    def __init__(self, name, version_string_or_tuple, executable=None, needs_version=True):
        self.name = name

        if isinstance(version_string_or_tuple, str):
            # parse to tuple then make version string according to pyenv
            self.version_tuple, self.version_detail_level = PyVersion.get_any_version_tuple(version_string_or_tuple)
            if needs_version and (not self.version_tuple or not self.version_detail_level):
                raise UnknownVersionStringFormat(
                    "Unknown python version string format '" + version_string_or_tuple + "'")
            self.version_string = self.make_version_string(self.version_tuple) if self.version_tuple else None
        elif isinstance(version_string_or_tuple, tuple):
            # accept directly, infer detail level from length and make version string
            self.version_tuple = version_string_or_tuple
            self.version_detail_level = PyVersionDetailLevel(len(version_string_or_tuple))
            self.version_string = self.make_version_string(self.version_tuple)
        # always just store executable path (if given)
        self.executable = executable

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "PyVersion[" \
               "name='%s', " \
               "version_string='%s', " \
               "version_tuple=%s, " \
               "version_detail_level=%s, " \
               "executable='%s'" \
               "]" % \
               (self.name, self.version_string, self.version_tuple, self.version_detail_level.name, self.executable)

    @classmethod
    def get_implementation(cls, implementation_string):
        return PyImplementation.CPython \
            if not implementation_string or len(implementation_string.strip()) == 0 \
            else PyImplementation.Other

    @classmethod
    def get_tox_version_tuple(cls, version_string):
        match = cls.tox_py_version_re.match(version_string)
        if match:
            return PyImplementation.CPython, int(match.group(1)), int(match.group(2))
        return None

    @classmethod
    def get_patch_version_tuple(cls, version_string):
        match = cls.patch_py_version_re.match(version_string)
        if match:
            return cls.get_implementation(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
        return None

    @classmethod
    def get_minor_version_tuple(cls, version_string):
        match = cls.minor_py_version_re.match(version_string)
        if match:
            return cls.get_implementation(match.group(1)), int(match.group(2)), int(match.group(3))
        return None

    @classmethod
    def get_alt_version_tuple(cls, version_string):
        match = cls.alt_py_version_re.match(version_string)
        if match:
            return cls.get_implementation(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4)
        return None

    @classmethod
    def get_any_version_tuple(cls, version_string):
        match = cls.get_tox_version_tuple(version_string)
        if match:
            return match, PyVersionDetailLevel.MINOR

        match = cls.get_patch_version_tuple(version_string)
        if match:
            return match, PyVersionDetailLevel.PATCH

        match = cls.get_minor_version_tuple(version_string)
        if match:
            return match, PyVersionDetailLevel.MINOR

        match = cls.get_alt_version_tuple(version_string)
        if match:
            return match, PyVersionDetailLevel.MINOR

        return None, None

    @classmethod
    def make_version_string(cls, version_tuple):
        return '.'.join([str(part) for part in version_tuple[1:]])

    @classmethod
    def ensure_int_version_tuple(cls, version_tuple):
        """
        Ensure that every part of a python version tuple is a integer.
        For alternative version strings like 3.11-dev the patch part is a string.
        The alternative part gets replaced with a negative integer to rank
        below actual patch versions.
        """
        return tuple(part if isinstance(part, int) else -1 for part in version_tuple)


class PyEnv:
    @classmethod
    def find_pyenv_executable(cls):
        err = None
        try:
            # pylint: disable=no-member
            pyenv = (getattr(py.path.local.sysfind('pyenv'), 'strpath', 'pyenv')
                     or 'pyenv')
            cmd = ['where' if os.name == 'nt' else 'which', pyenv]
            pipe = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            out, err = pipe.communicate()
            if pipe and pipe.poll() == 0:
                return out.strip()
        except OSError:
            LOG.warning("pyenv missing" + "; STDERR: %s", err)
            raise PyenvMissing(("pyenv missing" + "; STDERR: %s") % err)

    @classmethod
    def run_pyenv(cls, commands, err_string_on_os_error, log_string_on_os_error, exception_type):
        err = None
        try:
            # pylint: disable=no-member
            pyenv = cls.find_pyenv_executable()
            cmd = [pyenv, *commands]
            pipe = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            out, err = pipe.communicate()
        except OSError:
            LOG.warning(log_string_on_os_error + "; STDERR: %s", err)
            raise exception_type((err_string_on_os_error + "; STDERR: %s") % err)
        else:
            return pipe, out, err, cmd

    @classmethod
    def find_using_pyenv(cls, pyversion):
        pipe, out, err, cmd = cls.run_pyenv(
            ['which', pyversion],
            '\'pyenv\': command not found',
            "pyenv doesn't seem to be installed, you probably "
            "don't want this plugin installed either.",
            PyenvWhichFailed
        )
        if pipe and pipe.poll() == 0:
            return out.strip()
        return None  # no error as not found but pyenv worked

    @classmethod
    def install_using_pyenv(cls, pyversion):
        pipe, out, err, cmd = cls.run_pyenv(
            ['install', pyversion.name],
            'install failed',
            "pyenv doesn't seem to be able to install "
            "the requested python version_string " + pyversion.version_string + ".",
            PyenvInstallFailed
        )
        if pipe and pipe.poll() == 0:
            return True
        # no error as not installable but fallthrough might be needed
        # raise PyenvInstallFailed("Can't install version '%s' (%s) using pyenv! STDERR: %s",
        #                          pyversion.version_string, pyversion.name, err)
        LOG.error("Can't install version '%s' (%s) using pyenv! STDERR: %s", pyversion.name, pyversion.name, err)
        return False

    @classmethod
    def get_installable_pyenv_version_strings(cls):
        pipe, out, err, cmd = cls.run_pyenv(
            ['install', '-l'],
            'install -l failed',
            "pyenv doesn't seem to be able to list "
            "available python versions",
            PyEnvListInstallCandidatesFailed
        )
        if pipe and pipe.poll() == 0:
            return [line.strip() for line in out.strip().split('\n')][1:]
        raise PyEnvListInstallCandidatesFailed("Can't list installed pyenv versions! STDERR: %s" % err)

    @classmethod
    def get_installable_pyenv_pyversions(cls):
        return [
            PyVersion(version_string, version_string, needs_version=False)
            for version_string in cls.get_installable_pyenv_version_strings()
        ]

    @classmethod
    def get_installable_pyenv_pyversions_name_dict(cls):
        return {version.name: version for version in cls.get_installable_pyenv_pyversions()}

    @classmethod
    def get_installable_pyenv_pyversions_version_string_dict(cls):
        return {version.version_string: version for version in cls.get_installable_pyenv_pyversions() if
                version.version_string}

    @classmethod
    def get_installable_pyenv_pyversions_version_tuple_dict(cls):
        return {version.version_tuple: version for version in cls.get_installable_pyenv_pyversions() if
                version.version_tuple}

    @classmethod
    def find_installable_pyversion_from_name(cls, name):
        d = cls.get_installable_pyenv_pyversions_name_dict()
        if name in d:
            return d[name]
        return None

    @classmethod
    def find_installable_pyversion_from_version_string(cls, version_string):
        d = cls.get_installable_pyenv_pyversions_version_string_dict()
        if version_string in d:
            return d[version_string]
        return None

    @classmethod
    def find_installable_pyversion_from_version_tuple(cls, version_tuple):
        d = cls.get_installable_pyenv_pyversions_version_tuple_dict()
        if version_tuple in d:
            return d[version_tuple]
        return None

    @classmethod
    def find_installable_pyversion(cls, pyversion):
        result = None
        if pyversion.version_string:
            result = cls.find_installable_pyversion_from_version_string(pyversion.version_string)
        if not result and pyversion.version_tuple:
            result = cls.find_installable_pyversion_from_name(pyversion.version_tuple)
        if not result:
            result = cls.find_installed_pyversion_from_name(pyversion.name)
        return result

    @classmethod
    def get_pyenv_root_path(cls):
        pipe, out, err, cmd = cls.run_pyenv(
            ['root'],
            'pyenv root failed',
            "pyenv doesn't seem to be able to get "
            "root directory",
            PyEnvRootPathFailed
        )
        if pipe and pipe.poll() == 0:
            path = out.strip()
            if not os.path.isdir(path):
                raise PyEnvRootPathFailed("Expected pyenv python root path " + path + " doesn't exist!")
            return path
        raise PyEnvRootPathFailed("Can't find pyenv python root path! STDERR: %s" % err)

    @classmethod
    def get_pyenv_version_path(cls):
        path = cls.get_pyenv_root_path() + '/versions/'
        if not os.path.isdir(path):
            raise PyEnvListInstalledFailed("Expected pyenv python version path " + path + " doesn't exist!")
        return path

    @classmethod
    def get_installed_version_strings(cls):
        return (version_string for version_string in os.listdir(cls.get_pyenv_version_path()))

    @classmethod
    def get_installed_pyversions(cls):
        return [
            PyVersion(
                version_string,
                version_string,
                cls.find_executable_for_installed_pyenv_version_name(version_string),
                needs_version=False,
            )
            for version_string in cls.get_installed_version_strings()
        ]

    @classmethod
    def get_installed_pyversions_name_dict(cls):
        return {version.name: version for version in cls.get_installed_pyversions()}

    @classmethod
    def get_installed_pyversions_version_string_dict(cls):
        return {version.version_string: version for version in cls.get_installed_pyversions() if version.version_string}

    @classmethod
    def get_installed_pyversions_version_tuple_dict(cls):
        return {version.version_tuple: version for version in cls.get_installed_pyversions() if version.version_tuple}

    @classmethod
    def find_installed_pyversion_from_name(cls, name):
        d = cls.get_installed_pyversions_name_dict()
        if name in d:
            return d[name]
        return None

    @classmethod
    def find_installed_pyversion_from_version_string(cls, version_string):
        d = cls.get_installed_pyversions_version_string_dict()
        if version_string in d:
            return d[version_string]
        return None

    @classmethod
    def find_installed_pyversion_from_version_tuple(cls, version_tuple):
        d = cls.get_installed_pyversions_version_tuple_dict()
        if version_tuple in d:
            return d[version_tuple]
        return None

    @classmethod
    def find_installed_pyversion(cls, pyversion):
        result = None
        if pyversion.version_string:
            result = cls.find_installed_pyversion_from_version_string(pyversion.version_string)
        if not result and pyversion.version_tuple:
            result = cls.find_installed_pyversion_from_version_tuple(pyversion.version_tuple)
        if not result:
            result = cls.find_installed_pyversion_from_name(pyversion.name)
        return result

    @classmethod
    def find_executable_for_installed_pyenv_version_name(cls, pyenv_version_name):
        return next(
            (
                path
                for path in
                (cls.get_pyenv_version_path() + pyenv_version_name + '/bin/' + executable for executable in
                 ['python3', 'python'])
                if os.path.isfile(path)
            ),
            None
        )

    @classmethod
    def match_python_version_tuple(cls, version_tuple_less, version_tuple_more):
        ok = True
        for i in range(len(version_tuple_less)):
            if not len(version_tuple_more) > i or version_tuple_less[i] != version_tuple_more[i]:
                ok = False
                break
        return ok

    @classmethod
    def find_latest_installed_patch_version(cls, install_pyversion):
        candidates = []
        for pyversion in cls.get_installed_pyversions():
            if (
                    (
                            pyversion.name.startswith(install_pyversion.name) or
                            (
                                    pyversion.version_string and install_pyversion.version_string and
                                    pyversion.version_string.startswith(install_pyversion.version_string)
                            )
                    ) and
                    install_pyversion.version_tuple and
                    pyversion.version_tuple and
                    cls.match_python_version_tuple(install_pyversion.version_tuple, pyversion.version_tuple)
            ):
                candidates.append(pyversion)
        if len(candidates) == 0:
            return None
        return max(candidates, key=lambda pyversion: PyVersion.ensure_int_version_tuple(pyversion.version_tuple))

    @classmethod
    def find_latest_installable_patch_version(cls, install_pyversion):
        candidates = []
        for pyversion in cls.get_installable_pyenv_pyversions():
            if (
                    (
                            pyversion.name.startswith(install_pyversion.name) or
                            (
                                    pyversion.version_string and install_pyversion.version_string and
                                    pyversion.version_string.startswith(install_pyversion.version_string)
                            )
                    ) and
                    install_pyversion.version_tuple and
                    pyversion.version_tuple and
                    cls.match_python_version_tuple(install_pyversion.version_tuple, pyversion.version_tuple)
            ):
                candidates.append(pyversion)
        if len(candidates) == 0:
            return None
        return max(candidates, key=lambda pyversion: PyVersion.ensure_int_version_tuple(pyversion.version_tuple))


@tox_hookimpl
def tox_get_python_executable(envconfig):
    """Return a python executable for the given environment name, ignoring the base python name.
    The first plugin/hook which returns an executable path will determine it.

    ``envconfig`` is the testenv configuration which contains
    per-testenv configuration, notably the ``.envname`` and ``.basepython``
    setting.
    """

    # set LOG level based on verbosity of tox (-v, -vv)
    try:
        verbose_level = envconfig.config.option.verbose_level
        verbose_to_logging_level_map = [logging.WARNING, logging.INFO, logging.DEBUG]
        logging_level = verbose_to_logging_level_map[verbose_level] \
            if verbose_level < len(verbose_to_logging_level_map) else verbose_to_logging_level_map[-1]
        LOG.setLevel(logging_level)
    except Exception:
        pass

    # case tox version identifier:
    # example: py35             -> (3,5); '3.5          # minor detail level
    #          envname: py35
    #          basepython: python3.5
    #
    # case pyenv version identifier:
    # example: 3.5               -> (3,5); '3.5'         # minor detail level
    #          envname: 3.5
    #          basepython: python system executable
    # example: 3.5.0             -> (3,5,0); '3.5.0'     # patch detail level
    #          envname: 3.5.0
    #          basepython: python system executable
    # example: miniconda3-4.5.12 -> (4,5,12); '4.5.12'   # patch detail level
    #          envname: miniconda3-4.5.12
    #          basepython: python system executable

    try:
        pyversion = PyVersion(envconfig.envname, envconfig.envname)
        LOG.debug("Searching for python version %s", pyversion)

        # first try finding installed
        found_version = PyEnv.find_installed_pyversion(pyversion)
        if found_version and found_version.executable:  # found installed
            LOG.info("Found already installed python version %s", found_version)
            return found_version.executable

        # try installing
        if envconfig.tox_pyenv_install_auto_install:
            # try finding exact installable candidate
            install_pyversion = PyEnv.find_installable_pyversion(pyversion)
            if install_pyversion:
                LOG.debug("Found exact installation candidate python version %s", install_pyversion)
            else:
                if pyversion.version_detail_level == PyVersionDetailLevel.MINOR or \
                        pyversion.version_detail_level == PyVersionDetailLevel.MAJOR:
                    # try finding latest installed patch version for this minor version
                    if not envconfig.tox_pyenv_install_auto_install_always_latest_patch:
                        LOG.debug("Searching latest installed python version %s", pyversion)
                        install_pyversion = PyEnv.find_latest_installed_patch_version(pyversion)
                        if install_pyversion:
                            LOG.debug("Found latest installed python version %s", install_pyversion)
                    # install latest patch version
                    if not install_pyversion:
                        install_pyversion = PyEnv.find_latest_installable_patch_version(pyversion)
                        if install_pyversion:
                            LOG.debug("Found latest patch installation candidate python version %s", install_pyversion)
                else:
                    LOG.debug("Trying installation candidate from search python version %s", install_pyversion)
                    install_pyversion = pyversion

            if install_pyversion:
                # check if already installed
                already_installed_pyversion = PyEnv.find_installed_pyversion(install_pyversion)
                if already_installed_pyversion and already_installed_pyversion.executable:
                    # found already installed
                    LOG.info("Found already installed python version %s", already_installed_pyversion)
                    return already_installed_pyversion.executable

                # else install
                LOG.info("Installing python version %s.....", install_pyversion)
                installed = PyEnv.install_using_pyenv(install_pyversion)
                if installed:
                    # try finding newly installed
                    newly_installed_pyversion = PyEnv.find_installed_pyversion(install_pyversion)
                    if newly_installed_pyversion and newly_installed_pyversion.executable:
                        # found newly installed
                        LOG.info("Found newly installed python version %s", newly_installed_pyversion)
                        return newly_installed_pyversion.executable
                    else:
                        LOG.warning(
                            "Searching for python version '%s' after installation using pyenv through tox-pyenv plugin failed!",
                            install_pyversion.version_string
                        )

                else:
                    LOG.warning(
                        "Installation of python version '%s' using pyenv through tox-pyenv plugin failed!",
                        install_pyversion.name
                    )
            else:
                LOG.warning(
                    "Found no installation candidate of python version '%s'!",
                    pyversion.name
                )
        else:
            # try finding latest installed patch
            latest_installed_pyversion = PyEnv.find_latest_installed_patch_version(pyversion)
            if latest_installed_pyversion and latest_installed_pyversion.executable:
                # found a (latest) patch version for this minor version
                LOG.info("Found latest already installed python version %s", latest_installed_pyversion)
                return latest_installed_pyversion.executable

        LOG.debug("Didn't find or install python version %s", pyversion)

        # cancel if no fallback
        if envconfig.tox_pyenv_install_no_fallback:
            raise PyEnvPluginFailed()

        LOG.info("Failed finding or installing using tox-pyenv plugin, falling back. "
                 "To disable this behavior, set "
                 "tox_pyenv_install_fallback=False in your tox.ini or use "
                 " --tox-pyenv-install-no-fallback on the command line.")
    except ToxPyenvException as e:
        # raise and log if no fallback
        if envconfig.tox_pyenv_install_no_fallback:
            LOG.error("tox-pyenv plugin errored!", e)
            raise e


def _setup_no_fallback(parser):
    """Add the cli argument
     `--tox-pyenv-install-no-fallback`
     and the `[testenv]` option
     `tox_pyenv_install_no_fallback`.

    If this option is set, do not allow fallback to tox's built-in
    strategy for looking up python executables if the call to `pyenv which`
    by this plugin fails. This will allow the error to raise instead
    of falling back to tox's default behavior.

    Default: False
    """

    cli_dest = 'tox_pyenv_install_no_fallback'
    halp = ('If the tox-pyenv plugin fails looking '
            'up or installing the python executable, '
            'do not allow fallback to tox\'s '
            'built-in default logic.')
    # Add a command-line option.
    tox_pyenv_install_group = parser.argparser.add_argument_group(
        title='{0} plugin options'.format(__title__),
    )
    tox_pyenv_install_group.add_argument(
        '--tox-pyenv-install-no-fallback', '-F',
        dest=cli_dest,
        help=halp
    )

    def _pyenv_fallback(testenv_config, value):
        cli_says = getattr(testenv_config.config.option, cli_dest)
        return cli_says or value

    # Add an equivalent tox.ini [testenv] section option.
    parser.add_testenv_attribute(
        name=cli_dest,
        type="bool",
        postprocess=_pyenv_fallback,
        default=False,
        help=halp,
    )


def _setup_auto_install(parser):
    """Add the cli argument
     `--tox-pyenv-install-auto-install`
     and the `[testenv]` option
     `tox_pyenv_install_auto_install`.

    If this option is set, try to install the
    requested python version using `pyenv install`.

    Default: False
    """

    cli_dest = 'tox_pyenv_install_auto_install'
    halp = ('If pyenv has no installed version '
            'for the requested python version'
            ', try installing it with '
            '`pyenv install {basepython}`. '
            '(default: False)')
    # Add a command-line option.
    tox_pyenv_install_group = parser.argparser.add_argument_group(
        title='{0} plugin options'.format(__title__),
    )
    tox_pyenv_install_group.add_argument(
        '--tox-pyenv-install-auto-install', '-I',
        dest=cli_dest,
        help=halp
    )

    def _pyenv_auto_install(testenv_config, value):
        cli_says = getattr(testenv_config.config.option, cli_dest)
        return cli_says or value

    # Add an equivalent tox.ini [testenv] section option.
    parser.add_testenv_attribute(
        name=cli_dest,
        type="bool",
        postprocess=_pyenv_auto_install,
        default=False,
        help=halp,
    )


def _setup_auto_install_always_latest_patch(parser):
    """Add the cli argument
    `--tox-pyenv-install-auto-install-always-latest-patch` and
    the `[testenv]` option
    tox_pyenv_install_auto_install_always_latest_patch.

    If this option is set, always search for and install latest
    python patch version even though a previous minor python
    version was already installed. Else the latest installed
    patch version for the requested minor version is used.

    Default: True
    """

    cli_dest = 'tox_pyenv_install_auto_install_always_latest_patch'
    halp = ('If a python version needs installation '
            'always install the latest patch even '
            'though a earlier patch version is '
            'already installed.')
    # Add a command-line option.
    tox_pyenv_install_group = parser.argparser.add_argument_group(
        title='{0} plugin options'.format(__title__),
    )
    tox_pyenv_install_group.add_argument(
        '--tox-pyenv-install-auto-install-always-latest-patch', '-L',
        dest=cli_dest,
        help=halp
    )

    def _pyenv_auto_install_always_latest_patch(testenv_config, value):
        cli_says = getattr(testenv_config.config.option, cli_dest)
        return cli_says or value

    # Add an equivalent tox.ini [testenv] section option.
    parser.add_testenv_attribute(
        name=cli_dest,
        type="bool",
        postprocess=_pyenv_auto_install_always_latest_patch,
        default=True,
        help=halp,
    )


@tox_hookimpl
def tox_addoption(parser):
    """Add command line option to the argparse-style parser object."""
    _setup_no_fallback(parser)
    _setup_auto_install(parser)
    _setup_auto_install_always_latest_patch(parser)
