"""Generate live DASH content from limited DASH content on disk. Optionally, mux the video and audio.

See __init__.py for general info about this module.
"""


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

import sys
import os
import time
import signal
import re

import mpd2live
import mp4filter
from filewriter import FileWriter
import segmentmuxer

VERSION = "1.0 (webdav) 2015-01-25"

DEFAULT_DASH_NAMESPACE = "urn:mpeg:dash:schema:mpd:2011"
DEFAULT_TIMESHIFT_BUFFER_DEPTH_IN_S = 30
START_UP_DELAY_IN_S = 1 #Minimal diff between ideal time and when to start publishing a segment.
MUX_TYPE_NONE = 0
MUX_TYPE_FRAGMENT = 1
MUX_TYPE_SAMPLES = 2

## Utility functions

def makeTimeStamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

def makeDurationFromS(nrSeconds):
    return "PT%dS" % nrSeconds

class LiveGeneratorError(Exception):
    "Error in LiveGenerator"


class LiveGenerator(object):

    def __init__(self, mpdFile, baseDst, user=None, password=None, fixNamespace=False,
                 muxType=0, tsbd=DEFAULT_TIMESHIFT_BUFFER_DEPTH_IN_S, noClean=False,
                 adjustAST=0, verbose=1):
        self.mpdFile = mpdFile
        self.basePath = os.path.split(mpdFile)[0]
        self.baseDst = baseDst
        self.user = user
        self.password = password
        self.fixNamespace = fixNamespace
        self.muxType = muxType
        self.noClean = noClean
        self.adjustAST = adjustAST
        self.verbose = verbose
        self.interrupted = False
        self.startTime = None
        self.timeShiftBufferDepthInS = tsbd
        self.mediaData = {}
        self.muxedRep = None
        self.muxedPaths = {}
        self.fileWriter = None
        self.mpdSegStartNr = -1
        self.firstSegmentInLoop = -1
        self.lastSegmentInLoop = -1
        self.nrSegmentsInLoop = -1
        signal.signal(signal.SIGINT, self.signal_handler)
        print "Starting MobiTV DASH livegenerator version: %s" % VERSION
        try:
            self.mpdModifier = mpd2live.MpdModifier(self.mpdFile)
            self.loopTime = self.mpdModifier.mediaPresentationDurationInS
            self.fileWriter = FileWriter(baseDst, user, password, verbose)
            self.initMedia()
            self.checkAndUpdateMediaData()
        except Exception, e:
            print "Error in init: %s" % e
            self.stop()

    def initMedia(self):
        "Init media by analyzing the MPD and the media files."
        self.muxedRep = self.mpdModifier.getMuxedRep()
        for AS in self.mpdModifier.getAdaptationSets():
            contentType = AS.contentType
            if contentType is None:
                print "No contentType for adaptation set"
                self.stop()
                sys.exit(1)
            self.mediaData[contentType] = {}
            reps = AS.representations
            if len(reps) > 1:
                print "More than 1 (%d) for content type %s. Not supported" % (len(reps), contentType)
                self.stop()
                sys.exit(2)
            mData = self.mediaData[contentType]
            mData['contentType'] = contentType
            rep = reps[0]
            initPath = rep.getInitializationPath()
            mData['relInitPath'] = initPath
            mData['absInitPath'] = os.path.join(self.basePath, initPath)
            mData['trackID'] = mp4filter.getTrackID(mData['absInitPath'])
            print "%s trackID = %d" % (contentType, mData['trackID'])
            mData['relMediaPath'] = rep.getMediaPath()
            mData['absMediaPath'] = os.path.join(self.basePath, rep.getMediaPath())

            self.getSegmentRange(mData)
            mData['startNumber'] = int(AS.startNumber)
            mData['segDuration'] = int(AS.duration)
            mData['clock'] = mp4filter.getTimeScale(mData['absInitPath'])
            mData['presentationDurationInS'] = self.mpdModifier.mediaPresentationDurationInS
            if self.muxType == MUX_TYPE_NONE and not self.noClean:
                self.fileWriter.remove_old_files(mData['relInitPath'], mData['relMediaPath'])
            if self.verbose:
                print "%s data: " % contentType
                for (k,v) in mData.items():
                    print "  %s=%s" % (k, v)
        if self.muxType != MUX_TYPE_NONE:
            self.muxedPaths["relInitPath"] = self.mpdModifier.getMuxedInitPath()
            self.muxedPaths["relMediaPath"] = self.mpdModifier.getMuxedMediaPath()
            if not self.noClean:
                self.fileWriter.remove_old_files(self.muxedPaths["relInitPath"], self.muxedPaths["relMediaPath"])

    def getSegmentRange(self, mData):
        "Search the directory for the first and last segment and set firstNumber and lastNumber for this MediaType."
        mediaDir, mediaName = os.path.split(mData['absMediaPath'])
        mediaRegexp = mediaName.replace("%d", "(\d+)").replace(".", "\.")
        mediaReg = re.compile(mediaRegexp)
        files = os.listdir(mediaDir)
        numbers = []
        for f in files:
            matchObj = mediaReg.match(f)
            if matchObj:
                number = int(matchObj.groups(1)[0])
                numbers.append(number)
        numbers.sort()
        for i in range(1,len(numbers)):
            if numbers[i] != numbers[i-1] + 1:
                raise LiveGeneratorError("%s segment missing between %d and %d" % mData['contentType'], numbers[i], numbers[i-1])
        print "Found %s segments %d - %d" % (mData['contentType'], numbers[0] , numbers[-1])
        mData['firstNumber'] = numbers[0]
        mData['lastNumber'] = numbers[-1]

    def checkAndUpdateMediaData(self):
        """Check all segments for good values and return startTimes and total duration."""
        lastGoodSegments = []
        segDuration = None
        print "Checking all the media segment durations for deviations."
        for mediaType in self.mediaData.keys():
            mediaData = self.mediaData[mediaType]
            if self.firstSegmentInLoop >= 0:
                assert mediaData['firstNumber'] == self.firstSegmentInLoop
            else:
                self.firstSegmentInLoop = mediaData['firstNumber']
            if self.mpdSegStartNr >= 0:
                assert  mediaData['startNumber'] == self.mpdSegStartNr
            else:
                self.mpdSegStartNr = mediaData['startNumber']
            mediaData['endNr'] =  None
            mediaData['startTick'] = None
            mediaData['endTick'] = None
            if segDuration is None:
                segDuration = mediaData['segDuration']
                self.segDuration = segDuration
            else:
                assert segDuration == mediaData['segDuration']
            clock = mediaData['clock']
            segTicks = segDuration*clock
            maxDiffInTicks = int(clock*0.1) # Max 100ms
            segNr = mediaData['firstNumber']
            while (True):
                segmentPath = mediaData['absMediaPath'] % segNr
                if not os.path.exists(segmentPath):
                    if self.verbose:
                        print "\nLast good %s segment is %d, endTime=%.3fs, totalTime=%.3fs" % (
                            mediaType, mediaData['endNr'], mediaData['endTime'], mediaData['endTime']-mediaData['startTime'])
                    break
                ff = mp4filter.DurationFilter(segmentPath)
                ff.filter()
                tfdt = ff.getTfdtValue()
                duration = ff.getDuration()
                if mediaData['startTick'] is None:
                    mediaData['startTick'] = tfdt
                    mediaData['startTime'] = mediaData['startTick']/float(mediaData['clock'])
                    print "First %s segment is %d starting at time %.3fs" % (mediaType, segNr,
                                                                                 mediaData['startTime'])
                # Check that there is not too much drift. We want to end with at most maxDiffInTicks
                endTick = tfdt + duration
                idealTicks = (segNr - mediaData['firstNumber'] + 1)*segTicks + mediaData['startTick']
                absDiffInTicks = abs(idealTicks - endTick)
                if absDiffInTicks < maxDiffInTicks:
                    # This is a good wrap point
                    mediaData['endTick'] = tfdt + duration
                    mediaData['endTime'] = mediaData['endTick']/float(mediaData['clock'])
                    mediaData['endNr'] = segNr
                segNr += 1
                if self.verbose:
                    sys.stdout.write(".")
            lastGoodSegments.append(mediaData['endNr'])
        self.lastSegmentInLoop = min(lastGoodSegments)
        self.nrSegmentsInLoop = self.lastSegmentInLoop-self.firstSegmentInLoop+1
        self.loopTime = self.nrSegmentsInLoop*self.segDuration
        if self.verbose:
            print ""
        print "Will loop segments %d-%d with loop time %ds" % (self.firstSegmentInLoop, self.lastSegmentInLoop, self.loopTime)

    def start(self):
        "Start the actual live segment generation."
        self.startTime = int(time.time())
        self.mpdAvailabilityStartTIme = self.startTime + max(START_UP_DELAY_IN_S, self.adjustAST)
        try:
            self.processMpd()
            self.processAndPushInitSegments()
            self.pushMpd()
            self.startSegmentPushLoop()
        except Exception, e:
            print "Error in loop: %s" % e
        finally:
            self.stop()

    def signal_handler(self, signal, frame):
        print "Stopping..."
        self.stop()

    def stop(self):
        self.interrupted = True
        if self.fileWriter:
            self.fileWriter.close()

    def processMpd(self):
        """Process the MPD and make an appropriate live version."""
        mpdData = {"availabilityStartTime" :makeTimeStamp(self.mpdAvailabilityStartTIme),
                   "timeShiftBufferDepth" : makeDurationFromS(self.timeShiftBufferDepthInS),
                   "minimumUpdatePeriod" : "PT30M"}
        if not self.muxType != MUX_TYPE_NONE:
            self.mpdModifier.makeLiveMpd(mpdData)
        else:
            self.mpdModifier.makeLiveMultiplexedMpd(mpdData, self.mediaData)
            self.muxedRep = self.mpdModifier.getMuxedRep()
        targetMpdNamespace = None
        if self.fixNamespace:
            targetMpdNamespace = DEFAULT_DASH_NAMESPACE
        self.mpd = self.mpdModifier.getCleanString(True, targetMpdNamespace)

    def processAndPushInitSegments(self):
        """Make init segments and push/store them.

        If no multiplex is needed, just push the segments with the right relative path.
        """
        if self.muxType == MUX_TYPE_NONE:
            for mediaType in self.mediaData.keys():
                inPath = self.mediaData[mediaType]['absInitPath']
                relPath = self.mediaData[mediaType]['relInitPath']
                data = open(inPath, "r").read()
                self.fileWriter.write_file(relPath, data)
        else:
            audioPath = self.mediaData["audio"]['absInitPath']
            videoPath = self.mediaData["video"]["absInitPath"]
            mi = segmentmuxer.MultiplexInits(audioPath, videoPath)
            data = mi.constructMuxed()
            self.fileWriter.write_file(self.muxedPaths["relInitPath"], data)

    def pushMpd(self):
        "Push/store the MPD."
        mpdPath = os.path.basename(self.mpdFile)
        if self.muxType != MUX_TYPE_NONE:
            base, ext = os.path.splitext(mpdPath)
            mpdPath= "".join((base, "_mux", ext))
            print "Muxing media on %s level" % (MUX_TYPE_FRAGMENT and "fragment" or "sample")
        self.fileWriter.write_file(mpdPath, self.mpd)
        print "MPD written to %s" % mpdPath

    def startSegmentPushLoop(self):
        """Loop and generate segments given info in manifest file."""
        print "Starting segment push loop"
        nrWrapArounds = 0
        offset = 0
        mediaTypes = self.mediaData.keys()

        filesOnDiskLists = {}
        if self.muxType == MUX_TYPE_NONE:
            for mType in mediaTypes:
                filesOnDiskLists[mType] = []
        else:
            filesOnDiskLists["mux"] = []
        maxNrFilesToKeep = self.timeShiftBufferDepthInS/self.segDuration + 2 # For some margin
        if self.verbose:
            print "maxNrFilesToKeep = %d" % maxNrFilesToKeep

        outSegNr = self.mpdSegStartNr
        inSegNr = self.firstSegmentInLoop
        while not self.interrupted:
            nrWrapArounds = (inSegNr - self.firstSegmentInLoop) // self.nrSegmentsInLoop
            inFileSegNr = inSegNr - nrWrapArounds*self.nrSegmentsInLoop
            timeOffset = nrWrapArounds*self.loopTime
            publishTime = ((inSegNr-self.firstSegmentInLoop+1)*self.segDuration) + self.startTime
            now = time.time()
            while now < publishTime:
                time.sleep(min(publishTime-now, 0.1))
                now = time.time()

            data = {}

            for mType in mediaTypes:
                inFilePath = self.mediaData[mType]['absMediaPath'] % inFileSegNr
                trackTimeScale = self.mediaData[mType]['clock']
                # Set tfdtOffset so that the mediaTime starts at 0 at the start of the services
                tfdtOffset = -self.mediaData[mType]['startTick'] + timeOffset*trackTimeScale
                ff = mp4filter.MediaSegmentFilter(inFilePath, outSegNr, tfdtOffset)
                ff.filter()
                data[mType] = ff.output

            if self.muxType == MUX_TYPE_NONE:
                for mType in mediaTypes:
                    outFilePath = self.mediaData[mType]['relMediaPath'] % outSegNr
                    self.fileWriter.write_file(outFilePath, data[mType])
                    self.manageFilesOnDisk(outFilePath, filesOnDiskLists[mType], maxNrFilesToKeep)
            else:
                mM = segmentmuxer.MultiplexMediaSegments(data1=data["audio"], data2=data["video"])
                if self.muxType == MUX_TYPE_FRAGMENT:
                    muxedData = mM.muxOnFragmentLevel()
                elif self.muxType == MUX_TYPE_SAMPLES:
                    muxedData = mM.muxOnSampleLevel()
                else:
                    print "Error: Unknown mux type %d" % self.muxType
                    self.stop()
                    sys.exit(3)
                outFilePath = self.muxedPaths['relMediaPath'] % outSegNr
                self.fileWriter.write_file(outFilePath, muxedData)
                self.manageFilesOnDisk(outFilePath, filesOnDiskLists["mux"], maxNrFilesToKeep)

            if self.verbose:
                now = time.time()
                segAvailTime = self.mpdAvailabilityStartTIme + (outSegNr - self.mpdSegStartNr + 1)*self.segDuration
                timeDiff = segAvailTime - now
                print "Wrote %d'th segment from %d to %d, %.1fs before ideal time" % (
                    inSegNr-self.firstSegmentInLoop+1, inFileSegNr, outSegNr, timeDiff)
            inSegNr += 1
            outSegNr += 1
            if not self.verbose:
                sys.stdout.write(".")
                sys.stdout.flush()

    def manageFilesOnDisk(self, outFilePath, filesOnDiskList, maxNrFiles):
        "Remove times outside timeShiftBufferDepth is configured."
        filesOnDiskList.append(outFilePath)
        while len(filesOnDiskList) > maxNrFiles:
            fileToRemove = filesOnDiskList.pop(0)
            self.fileWriter.remove_file(fileToRemove)


