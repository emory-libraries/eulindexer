from fabric.api import env, local, prefix, put, sudo, task, \
     require, puts, cd, run, abort
from fabric.colors import green, red, cyan
from fabric.contrib import files
from fabric.context_managers import cd, hide, settings
import eulindexer

'''
Overview
========

A basic build deploy script for readux, using Fabric 1.1 or greater.

Usage
-----

To deploy the code, run the **deploy** task with parameters and a
remote server.  To undo a deploy, run the **revert** task with the
same parameters.  To clean up local deploy artifacts, use the
**clean** task.  For more details, use ``fab -d`` with the task name
that you are interested in.

'''

# default settings
env.rev_tag = ''
env.remote_path = '/home/httpd/sites/eulindexer'
env.remote_acct = 'eulindexer'
env.url_prefix = ''
env.remote_proxy = None

def configure(path=None, user=None, url_prefix=None, remote_proxy=None):
    'Configuration settings used internally for the build.'
    env.version = eulindexer.__version__
    config_from_git()
    # construct a unique build directory name based on software version and svn revision
    env.build_dir = 'eulindexer-%(version)s%(rev_tag)s' % env
    env.tarball = 'eulindexer-%(version)s%(rev_tag)s.tar.bz2' % env

    if path:
        env.remote_path = path.rstrip('/')
    if user:
        env.remote_acct = user
    if url_prefix:
        env.url_prefix = url_prefix.rstrip('/')
    if remote_proxy:
        env.remote_proxy = remote_proxy
        puts('setting remote proxy to %(remote_proxy)s' % env)


def config_from_git():
    """Infer revision from local git checkout."""
    # if not a released version, use revision tag 
    env.git_rev = local('git rev-parse --short HEAD', capture=True).strip()
    if eulindexer.__version_info__[-1]:
        env.rev_tag = '-r' + env.git_rev

def prep_source():
    'Export the code from git and do local prep.'
    require('git_rev', 'build_dir',
            used_for='Exporting code from git into build area')
    
    local('mkdir -p build')
    local('rm -rf build/%(build_dir)s' % env)
    # create a tar archive of the specified version and extract inside the bulid directory
    local('git archive --format=tar --prefix=%(build_dir)s/ %(git_rev)s | (cd build && tar xf -)' % env)
    
    # localsettings.py will be handled remotely

    # update wsgi file if a url prefix is requested
    if env.url_prefix:
        env.apache_conf = 'build/%(build_dir)s/apache/eulindexer.conf' % env
        puts(cyan('Updating apache config %(apache_conf)s with url prefix %(url_prefix)s' % env))
        # back up the unmodified apache conf
        orig_conf = env.apache_conf + '.orig'
        local('cp %s %s' % (env.apache_conf, orig_conf))
        with open(orig_conf) as original:
            text = original.read()
        text = text.replace('WSGIScriptAlias / ', 'WSGIScriptAlias %(url_prefix)s ' % env)
        text = text.replace('Alias /static/ ', 'Alias %(url_prefix)s/static ' % env)
        text = text.replace('<Location />', '<Location %(url_prefix)s/>' % env)
        with open(env.apache_conf, 'w') as conf:
            conf.write(text)

def package_source():
    'Create a tarball of the source tree.'
    local('mkdir -p dist')
    local('tar cjf dist/%(tarball)s -C build %(build_dir)s' % env)

# remote functions

def upload_source():
    'Copy the source tarball to the target server.'
    put('dist/%(tarball)s' % env,
        '/tmp/%(tarball)s' % env)

def extract_source():
    'Extract the remote source tarball under the configured remote directory.'
    with cd(env.remote_path):
        sudo('tar xjf /tmp/%(tarball)s' % env, user=env.remote_acct)
        # if the untar succeeded, remove the tarball
        run('rm /tmp/%(tarball)s' % env)
        # update apache.conf if necessary

def setup_virtualenv():
    'Create a virtualenv and install required packages on the remote server.'
    with cd('%(remote_path)s/%(build_dir)s' % env):
        # TODO: we should be using an http proxy here  (pip --proxy)
        # create the virtualenv under the build dir
        sudo('virtualenv --no-site-packages env',
             user=env.remote_acct)
        # activate the environment and install required packages
        with prefix('source env/bin/activate'):
            pip_cmd = 'pip install -r pip-install-req.txt'
            if env.remote_proxy:
                pip_cmd += ' --proxy=%(remote_proxy)s' % env
            sudo(pip_cmd, user=env.remote_acct)

