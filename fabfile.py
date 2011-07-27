import json
from xml.etree.ElementTree import XML

from fabric.api import env, local, prefix, put, sudo

import eulindexer

# This is a sample fabfile (http://fabfile.org). It may or may not do what
# you need it to do, so consider it a starting place. This one loads extra
# fab configuration from a json file, tars up the source tree, and copies it
# over to a deployment server. Then it ssh'es over to that server, su's into
# a deployment user, extracts the tarball, sets up a virtualenv, and copies
# in some django settings. Again, use or tweak as you need.
#
# recommended distribution command:
#   $ fab load_config:settings.json deploy
#
# where settings.json is a path to a file that looks something like this:
#   {
#     "hosts": ["myself@stagingserver"], # where we'll ssh/scp
#     "sudo_user": "eulindexer", # the user we'll sudo into to do stuff
#     "extract_path": "/path/to/sites/eulindexer" # where we'll extract the webapp
#   }
#
# if the new version doesn't work, you can revert symlinks with:
#   $ fab load_config:settings.json revert

# env targets

def _base_env():
    """Configure basic env."""
    env.version = eulindexer.__version__
    env.git_rev = 'HEAD'
    env.rev_tag = ''
_base_env()

def _git_env():
    """Try to infer some env from local git checkout."""
    env.git_rev = local('git rev-parse --short HEAD', capture=True).strip()
    env.rev_tag = '-r' + env.git_rev
try:
    if eulindexer.__version_info__[-1]:
        _git_env()
except:
    pass

def _env_paths():
    """Set some env paths based on previously-generated env."""
    env.build_dir = 'eulindexer-%(version)s%(rev_tag)s' % env
    env.tarball = 'eulindexer-%(version)s%(rev_tag)s.tar.bz2' % env
_env_paths()

def load_config(file):
    """Load fab env variables from a local JSON file."""
    with open(file) as f:
        config = json.load(f)
    env.update(config)

# misc helpers

def _sudo(*args, **kwargs):
    """Wrapper for sudo, using a default user in env."""
    if 'user' not in kwargs and 'sudo_user' in env:
        kwargs = kwargs.copy()
        kwargs['user'] = env.sudo_user
    return sudo(*args, **kwargs)

# local build functions

def _package_source():
    """Create a tarball of the source tree."""
    local('mkdir -p dist')
    local('git archive %(git_rev)s --prefix=%(build_dir)s/ | bzip2 > dist/%(tarball)s' % env)

# remote functions

def _copy_tarball():
    """Copy the source tarball to the target server."""
    put('dist/%(tarball)s' % env,
        '/tmp/%(tarball)s' % env)

def _extract_tarball():
    """Extract the remote source tarball in the appropriate directory."""
    _sudo('cp /tmp/%(tarball)s %(extract_path)s/%(tarball)s' % env)
    _sudo('tar xjf %(extract_path)s/%(tarball)s -C %(extract_path)s' % env)

def _create_virtualenv():
    """Construct and configure a remote virtualenv."""
    _sudo('virtualenv --no-site-packages %(extract_path)s/%(build_dir)s/env' % env)
    with prefix('source %(extract_path)s/%(build_dir)s/env/bin/activate' % env):
        _sudo('pip install -r %(extract_path)s/%(build_dir)s/pip-install-req.txt' % env)

def _collect_remote_config():
    """Copy configuration files into the remote source tree."""
    _sudo('cp %(extract_path)s/localsettings.py %(extract_path)s/%(build_dir)s/eulindexer/localsettings.py' % env)

def _update_links():
    """Update current/previous symlinks."""
    _sudo('''if [ -h %(extract_path)s/current ]; then
               rm -f %(extract_path)s/previous;
               mv %(extract_path)s/current %(extract_path)s/previous;
             fi''' % env)
    _sudo('ln -sf %(build_dir)s %(extract_path)s/current' % env)

# bring it all together

def deploy():
    """Deploy the application from source control to a remote server."""
    _package_source()
    _copy_tarball()
    _extract_tarball()
    _create_virtualenv()
    _collect_remote_config()
    _update_links()

def revert():
    """Back out the current version, updating remote symlinks to point back
    to the stored previous one."""
    _sudo('[ -h %(extract_path)/previous ]' % env) # only if previous link exists
    _sudo('rm -f %(extract_path)/current' % env)
    _sudo('ln -s $(readlink %(extract_path)/previous) %(extract_path)/current' % env)
    _sudo('rm %(extract_path)/previous' % env)
    
def clean_local():
    """Remove local files created during deployment."""
    local('rm -rf dist build')

def clean_remote():
    """Remove the deployed application from the remote server."""
    _sudo('rm -rf %(extract_path)s/%(build_dir)s %(extract_path)s/%(tarball)s' % env)