def main():
    from optparse import OptionParser
    verbose = 0
    usage = "usage: %prog [options] mpdPath dstDir"
    parser = OptionParser(usage)
    parser.add_option("-f", "--fixnamespace", dest="fixNamespace", action="store_true", help="Fix MPD namespace")
    parser.add_option("-m", "--mux", dest="mux", type="int", help="Multiplex 1 (fragment) or 2 (samples) into *_mux.mpd",
                      default=0)
    parser.add_option("-t", "--tsbd", dest="tsbd", help="timeShiftBufferDepth (s)", type="int",
                      default = DEFAULT_TIMESHIFT_BUFFER_DEPTH_IN_S)
    parser.add_option("-n", "--noclean", dest="noclean", help="leave old files", action="store_true")
    parser.add_option("-a", "--adjustast", dest="adjustast", help="Adjust availabilityStartTime (in s)", type="int",
                      default = 0)
    parser.add_option("-u", "--user", dest="user", help="WebDAV user")
    parser.add_option("-p", "--password", dest="password", help="WebDAV password")
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose")

    (options, args) = parser.parse_args()
    if options.verbose:
        verbose = 1
    if len(args) < 2:
        parser.error("incorrect number of arguments")
    mpdFile = args[0]
    baseDst = args[1]
    liveGen = LiveGenerator(mpdFile, baseDst, options.user, options.password,
                 options.fixNamespace, options.mux, options.tsbd, options.noclean,
                 options.adjustast, verbose)
    liveGen.start()


if __name__ == "__main__":
    main()
