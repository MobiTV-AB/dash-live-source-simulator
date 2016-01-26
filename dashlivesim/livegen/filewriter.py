"""Write files to disc or push onto WebDAV."""

# The copyright in this software is being made available under the BSD License,
# included below. This software may be subject to other third party and contributor
# rights, including patent rights, and no such rights are granted under this license.
#
# Copyright (c) 2016, Dash Industry Forum.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#  * Redistributions of source code must retain the above copyright notice, this
#  list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright notice,
#  this list of conditions and the following disclaimer in the documentation and/or
#  other materials provided with the distribution.
#  * Neither the name of Dash Industry Forum nor the names of its
#  contributors may be used to endorse or promote products derived from this software
#  without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS AS IS AND ANY
#  EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
#  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
#  IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
#  INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
#  NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
#  PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
#  WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
#  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.

import os, sys
import time
from threading import Thread, Lock
import urlparse
import glob
import re


from easywebdavmod import Client

CREATE_DIRS = True


class FileWriter(object):
    "File writer that handles standard file system as well as webdav using easywebdav."

    def __init__(self, baseDst, user=None, password=None, verbose=0):
        self.baseDst = baseDst
        self.baseParts = urlparse.urlparse(baseDst)
        self.verbose = verbose
        self.webdavThread = None
        self.lock = Lock()
        if self.baseParts[0] == "webdav":
            self.webdavThread = WebDavThread(self.baseDst, self.baseParts, user, password, self.verbose)
            self.webdavThread.start()

    def removeOldFiles(self, relInitPath, relMediaPath):
        "Remove old output files."
        if self.webdavThread:
            self.webdavThread.clean(relInitPath, relMediaPath)
        else:
            absDstInitPath = os.path.join(self.baseDst, relInitPath)
            absDstMediaPath = os.path.join(self.baseDst, relMediaPath)
            if self.verbose:
                print "Removing old init and media files %s %s" % (absDstInitPath, absDstMediaPath)
            if os.path.exists(absDstInitPath):
                os.unlink(absDstInitPath)
            mediaPattern = absDstMediaPath.replace("%d", "*")
            mediaFileList = glob.glob(mediaPattern)
            for f in mediaFileList:
                os.unlink(f)

    def writeFile(self, relPath, data):
        self.lock.acquire()
        try:
            if self.webdavThread:
                self.webdavThread.queueWrite(relPath, data)
            else:
                self.writeToFileSystem(relPath, data)
        finally:
            self.lock.release()

    def writeToFileSystem(self, relPath, data):
        path = os.path.join(self.baseDst, relPath)
        if self.verbose:
            print "FileWriter::Writing file %s" % path
        if CREATE_DIRS:
            dirPath, fileName = os.path.split(path)
            if dirPath != "" and not os.path.exists(dirPath):
                if self.verbose:
                    print "FileWriter::os.makedirs: %s" % dirPath
                os.makedirs(dirPath)
        ofh = open(path, "wb")
        ofh.write(data)
        ofh.close()

    def removeFile(self, relPath):
        self.lock.acquire()
        try:
            if self.webdavThread:
                self.webdavThread.queueDelete(relPath)
            else:
                path = os.path.join(self.baseDst, relPath)
                if os.path.exists(path):
                    os.unlink(path)
                    if self.verbose:
                        print "FileWriter::Deleted %s" % path
        finally:
            self.lock.release()

    def close(self):
        if self.webdavThread:
            self.webdavThread.interrupt()


class WebDavThread(Thread):

    def __init__(self, baseDst, baseParts, user=None, password=None, verbose=0):
        Thread.__init__(self, name="WebDav")
        self.baseDst = baseDst
        self.baseParts = baseParts
        self.user = user
        self.password = password
        self.verbose = verbose
        self.lock = Lock()
        self.conn = None
        self.webdavDirs = set() # Keep track of directories
        self.connectWebDav()
        self.queue = []
        self.interrupted = False

    def connectWebDav(self):
        "Connect to webdav server."
        if self.verbose:
            print "WebDavThread::Connecting to %s" % self.baseDst
        self.conn = Client(self.baseParts[1], username=self.user, password=self.password)
        path = self.baseParts[2:]
        try:
            self.conn.mkdirs(path)
        except Exception, e:
            pass
        self.webdavDirs.add(path)

    def _queueJob(self, command, data):
        self.lock.acquire()
        try:
            self.queue.append((command, data))
            if len(self.queue) > 5:
                sys.stderr.write("\nWARNING: Upload speed not enough. Webdav queue length is %d\n" % len(self.queue))
        finally:
            self.lock.release()

    def queueWrite(self, relPath, data):
        self._queueJob("PUT", (relPath, data))

    def queueDelete(self, relPath):
        self._queueJob("DELETE", relPath)

    def clean(self, relInitPath, relMediaPath):
        "Clean by deleting old files (blocking)."
        self.lock.acquire()
        if self.verbose:
            print "WebDavThread::Cleaning:"
        try:
            self.cleanFiles(relInitPath, relMediaPath)
        finally:
            self.lock.release()

    def getJob(self):
        self.lock.acquire()
        try:
            if len(self.queue) > 0:
                job = self.queue.pop(0)
            else:
                job = None
        finally:
            self.lock.release()
        return job

    def interrupt(self):
        self.interrupted = True

    def run(self):
        while not self.interrupted:
            job = self.getJob()
            if job is not None:
                jobType, data = job
                if jobType == "PUT":
                    self.putFile(*data)
                elif jobType == "DELETE":
                    self.deleteFile(data)
                else:
                    print "WebDavThread::Unknown job type: %s" % jobType
                    self.interrupt()
                    sys.exit(1)
            else:
                time.sleep(0.2)

    def putFile(self, relPath, data):
        "Put a file (create dir if needed)."
        lastDir, file = os.path.split(relPath)
        path = os.path.join(self.baseParts[2], lastDir)
        if not path in self.webdavDirs:
            if self.verbose:
                print "WebDavThread::Checking/creating path %s" % path
            try:
                self.conn.mkdirs(path)
            except Exception, e:
                print e
        self.webdavDirs.add(path)
        filePath = os.path.join(self.baseParts[2], relPath)
        try:
            if self.verbose:
                print "WebDavThread::Uploading data to %s" % filePath
            self.conn.uploaddata(data, filePath)
        except Exception, e:
            print "WebDavThread::Error %s when uploading to %s" % (e, filePath)

    def deleteFile(self, relPath):
        filePath = os.path.join(self.baseParts[2], relPath)
        if self.conn.exists(filePath):
            self.conn.delete(filePath)
            print "WebDavThread::File %s removed" % filePath

    def cleanFiles(self, relInitPath, relMediaPath):
        self.deleteFile(relInitPath)
        mediaPath = os.path.join(self.baseParts[2], relMediaPath)
        dir, filePattern = os.path.split(mediaPath)
        mediaReg = re.compile(mediaPath.replace("%d", "\d+"))
        if self.conn.exists(dir):
            files = self.conn.ls(dir)
            for f in files:
                if mediaReg.match(f.name):
                    self.conn.delete(f.name)
                    print "WebDavThread::File %s removed" % f.name
