"""Filter MP4 files and produce modified versions.

The filter is streamlined for DASH or other content with one track per file.
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

from struct import pack, unpack
import datetime

def getTimeScale(fileName=None, data=None):
    "Get timescale from track box (assumes that there is only one track."
    ff = InitFilter(fileName, data)
    ff.filter()
    return ff.getTrackTimeScale()

def getTrackID(fileName=None, data=None):
    "Get trackID from moov with only one trackID."
    ff = InitFilter(fileName, data)
    ff.filter()
    return ff.getTrackID()

def getDuration(fileName=None, data=None):
    "Get duration for a segment"
    ff = DurationFilter(fileName, data)
    ff.filter()
    return ff.getDuration()


class MP4Filter(object):
    """Base class for filters.

    Call filter() to get a filtered version of the file."""

    def __init__(self, fileName=None, data=None):
        if fileName is not None:
            self.data = open(fileName,"rb").read()
        else:
            self.data = data
        self.output = ""
        self.relevantBoxes = [] # Boxes at top-level to filter
        #print "MP4Filter with %s" % fileName

    def checkBox(self, data):
        "Check the type of box starting at position pos."
        size = self.str2uint(data[:4])
        boxType = data[4:8]
        return (size, boxType)

    def str2uint(self, string4):
        return unpack(">I", string4)[0]

    def str2sint(self, string4):
        return unpack(">i", string4)[0]

    def str2ulong(self, string8):
        return unpack(">Q", string8)[0]

    def uint2str(self, uInt):
        return pack(">I", uInt)

    def sint2str(self, uInt):
        return pack(">i", uInt)

    def ulong2str(self, uLong):
        return pack(">Q", uLong)

    def filter (self):
        #print "filter %s" % self.fileName
        self.output = ""
        pos = 0
        while pos < len(self.data):
            size, boxType = self.checkBox(self.data[pos:pos+8])
            boxData = self.data[pos:pos+size]
            if boxType in self.relevantBoxes:
                self.output += self.filterbox(boxType, boxData, len(self.output))
            else:
                self.output += boxData
            pos += size
        self.finalize()
        return self.output

    def finalize(self):
        pass


class InitFilter(MP4Filter):
    "Filter init file and extract track timescale and trackID."

    def __init__(self, fileName=None, data=None, newTrackId=None):
        MP4Filter.__init__(self, fileName, data)
        self.relevantBoxes = ['moov']
        self.trackTimeScale = -1
        self.newTrackId = newTrackId
        self.trackID = None

    def filterbox(self, boxType, data, filePos, path=""):
        "Filter box or tree of boxes recursively."
        if path == "":
            path = boxType
        else:
            path = "%s.%s" % (path, boxType)
        output = ""
        if path in ("moov", "moov.trak", "moov.trak.mdia"):
            output += data[:8]
            pos = 8
            while pos < len(data):
                size, boxType = self.checkBox(data[pos:pos+8])
                output += self.filterbox(boxType, data[pos:pos+size], filePos + len(output), path)
                pos += size
        elif path == "moov.trak.mdia.mdhd": # Find timescale
            self.trackTimeScale = self.str2uint(data[20:24])
            #print "Found trackTimeScale=%d" % self.trackTimeScale
            output = data
        elif path == "moov.trak.tkhd": # Find trackID
            vflags = self.str2uint(data[8:12])
            version = vflags >> 24
            if version == 0:
                trackIdPos = 20
            else:
                trackIdPos = 28
            if self.newTrackId:
                output = data[:trackIdPos]
                output += self.uint2str(self.newTrackId)
                output += data[trackIdPos+4:]
            else:
                self.trackID = self.str2uint(data[trackIdPos:trackIdPos+4])
                output = data
        else:
            output = data
        return output

    def getTrackTimeScale(self):
        return self.trackTimeScale

    def getTrackID(self):
        return self.trackID


class SidxFilter(MP4Filter):
    "Remove sidx from file."

    def __init__(self, fileName=None, data=None):
        MP4Filter.__init__(self, fileName, data)
        self.relevantBoxes = ['sidx']

    def filterbox(self, boxType, data, filePos, path=""):
        "Remove sidx, leave other boxes."
        if boxType == "sidx":
            output = ""
        else:
            output = data
        return output

class TfdtFilter(MP4Filter):
    """Process a file. Change the offset of tfdt if set, and write to outFileName."""

    def __init__(self, fileName, offset=None):
        MP4Filter.__init__(self, fileName)
        self.offset = offset
        self.relevantBoxes = ["moof"]
        self.tfdt = None

    def filterbox(self, boxType, data, filePos, path=""):
        "Filter box or tree of boxes recursively."
        if path == "":
            path = boxType
        else:
            path = "%s.%s" % (path, boxType)
        output = ""
        if path in ("moof", "moof.traf"):
            output += data[:8]
            pos = 8
            while pos < len(data):
                size, boxType = self.checkBox(data[pos:pos+8])
                output += self.filterbox(boxType, data[pos:pos+size], filePos + len(output), path)
                pos += size
        elif path == "moof.traf.tfdt": # Down at tfdt level
            output = self.processTfdt(data, output)
        else:
            output = data
        return output

    def processTfdt(self, data, output):
        """Adjust time of tfdt if offset set."""
        version = ord(data[8])
        if version == 0: # 32-bit baseMediaDecodeTime
            tfdt = self.str2uint(data[12:16])
            if self.offset != None:
                tfdt += self.offset
                output += data[:12] + self.uint2str(tfdt) + data[16:]
            else:
                output += data
        else:
            output = data[:12]
            tfdt = self.str2ulong(data[12:20])
            if self.offset != None:
                tfdt += self.offset
                output += self.ulong2str(tfdt)
            else:
                output += data
        self.tfdt = tfdt
        return output


    def getTfdtValue(self):
        return self.tfdt


class DurationFilter(MP4Filter):
    """Process a mediasegment. Get the tfdt and the total duration by summing up durations in trun(s)."""

    def __init__(self, fileName, offset=None):
        MP4Filter.__init__(self, fileName)
        self.offset = offset
        self.relevantBoxes = ["moof"]
        self.tfdt = None
        self.duration = None

    def filterbox(self, boxType, data, filePos, path=""):
        "Filter box or tree of boxes recursively."
        if path == "":
            path = boxType
        else:
            path = "%s.%s" % (path, boxType)
        output = ""
        if path in ("moof", "moof.traf"):
            output += data[:8]
            pos = 8
            while pos < len(data):
                size, boxType = self.checkBox(data[pos:pos+8])
                output += self.filterbox(boxType, data[pos:pos+size], filePos + len(output), path)
                pos += size
        elif path == "moof.traf.tfdt": # Down at tfdt level
            output = self.processTfdt(data, output)
        elif path == "moof.traf.trun":
            self.readTrun(data)
            output += data
        else:
            output = data
        return output

    def processTfdt(self, data, output):
        """Adjust time of tfdt if offset set."""
        version = ord(data[8])
        if version == 0: # 32-bit baseMediaDecodeTime
            tfdt = self.str2uint(data[12:16])
            if self.offset != None:
                tfdt += self.offset
                output += data[:12] + self.uint2str(tfdt) + data[16:]
            else:
                output += data
        else:
            output = data[:12]
            tfdt = self.str2ulong(data[12:20])
            if self.offset != None:
                tfdt += self.offset
                output += self.ulong2str(tfdt)
            else:
                output += data
        self.tfdt = tfdt
        return output

    def readTrun(self, data):
        "Read trun and find the total duration."
        flags = self.str2uint(data[8:12]) & 0xffffff
        sample_count = self.str2uint(data[12:16])
        pos = 16
        if flags & 0x1:
            pos += 4 # Data offset present
        if flags & 0x4:
            pos += 4 # First sample flags present
        sample_duration_present = flags & 0x100
        sample_size_present = flags & 0x200
        sample_flags_present = flags & 0x400
        sample_comp_time_present = flags & 0x800
        duration = 0
        for i in range(sample_count):
            if sample_duration_present:
                duration += self.str2uint(data[pos:pos+4])
                pos += 4
            if sample_size_present:
                pos += 4
            if sample_flags_present:
                pos += 4
            if sample_comp_time_present:
                pos += 4
        self.duration = duration

    def getTfdtValue(self):
        return self.tfdt

    def getDuration(self):
        return self.duration


class MediaSegmentFilter(MP4Filter):
    """Filter the fragment response to fill in the right segNr and tfdt time given offset.

    Make tfdt 64-bit if needed."""

    def __init__(self, fileName, newSequenceNr, tfdtOffset):
        MP4Filter.__init__(self, fileName)
        self.newSequenceNr = newSequenceNr
        self.tfdtOffset = tfdtOffset

        self.relevantBoxes = ["styp", "sidx", "moof"]
        self.sizeOffsets = []
        self.sizeChange = 0
        self.tfdtValue = None # For testing

    def filterbox(self, boxType, data, filePos, path=""):
        "Filter box or tree of boxes recursively."
        #print "filtering box %s" % boxType
        if path == "":
            path = boxType
        else:
            path = "%s.%s" % (path, boxType)
        output = ""

        #print "%d %s %d" % (len(self.output), boxType, len(data))
        if path == "styp": # Remove lmsg if present
            output += self.processStyp(data)
        elif path == "sidx":
            output += self.processSidx(data)
        elif path in ("moof", "moof.traf"):
            self.sizeOffsets.append(filePos)
            #print "Added offset %d for %s" % (filePos, path)
            output += data[:8]
            pos = 8
            while pos < len(data):
                size, boxType = self.checkBox(data[pos:pos+8])
                output += self.filterbox(boxType, data[pos:pos+size], filePos+pos, path)
                pos += size
        elif path == "moof.traf.trun":
            output += self.processTrun(data)
        elif path == "moof.mfhd": # Change sequenceNumber
            #oldSegNr = self.str2uint(data[12:16])
            output += data[0:12] + self.uint2str(self.newSequenceNr)
        elif path == "moof.traf.tfdt":
            output = self.processTfdt32bit(data, output)
        else:
            output = data
        return output

    def processStyp(self, data):
        "Process the styp box and remove lmsg if present"
        pos = 8
        output = ""
        brands = []
        while pos < len(data):
            b = data[pos:pos+4]
            if b != "lmsg":
                brands.append(b)
            pos += 4
        newSize = 8 + 4*len(brands)
        output += self.uint2str(newSize)
        output += "styp"
        for b in brands:
            output += b
        return output

    def processSidx(self, data):
        "Remove sidx."
        output = ""
        return output

    def processTrun(self, data):
        "Fix offset in trun (if needed). Assume that offset is available. Should check a flag."
        output = data[:16]
        offset = self.str2sint(data[16:20])
        offset += self.sizeChange
        output += self.sint2str(offset)
        output += data[20:]
        return output

    def processTfdt(self, data, output):
        """Generate new timestamps for tfdt and change size of boxes above if needed.

        Note that the input output will be returned and can have another size."""
        version = ord(data[8])
        if version == 0: # 32-bit baseMediaDecodeTime
            self.sizeChange = 4
            output = self.uint2str(self.str2uint(data[:4]) + self.sizeChange)
            output += data[4:8]
            output += chr(1)
            output += data[9:12]
            baseMediaDecodeTime = self.str2uint(data[12:16])
        else: # 64-bit
            output = data[:12]
            baseMediaDecodeTime = self.str2ulong(data[12:20])
        newBaseMediaDecodeTime = baseMediaDecodeTime + self.tfdtOffset
        output += self.ulong2str(newBaseMediaDecodeTime)
        self.tfdtValue = newBaseMediaDecodeTime
        return output

    def processTfdt32bit(self, data, output):
        """Generate new timestamps for tfdt and change size of boxes above if needed.

       Try to fit in 32 bits if possible."""
        version = ord(data[8])

        if version == 0: # 32-bit baseMediaDecodeTime
            baseMediaDecodeTime = self.str2uint(data[12:16])
            newBaseMediaDecodeTime = baseMediaDecodeTime + self.tfdtOffset
            if newBaseMediaDecodeTime < 4294967296:
                output = data[:12]
                output += self.uint2str(newBaseMediaDecodeTime)
            else:
                #print "Forced to change to 64-bit tfdt."
                self.sizeChange = 4
                output = self.uint2str(self.str2uint(data[:4]) + self.sizeChange)
                output += data[4:8]
                output += chr(1)
                output += data[9:12]
                output += self.ulong2str(newBaseMediaDecodeTime)
        else: # 64-bit
            #print "Staying at 64-bit tfdt."
            output = data[:12]
            baseMediaDecodeTime = self.str2ulong(data[12:20])
            newBaseMediaDecodeTime = baseMediaDecodeTime + self.tfdtOffset
            output += self.ulong2str(newBaseMediaDecodeTime)
        self.tfdtValue = newBaseMediaDecodeTime
        return output

    def getTfdtValue(self):
        return self.tfdtValue

    def finalize(self):
        "Change sizes at the end."
        if self.sizeChange:
            for offset in self.sizeOffsets:
                oldSize = self.str2uint(self.output[offset:offset+4])
                newSize = oldSize + self.sizeChange
                #print "%d: size change %d->%d" % (offset, oldSize, newSize)
                self.output = self.output[:offset] + self.uint2str(newSize) + self.output[offset+4:]
