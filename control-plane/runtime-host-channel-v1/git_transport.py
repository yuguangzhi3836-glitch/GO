"""Immutable candidate Git transport, separate namespace from legacy HK tasks.
Remote/branch/credentials must be trusted installed config, never Request inputs.
Calls use argv, no shell. This module does not provision or discover credentials.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path
from channel import Reject

PREFIX='runtime-host-v1/'
KINDS=('tasks','evidence','registrations')  # registrations is an append-only namespace
KEY=re.compile(r'^(tasks|evidence|registrations)/[A-Za-z0-9][A-Za-z0-9._-]{2,79}\.json$')

class GitTransport:
    def __init__(self, remote, branch, kind, *, git_env):
        if kind not in KINDS or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,79}',branch):
            raise Reject('transport_config')
        if not isinstance(remote,str) or remote.startswith('-') or '\n' in remote:
            raise Reject('remote_config')
        self.remote,self.branch,self.kind=remote,branch,kind
        # Supplied by trusted service with pinned host keys and dedicated identity.
        self.env=dict(git_env)
        self.env.update(GIT_TERMINAL_PROMPT='0',GIT_CONFIG_NOSYSTEM='1')
    def git(self, repo, *args, check=True):
        result=subprocess.run(['git','-C',str(repo),*args],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if check and result.returncode: raise Reject('git_transport_failed')
        return result
    def clone(self, root):
        result=subprocess.run(['git','clone','--quiet','--single-branch','--branch',self.branch,'--',self.remote,str(root)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if result.returncode: raise Reject('git_clone_failed')
    def path(self,key):
        if not KEY.fullmatch(key) or not key.startswith(self.kind+'/'): raise Reject('transport_key')
        return PREFIX+key
    def read(self,key):
        path=self.path(key)
        with tempfile.TemporaryDirectory() as root:
            repo=Path(root)/'repo';self.clone(repo)
            present=self.git(repo,'ls-tree','HEAD','--',path).stdout
            if not present:return None
            if not present.startswith(b'100644 blob '): raise Reject('transport_object_mode')
            data=self.git(repo,'show','HEAD:'+path).stdout
            if len(data)>16384:raise Reject('transport_object_size')
            return data
    def keys(self):
        with tempfile.TemporaryDirectory() as root:
            repo=Path(root)/'repo';self.clone(repo)
            names=self.git(repo,'ls-tree','-r','--name-only','HEAD','--',PREFIX+self.kind+'/').stdout.decode().splitlines()
            keys=[name[len(PREFIX):] for name in names]
            for key in keys:self.path(key)
            return keys
    def create(self,key,raw):
        path=self.path(key)
        if not isinstance(raw,bytes) or len(raw)>16384:raise Reject('transport_size')
        with tempfile.TemporaryDirectory() as root:
            repo=Path(root)/'repo';self.clone(repo)
            target=repo/path
            # Reject links/directories; no overwrite, even for a malformed remote.
            for parent in (repo/PREFIX, repo/PREFIX/self.kind):
                if parent.is_symlink():raise Reject('transport_symlink')
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file() or target.read_bytes()!=raw:raise Reject('transport_conflict')
                return
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(raw)
            self.git(repo,'add','--',path)
            self.git(repo,'-c','user.name=GO Runtime Channel','-c','user.email=runtime-channel@localhost','commit','--quiet','-m','runtime channel: '+key)
            # No force, no automatic rebase/retry on conflict or lost acknowledgement.
            self.git(repo,'push','origin','HEAD:refs/heads/'+self.branch)
