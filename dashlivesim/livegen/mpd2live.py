"""Transform a DASH VoD manifest into a live dito.
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

from xml.etree import ElementTree
import cStringIO
import re
import sys

entities = ['MPD', 'Period', 'AdaptationSet', 'SegmentTemplate']

RE_DURATION = re.compile(r"PT((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+)S)?")
RE_NAMESPACE = re.compile(r"({.*})?(.*)")

class MpdModifierError(Exception):
    pass

class MpdEntity(object):
    "BaseClass for MPD entities."

    def tagAndNamespace(self, fullTag):
        mObj = RE_NAMESPACE.match(fullTag)
        tag = mObj.group(2)
        ns = mObj.group(1)
        return (tag, ns)

    def compareTag(self, fullTag, str):
        tag, ns = self.tagAndNamespace(fullTag)
        return tag == str

    def checkAndAddAttributes(self, node, attribs):
        for a in attribs:
            if node.attrib.has_key(a):
                self.__dict__[a] = node.attrib[a]

    def setValue(self, element, key, data):
        if data.has_key(key):
            element.set(key, str(data[key]))

    def durationToSeconds(self, duration):
        mObj = RE_DURATION.match(duration)
        if not mObj:
            print ("%s does not match a duration")
            sys.exit(3)
        secs = 0
        if mObj.group("hours"):
            secs += int(mObj.group("hours"))*3600
        if mObj.group("minutes"):
            secs += int(mObj.group("minutes"))*60
        if mObj.group("seconds"):
            secs += int(mObj.group("seconds"))
        return secs

class AdaptationSet(MpdEntity):

    def __init__(self, node):
        self.node = node
        self.contentType = None
        self.representations = []
        self.initialization = None
        self.startNumber = None
        self.media = None

    def parse(self):
        self.checkAndAddAttributes(self.node, ('contentType',))
        for child in self.node.getchildren():
            if self.compareTag(child.tag, 'SegmentTemplate'):
                self.checkAndAddAttributes(child, ('initialization', 'startNumber', 'media','duration', 'timescale'))
            elif self.compareTag(child.tag, 'Representation'):
                rep = Representation(self, child)
                rep.parse()
                self.representations.append(rep)

class Representation(MpdEntity):

    def __init__(self, adaptationSet, node):
        self.adaptationSet = adaptationSet
        self.node = node
        self.id = None
        self.bandwidth = None

    def parse(self):
        self.checkAndAddAttributes(self.node, ('id', 'bandwidth'))

    def getInitializationPath(self):
        initPattern = self.adaptationSet.initialization
        initPath = initPattern.replace("$RepresentationID$", self.id).replace("$bandwidth$", self.bandwidth)
        return initPath

    def getMediaPath(self, segNr="%d"):
        mediaPattern = self.adaptationSet.media
        mediaPath = mediaPattern.replace("$RepresentationID$", self.id).replace("$bandwidth$", self.bandwidth)
        mediaPath = mediaPath.replace("$Number$", str(segNr))
        return mediaPath



class MpdModifier(MpdEntity):
    """Modify the mpd to become live. Whatever is input in data is set to these values."""

    def __init__(self, infile):
        self.tree = ElementTree.parse(infile)
        self.mpdNamespace = None
        self.root = self.tree.getroot()
        self.baseURLSet = False
        self.adaptationSets = []
        self.mediaPresentationDuration = None
        self.mediaPresentationDurationInS = None
        self.muxedRep = None
        self.parse()

    def parse(self):
        "Parse and find all the adaptation sets and their representations."
        MPD = self.root
        tag, self.mpdNamespace = self.tagAndNamespace(MPD.tag)
        assert tag == "MPD"
        repIds = {}
        if MPD.attrib.has_key('mediaPresentationDuration'):
            self.mediaPresentationDuration = MPD.attrib['mediaPresentationDuration']
            self.mediaPresentationDurationInS = self.durationToSeconds(self.mediaPresentationDuration)
            print "Found mediaPresentationDuration = %ds" % self.mediaPresentationDurationInS
        for child in MPD:
            if self.compareTag(child.tag, 'Period'):
                for grandChild in child:
                    if self.compareTag(grandChild.tag, 'AdaptationSet'):
                        AS = AdaptationSet(grandChild)
                        AS.parse()
                        repIds[AS.contentType] = AS.representations[0].id
                        self.adaptationSets.append(AS)
        if "video" in repIds.keys() and "audio" in repIds.keys():
            self.muxedRep = "%s_%s" % (repIds["audio"], repIds["video"])

    def getAdaptationSets(self):
        return self.adaptationSets

    def getMuxedRep(self):
        return self.muxedRep

    def getMuxedInitPath(self):
        initPath = None
        for AS in self.adaptationSets:
            if AS.contentType == "video":
                print AS.initialization
                initPath = AS.initialization.replace("$RepresentationID$", self.muxedRep)
        return initPath

    def getMuxedMediaPath(self):
        mediaPath = None
        for AS in self.adaptationSets:
            if AS.contentType == "video":
                mediaPath = AS.media.replace("$RepresentationID$", self.muxedRep).replace("$Number$", "%d")
        return mediaPath

    def process(self, mpdData = {}):
        MPD = self.root
        self.processMPD(MPD, mpdData)


    def makeLiveMpd(self, data):
        """Process the root element (MPD) and set values from data dictionary.

        Typical keys are: availabilityStartTime, timeShiftBufferDepth, minimumUpdatePeriod."""
        MPD = self.root
        MPD.set('type', "dynamic")
        for key in data.keys():
            self.setValue(MPD, key, data)
        if MPD.attrib.has_key('mediaPresentationDuration'):
            del MPD.attrib['mediaPresentationDuration']
        for child in MPD:
            if self.compareTag(child.tag, 'Period'):
                child.set("start", "PT0S") # Set Period start to 0

    def makeLiveMultiplexedMpd(self, data, mediaData):
        self.makeLiveMpd(data)
        MPD = self.root
        audioAS = None
        videoAS = None
        period = None
        audioRep = None
        vidoeRep = None
        for child in MPD:
            if self.compareTag(child.tag, 'Period'):
                period = child
                for grandChild in child:
                    if self.compareTag(grandChild.tag, 'AdaptationSet'):
                        AS = AdaptationSet(grandChild)
                        AS.parse()
                        if AS.contentType == "audio":
                            audioAS = grandChild
                        elif AS.contentType == "video":
                            videoAS = grandChild

        for contentType, mData in mediaData.items():
            trackID = mData['trackID']
            cc = self.makeContentComponent(contentType, trackID)
            videoAS.insert(0, cc)

        del videoAS.attrib['contentType']
        audioRep = audioAS.find(self.mpdNamespace+"Representation")
        videoRep = videoAS.find(self.mpdNamespace+"Representation")
        videoRep.set("id", self.muxedRep)
        try:
            audioCodec = audioRep.attrib["codecs"]
            videoCodec = videoRep.attrib["codecs"]
            combinedCodecs = "%s,%s" % (audioCodec, videoCodec)
            videoRep.set("codecs", combinedCodecs)
        except KeyError:
            print "Could not combine codecs"
        period.remove(audioAS)


    def makeContentComponent(self, contentType, trackID):
        "Create and insert a contentComponent element."
        elem = ElementTree.Element('%sContentComponent' % self.mpdNamespace)
        elem.set("id", str(trackID))
        elem.set("contentType", contentType)
        elem.tail = "\n"
        return elem


    def getCleanString(self, clean=True, targetMpdNameSpace=None):
        "Get a string of all XML cleaned (no ns0 namespace)"
        ofh = cStringIO.StringIO()
        self.tree.write(ofh, encoding="utf-8")#, default_namespace=NAMESPACE)
        value = ofh.getvalue()
        if clean:
            value =  value.replace("ns0:", "").replace("xmlns:ns0=", "xmlns=")
        if targetMpdNameSpace is not None:
            newStr = 'xmlns="%s"' % targetMpdNameSpace
            value = re.sub('xmlns="[^"]+"', newStr, value)
        xmlIntro = '<?xml version="1.0" encoding="utf-8"?>\n'
        return xmlIntro + value
