'''integration with Subversion repositories

hgsubversion is an extension for Mercurial that allows it to act as a Subversion
client, offering fast, incremental and bidirectional synchronisation.

At this point, hgsubversion is usable by users reasonably familiar with
Mercurial as a VCS. It's not recommended to dive into hgsubversion as an
introduction to Mercurial, since hgsubversion "bends the rules" a little
and violates some of the typical assumptions of early Mercurial users.

Before using hgsubversion, we *strongly* encourage running the
automated tests. See 'README' in the hgsubversion directory for
details.

For more information and instructions, see :hg:`help subversion`.
'''

import os
import sys
import traceback

from mercurial import commands
from mercurial import extensions
from mercurial import help
from mercurial import hg
from mercurial import util as hgutil
from mercurial import demandimport
demandimport.ignore.extend([
    'svn',
    'svn.client',
    'svn.core',
    'svn.delta',
    'svn.ra',
    ])

try:
    from mercurial import templatekw
    # force demandimport to load templatekw
    templatekw.keywords
except ImportError:
   templatekw = None

try:
    from mercurial import revset
    # force demandimport to load revset
    revset.methods
except ImportError:
   revset = None

try:
    from mercurial import subrepo
    # require svnsubrepo and hg >= 1.7.1
    subrepo.svnsubrepo
    hgutil.checknlink
except (ImportError, AttributeError), e:
    subrepo = None

import svncommands
import util
import svnrepo
import wrappers
import svnexternals

svnopts = [
    ('', 'stupid', None,
     'use slower, but more compatible, protocol for Subversion'),
]

# generic means it picks up all options from svnopts
# fixdoc means update the docstring
# TODO: fixdoc hoses l18n
wrapcmds = { # cmd: generic, target, fixdoc, ppopts, opts
    'parents': (False, None, False, False, [
        ('', 'svn', None, 'show parent svn revision instead'),
    ]),
    'diff': (False, None, False, False, [
        ('', 'svn', None, 'show svn diffs against svn parent'),
    ]),
    'pull': (True, 'sources', True, True, []),
    'push': (True, 'destinations', True, True, []),
    'incoming': (False, 'sources', True, True, []),
    'version': (False, None, False, False, [
        ('', 'svn', None, 'print hgsubversion information as well')]),
    'clone': (False, 'sources', True, True, [
        ('T', 'tagpaths', '',
         'list of paths to search for tags in Subversion repositories'),
        ('A', 'authors', '',
         'file mapping Subversion usernames to Mercurial authors'),
        ('', 'filemap', '',
         'file containing rules for remapping Subversion repository paths'),
        ('', 'layout', 'auto', ('import standard layout or single '
                                'directory? Can be standard, single, or auto.')),
        ('', 'branchmap', '', 'file containing rules for branch conversion'),
        ('', 'tagmap', '', 'file containing rules for renaming tags'),
        ('', 'startrev', '', ('convert Subversion revisions starting at the one '
                              'specified, either an integer revision or HEAD; '
                              'HEAD causes only the latest revision to be '
                              'pulled')),
    ]),
}


# only need the discovery variant of this code when we drop hg < 1.6
try:
    from mercurial import discovery
    def findoutgoing(orig, *args, **opts):
        capable = getattr(args[1], 'capable', lambda x: False)
        if capable('subversion'):
            return wrappers.outgoing(*args, **opts)
        else:
            return orig(*args, **opts)
    extensions.wrapfunction(discovery, 'findoutgoing', findoutgoing)
except ImportError:
    pass

def extsetup():
    """insert command wrappers for a bunch of commands"""
    # add the ui argument to this function once we drop support for 1.3

    docvals = {'extension': 'hgsubversion'}
    for cmd, (generic, target, fixdoc, ppopts, opts) in wrapcmds.iteritems():

        if fixdoc and wrappers.generic.__doc__:
            docvals['command'] = cmd
            docvals['Command'] = cmd.capitalize()
            docvals['target'] = target
            doc = wrappers.generic.__doc__.strip() % docvals
            fn = getattr(commands, cmd)
            fn.__doc__ = fn.__doc__.rstrip() + '\n\n    ' + doc

        wrapped = generic and wrappers.generic or getattr(wrappers, cmd)
        entry = extensions.wrapcommand(commands.table, cmd, wrapped)
        if ppopts:
            entry[1].extend(svnopts)
        if opts:
            entry[1].extend(opts)

    try:
        rebase = extensions.find('rebase')
        if not rebase:
            return
        entry = extensions.wrapcommand(rebase.cmdtable, 'rebase', wrappers.rebase)
        entry[1].append(('', 'svn', None, 'automatic svn rebase'))
    except:
        pass

    helpdir = os.path.join(os.path.dirname(__file__), 'help')

    entries = (
        (['subversion'],
         "Working with Subversion Repositories",
         lambda: open(os.path.join(helpdir, 'subversion.rst')).read()),
    )

    # in 1.6 and earler the help table is a tuple
    if getattr(help.helptable, 'extend', None):
        help.helptable.extend(entries)
    else:
        help.helptable = help.helptable + entries

    if templatekw:
        templatekw.keywords.update(util.templatekeywords)

    if revset:
        revset.symbols.update(util.revsets)

    if subrepo:
        subrepo.types['hgsubversion'] = svnexternals.svnsubrepo

def reposetup(ui, repo):
    if repo.local():
       svnrepo.generate_repo_class(ui, repo)

_old_local = hg.schemes['file']
def _lookup(url):
    if util.islocalrepo(url):
        return svnrepo
    else:
        return _old_local(url)

# install scheme handlers
hg.schemes.update({ 'file': _lookup, 'http': svnrepo, 'https': svnrepo,
                    'svn': svnrepo, 'svn+ssh': svnrepo, 'svn+http': svnrepo,
                    'svn+https': svnrepo})

commands.optionalrepo += ' svn'

cmdtable = {
    "svn":
        (svncommands.svn,
         [('u', 'svn-url', '', 'path to the Subversion server.'),
          ('', 'stupid', False, 'be stupid and use diffy replay.'),
          ('A', 'authors', '', 'username mapping filename'),
          ('', 'filemap', '',
           'remap file to exclude paths or include only certain paths'),
          ('', 'force', False, 'force an operation to happen'),
          ('', 'username', '', 'username for authentication'),
          ('', 'password', '', 'password for authentication'),
          ('r', 'rev', '', 'Mercurial revision'),
          ],
         'hg svn <subcommand> ...',
         ),
}

# only these methods are public
__all__ = ('cmdtable', 'reposetup', 'uisetup')