def configure_site():
    'Copy configuration files into the remote source tree.'
    with cd(env.remote_path):
        if not files.exists('localsettings.py'):  
            abort('Configuration file is not in expected location: %(remote_path)s/localsettings.py' % env)
        sudo('cp localsettings.py %(build_dir)s/eulindexer/localsettings.py' % env,
             user=env.remote_acct)

    # collect static files to be served out by apache
    with cd('%(remote_path)s/%(build_dir)s' % env):
        with prefix('source env/bin/activate'):
            sudo('python eulindexer/manage.py collectstatic --noinput',
                 user=env.remote_acct)

def update_links():
    'Update current/previous symlinks on the remote server.'
    with cd(env.remote_path):
        if files.exists('current' % env):
            sudo('rm -f previous; mv current previous', user=env.remote_acct)
        sudo('ln -sf %(build_dir)s current' % env, user=env.remote_acct)


def build_source_package(path=None, user=None, url_prefix='', remote_proxy=''):
    '''Produce a tarball of the source.  '''
    configure(path, user, url_prefix, remote_proxy)
    prep_source()
    package_source()

@task
def deploy(path=None, user=None, url_prefix='', remote_proxy=''):
    '''Deploy the code to a remote server.
    
    Parameters:
      path: base deploy directory on remote host; deploy expects a
            localsettings.py file in thir directory
            Default: /home/httpd/sites/eulindexer
      user: user on the remote host to run the deploy; ssh user (current or
            specified with -U option) must have sudo permission to run deploy
            tasks as the specified user
            Default: eulindexer
      url_prefix: base url if site is not deployed at /
      remote_proxy: HTTP proxy that can be used for pip/virtualenv
	    installation on the **remote** server (server:port)

    Example usage:
      fab deploy:/home/eulindexer/,user -H servername
      fab deploy:user=www-data,url_prefix=/eulindexer -H servername
    '''
    build_source_package(path, user, url_prefix, remote_proxy)
    upload_source()
    extract_source()
    setup_virtualenv()
    configure_site()
    update_links()

    puts(green('Successfully deployed %(build_dir)s to %(host)s' % env))

@task
def revert(path=None, user=None):
    """Update remote symlinks to retore the previous version as current"""
    configure(path, user)
    # if there is a previous link, shift current to previous
    if files.exists('previous'):
        # remove the current link (but not actually removing code)
        sudo('rm current', user=env.remote_acct)
        # make previous link current
        sudo('mv previous current', user=env.remote_acct)
        sudo('readlink current', user=env.remote_acct)

@task
def clean():
    '''Remove local build/dist artifacts generated by deploy task'''
    local('rm -rf build dist')

@task
def rm_old_builds(path=None, user=None, noinput=False):
    '''Remove old build directories on the deploy server.

    Takes the same path and user options as **deploy**.  By default,
    will ask user to confirm deletion.  Use the noinput parameter to
    delete without requesting confirmation.
    '''
    configure(path, user)
    with cd(env.remote_path):
        with hide('stdout'):  # suppress ls/readlink output
            # get directory listing sorted by modification time (single-column for splitting)
            dir_listing = sudo('ls -t1', user=env.remote_acct)
            # get current and previous links so we don't remove either of them
            current = sudo('readlink current', user=env.remote_acct) if files.exists('current') else None
            previous = sudo('readlink previous', user=env.remote_acct) if files.exists('previous') else None
            
        # split dir listing on newlines and strip whitespace
        dir_items = [n.strip() for n in dir_listing.split('\n')] 
        # regex based on how we generate the build directory:
        #   project name, numeric version, optional pre/dev suffix, optional revision #
        build_dir_regex = r'^eulindexer-[0-9.]+(-[A-Za-z0-9_-]+)?(-r[0-9a-f]+)?$' % env
        build_dirs = [item for item in dir_items if re.match(build_dir_regex, item)]
        # by default, preserve the 3 most recent build dirs from deletion
        rm_dirs = build_dirs[3:]
        # if current or previous for some reason is not in the 3 most recent,
        # make sure we don't delete it
        for link in [current, previous]:
            if link in rm_dirs:
                rm_dirs.remove(link)

        if rm_dirs:
            for dir in rm_dirs:
                if noinput or confirm('Remove %s/%s ?' % (env.remote_path, dir)):
                    sudo('rm -rf %s' % dir, user=env.remote_acct)
        else:
            puts('No old build directories to remove')
 
