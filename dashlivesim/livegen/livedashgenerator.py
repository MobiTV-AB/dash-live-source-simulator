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

from optparse import OptionParser
from livegen import LiveGenerator, DEFAULT_TIMESHIFT_BUFFER_DEPTH_IN_S
import ConfigParser
import sys

good_version = "1.0"

class Config:

    def __init__(self, configFile):
        self.configFile = configFile
        self.mpdFile = None
        self.baseDst = None
        self.user = None
        self.password = None
        self.fixNamespace = False
        self.mux = 0
        self.tsbd = 30
        self.noclean = False
        self.parseConfigFile()

    def parseConfigFile(self):
        config = ConfigParser.RawConfigParser()
        config.read(self.configFile)
        version = config.get('General', 'version')
        if version != good_version:
            print "Wrong version of config file: %s (should be %s)" % (version, good_version)
            sys.exit(1)
        self.mpdFile = config.get("Input", "mpdfile")
        self.baseDst = config.get("Output", "basedst")
        try:
            self.user = config.get("Output", "webDavUser")
            self.password = config.get("Output", "wevDavPassword")
        except ConfigParser.NoOptionError:
            pass
        try:
            self.mux = config.getint("Output", "muxedformat")
        except ConfigParser.NoOptionError:
            pass
        try:
            self.fixNameSpace = config.getboolean("Other", "fixnamespace")
        except ConfigParser.NoOptionError:
            pass
        try:
            self.noclean = config.getboolean("Other", "noclean")
        except ConfigParser.NoOptionError:
            pass
        try:
            self.tsbd = config.getint("Other", "timeShiftBufferDepthInS")
        except:
            pass
        try:
            self.adjustAST = config.getint("Other", "adjustAvailabilityStartTime")
        except:
            pass


def main():
    verbose = 0
    usage = "usage: %prog [-v] file.cfg"
    parser = OptionParser(usage)
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose")

    (options, args) = parser.parse_args()
    if options.verbose:
        verbose = 1
    if len(args) != 1:
        parser.error("incorrect number of arguments")
    configFile = args[0]
    c = Config(configFile)
    liveGen = LiveGenerator(c.mpdFile, c.baseDst, c.user, c.password,
                 c.fixNamespace, c.mux, c.tsbd, c.noclean, c.adjustAST, verbose)
    liveGen.start()


if __name__ == "__main__":
    main()
