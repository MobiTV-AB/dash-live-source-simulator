"""Segment Muxer. Can multiplex DASH init and media segments (of some kinds).
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

from mp4filter import MP4Filter, InitFilter
from struct import pack, unpack

def uint2str(uInt):
    return pack(">I", uInt)

def str2uint(string4):
    return unpack(">I", string4)[0]


class InitSegmentStructure(MP4Filter):
    """Holds the structure of an initsegment.

    Stores ftyp, mvhd, trex, and trak box data."""

    def __init__(self, fileName=None, data=None):
        MP4Filter.__init__(self, fileName, data)
        self.relevantBoxes = ['ftyp', 'moov']
        self.ftyp = None
        self.mvhd = None
        self.trex = None
        self.trak = None

    def filterbox(self, boxType, data, filePos, path=""):
        if boxType == "ftyp":
            self.ftyp = data
        elif boxType == "mvhd":
            self.mvhd = data
        elif boxType == "trex":
            self.trex = data
        elif boxType == "trak":
            self.trak = data
        if path == "":
            path = boxType
        else:
            path = "%s.%s" % (path, boxType)
        output = ""
        if path in ("moov", "moov.mvex"): # Go deeper
            output += data[:8]
            pos = 8
            while pos < len(data):
                size, boxType = self.checkBox(data[pos:pos+8])
                output += self.filterbox(boxType, data[pos:pos+size], filePos + len(output), path)
                pos += size
        else:
            output = data
        return data


class MultiplexInits(object):
    "Takes two init segments and multiplexes them. The ftyp and mvhd is taken from the first."

    def __init__(self, fileName1=None, fileName2=None, data1=None, data2=None):
        self.iStruct1 = InitSegmentStructure(fileName1, data1)
        self.iStruct1.filter()
        self.iStruct2 = InitSegmentStructure(fileName2, data2)
        self.iStruct2.filter()

    def constructMuxed(self):
        data = []

        data.append(self.iStruct1.ftyp)
        mvexSize = 8 + len(self.iStruct1.trex) + len(self.iStruct2.trex)
        moovSize = 8 + len(self.iStruct1.mvhd) + mvexSize + len(self.iStruct1.trak) + len(self.iStruct2.trak)

        data.append(uint2str(moovSize))
        data.append('moov')
        data.append(self.iStruct1.mvhd)
        data.append(uint2str(mvexSize))
        data.append('mvex')
        data.append(self.iStruct1.trex)
        data.append(self.iStruct2.trex)
        data.append(self.iStruct1.trak)
        data.append(self.iStruct2.trak)

        return "".join(data)


class MediaSegmentStructure(MP4Filter):
    "Holds the box structure of a mediasegment."

    def __init__(self, fileName=None, data=None):
        MP4Filter.__init__(self, fileName, data)
        self.relevantBoxes = ['styp', 'moof', 'mdat']
        self.trunDataOffset = None

    def parseTrun(self, data, pos):
        "Parse trun box and find position of data_offset."
        flags = str2uint(data[8:12]) & 0xffffff
        data_offset_present = flags & 1
        if data_offset_present:
            self.trunDataOffset = str2uint(data[16:20])
            self.trunDataOffsetPosInTraf = pos + 16 - self.trafStart

    def filterbox(self, boxType, data, filePos, path=""):
        if boxType == "styp":
            self.styp = data
        elif boxType == "moof":
            self.moof = data
        elif boxType == "mdat":
            self.mdat = data
        elif boxType == "mfhd":
            self.mfhd = data
        elif boxType == "traf":
            self.traf = data
            self.trafStart = filePos
        elif boxType == "trun":
            self.parseTrun(data, filePos)
        if path == "":
            path = boxType
        else:
            path = "%s.%s" % (path, boxType)
        output = ""
        if path in ("moof", "moof.traf"): # Go deeper
            output += data[:8]
            pos = 8
            while pos < len(data):
                size, boxType = self.checkBox(data[pos:pos+8])
                output += self.filterbox(boxType, data[pos:pos+size], filePos + len(output), path)
                pos += size
        else:
            output = data
        return data

class MultiplexMediaSegments(object):
    "Takes two media segments and multiplexes them like [mdat1][moof1][mdat2][moof2]. The styp and is taken from the first."

    def __init__(self, fileName1=None, fileName2=None, data1=None, data2=None):
        self.mStruct1 = MediaSegmentStructure(fileName1, data1)
        self.mStruct1.filter()
        self.mStruct2 = MediaSegmentStructure(fileName2, data2)
        self.mStruct2.filter()


    def muxOnFragmentLevel(self):
        data = []
        data.append(self.mStruct1.styp)
        data.append(self.mStruct1.moof)
        data.append(self.mStruct1.mdat)
        data.append(self.mStruct2.moof)
        data.append(self.mStruct2.mdat)
        return "".join(data)

    def muxOnSampleLevel(self):
        "Mux media samples into one mdata. This is done by simple concatenation."
        deltaOffset1 = len(self.mStruct2.traf)
        deltaOffset2 = len(self.mStruct1.traf) + len(self.mStruct1.mdat) - 8
        traf1 = self._getTrafWithModOffset(self.mStruct1, deltaOffset1)
        traf2 = self._getTrafWithModOffset(self.mStruct2, deltaOffset2)

        moofSize = 8 + len(self.mStruct1.mfhd) + len(self.mStruct1.traf) + len(self.mStruct2.traf)
        mdatSize = len(self.mStruct1.mdat) + len(self.mStruct2.mdat) - 8

        data = []
        data.append(self.mStruct1.styp)
        data.append(uint2str(moofSize))
        data.append('moof')
        data.append(self.mStruct1.mfhd)
        data.append(traf1)
        data.append(traf2)
        data.append(uint2str(mdatSize))
        data.append('mdat')
        data.append(self.mStruct1.mdat[8:])
        data.append(self.mStruct2.mdat[8:])

        return "".join(data)

    def _getTrafWithModOffset(self, mStruct, deltaOffset):
        if mStruct.trunDataOffset is None:
            return mStruct.traf
        newDataOffset = mStruct.trunDataOffset + deltaOffset
        traf = mStruct.traf
        offsetPos = mStruct.trunDataOffsetPosInTraf
        return traf[:offsetPos] + uint2str(newDataOffset) + traf[offsetPos+4:]




